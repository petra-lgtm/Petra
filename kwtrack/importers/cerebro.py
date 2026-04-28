"""Helium10 Cerebro CSV importer.

Cerebro exports vary slightly across regions and product updates: some columns
are localised (German files use "Suchvolumen" etc.), and per-ASIN rank columns
appear when multiple ASINs are queried. We map a stable set of core columns
into typed snapshot fields and stash everything else as JSON in `extra_json`.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from kwtrack.db import ensure_keyword, ensure_tracking_row
from kwtrack.markets import normalize as normalize_market


# Header alias map. Keys are the snapshot column names; values are lists of
# header strings (case-insensitive, whitespace-collapsed) that map to them.
# Includes EN, DE, FR variants observed in Cerebro exports.
HEADER_ALIASES: dict[str, tuple[str, ...]] = {
    "phrase": (
        "keyword phrase",
        "keyword",
        "schluesselwortphrase",
        "schlusselwortphrase",
        "phrase de mot-cle",
    ),
    "cerebro_iq_score": ("cerebro iq score",),
    "search_volume": ("search volume", "suchvolumen", "volume de recherche"),
    "search_volume_trend": (
        "search volume trend",
        "suchvolumen-trend",
        "tendance du volume de recherche",
    ),
    "sponsored_asins": ("sponsored asins",),
    "competing_products": (
        "competing products",
        "konkurrierende produkte",
        "produits concurrents",
    ),
    "cpr": ("cpr",),
    "title_density": ("title density", "titel-dichte", "densite de titre"),
    "amazon_recommended_rank": (
        "amazon recommended rank",
        "amazon recommended position",
    ),
    "sponsored_rank": ("sponsored rank", "sponsored position"),
    "organic_rank": ("organic rank", "organic position", "organische position"),
    "keyword_sales": ("keyword sales", "keyword-verkaeufe", "ventes par mot-cle"),
    "aba_total_click_share": (
        "aba total click share",
        "aba total click share %",
    ),
    "aba_total_conv_share": (
        "aba total conv. share",
        "aba total conv share",
        "aba total conv. share %",
    ),
}

INT_FIELDS = {
    "cerebro_iq_score",
    "search_volume",
    "sponsored_asins",
    "competing_products",
    "cpr",
    "title_density",
    "amazon_recommended_rank",
    "sponsored_rank",
    "organic_rank",
    "keyword_sales",
}
FLOAT_FIELDS = {
    "search_volume_trend",
    "aba_total_click_share",
    "aba_total_conv_share",
}


def _norm_header(s: str) -> str:
    s = s.strip().lower()
    s = re.sub(r"\s+", " ", s)
    s = s.replace("ü", "ue").replace("ö", "oe").replace("ä", "ae").replace("ß", "ss")
    s = s.replace("é", "e").replace("è", "e").replace("ê", "e").replace("ç", "c")
    return s


def _build_header_map(headers: list[str]) -> dict[str, int]:
    """Map snapshot field name -> column index for known aliases."""
    by_norm = {_norm_header(h): i for i, h in enumerate(headers)}
    out: dict[str, int] = {}
    for field, aliases in HEADER_ALIASES.items():
        for alias in aliases:
            idx = by_norm.get(_norm_header(alias))
            if idx is not None:
                out[field] = idx
                break
    return out


_BLANK_TOKENS = {"", "-", "n/a", "na", "—", "null", "none"}


def _clean_cell(raw: Any) -> str | None:
    if raw is None:
        return None
    s = str(raw).strip()
    if s.lower() in _BLANK_TOKENS:
        return None
    return s


def _parse_int(raw: Any) -> int | None:
    s = _clean_cell(raw)
    if s is None:
        return None
    # Strip leading comparison operators Cerebro sometimes emits, e.g. ">300".
    s = s.lstrip("<>~ ").rstrip("%").strip()
    # Remove thousands separators (both , and . styles); we only keep digits/sign.
    s = s.replace(",", "").replace(" ", "")
    # Drop a fractional part if present (Cerebro is integer for these columns).
    if "." in s:
        s = s.split(".", 1)[0]
    try:
        return int(s)
    except ValueError:
        return None


def _parse_float(raw: Any) -> float | None:
    s = _clean_cell(raw)
    if s is None:
        return None
    s = s.lstrip("<>~ ").strip()
    pct = s.endswith("%")
    if pct:
        s = s[:-1].strip()
    # Heuristic for European decimals: "1.234,56" -> "1234.56".
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s and "." not in s:
        s = s.replace(",", ".")
    try:
        v = float(s)
    except ValueError:
        return None
    if pct:
        v /= 100.0
    return v


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _open_csv(path: Path):
    """Open the CSV with a sniffed dialect, falling back to defaults."""
    # utf-8-sig handles a BOM if Cerebro added one.
    f = path.open("r", encoding="utf-8-sig", newline="")
    sample = f.read(8192)
    f.seek(0)
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    return f, dialect


@dataclass
class ImportResult:
    import_run_id: int
    rows_inserted: int
    new_keywords: int


def import_cerebro_csv(
    conn: sqlite3.Connection,
    csv_path: str | Path,
    market: str,
    *,
    note: str | None = None,
) -> ImportResult:
    market = normalize_market(market)
    path = Path(csv_path).resolve()
    if not path.is_file():
        raise FileNotFoundError(path)

    file_hash = _file_sha256(path)

    # Reject re-imports of the same file for the same market.
    existing = conn.execute(
        "SELECT id FROM import_runs WHERE source = 'cerebro' AND market = ? AND file_hash = ?",
        (market, file_hash),
    ).fetchone()
    if existing:
        raise RuntimeError(
            f"This file (sha256 {file_hash[:12]}…) was already imported for "
            f"market {market} as run #{existing['id']}. Refusing duplicate."
        )

    f, dialect = _open_csv(path)
    try:
        reader = csv.reader(f, dialect)
        try:
            headers = next(reader)
        except StopIteration:
            raise RuntimeError(f"{path} is empty")

        header_map = _build_header_map(headers)
        if "phrase" not in header_map:
            raise RuntimeError(
                f"Could not find a 'Keyword Phrase' column in {path}. "
                f"Headers: {headers}"
            )

        with conn:  # single transaction
            cur = conn.execute(
                "INSERT INTO import_runs (source, market, file_path, file_hash, notes) "
                "VALUES ('cerebro', ?, ?, ?, ?)",
                (market, str(path), file_hash, note),
            )
            run_id = cur.lastrowid

            captured_at = conn.execute(
                "SELECT imported_at FROM import_runs WHERE id = ?", (run_id,)
            ).fetchone()["imported_at"]

            rows_inserted = 0
            new_keywords = 0
            seen_keyword_ids: set[int] = set()

            for row in reader:
                if not row or not any(cell.strip() for cell in row if cell):
                    continue
                phrase_idx = header_map["phrase"]
                if phrase_idx >= len(row):
                    continue
                phrase = (row[phrase_idx] or "").strip()
                if not phrase:
                    continue

                # Track new-vs-existing keyword count.
                pre = conn.execute(
                    "SELECT id FROM keywords WHERE phrase = ? COLLATE NOCASE",
                    (phrase,),
                ).fetchone()
                kw_id = ensure_keyword(conn, phrase)
                if pre is None:
                    new_keywords += 1

                ensure_tracking_row(conn, kw_id, market)

                # Extract typed fields.
                values: dict[str, Any] = {}
                for field, idx in header_map.items():
                    if field == "phrase":
                        continue
                    if idx >= len(row):
                        continue
                    raw = row[idx]
                    if field in INT_FIELDS:
                        values[field] = _parse_int(raw)
                    elif field in FLOAT_FIELDS:
                        values[field] = _parse_float(raw)
                    else:
                        values[field] = _clean_cell(raw)

                # Build extra_json from columns we didn't map.
                mapped_idxs = set(header_map.values())
                extras: dict[str, Any] = {}
                for i, h in enumerate(headers):
                    if i in mapped_idxs or i >= len(row):
                        continue
                    val = _clean_cell(row[i])
                    if val is not None:
                        extras[h] = val
                extra_json = json.dumps(extras, ensure_ascii=False) if extras else None

                # Skip if we already inserted this keyword for this run (Cerebro
                # files occasionally contain duplicate phrase rows).
                if kw_id in seen_keyword_ids:
                    continue
                seen_keyword_ids.add(kw_id)

                conn.execute(
                    """
                    INSERT INTO cerebro_snapshots (
                        import_run_id, keyword_id, market, captured_at,
                        cerebro_iq_score, search_volume, search_volume_trend,
                        sponsored_asins, competing_products, cpr, title_density,
                        amazon_recommended_rank, sponsored_rank, organic_rank,
                        keyword_sales, aba_total_click_share, aba_total_conv_share,
                        extra_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id, kw_id, market, captured_at,
                        values.get("cerebro_iq_score"),
                        values.get("search_volume"),
                        values.get("search_volume_trend"),
                        values.get("sponsored_asins"),
                        values.get("competing_products"),
                        values.get("cpr"),
                        values.get("title_density"),
                        values.get("amazon_recommended_rank"),
                        values.get("sponsored_rank"),
                        values.get("organic_rank"),
                        values.get("keyword_sales"),
                        values.get("aba_total_click_share"),
                        values.get("aba_total_conv_share"),
                        extra_json,
                    ),
                )
                rows_inserted += 1

            conn.execute(
                "UPDATE import_runs SET row_count = ? WHERE id = ?",
                (rows_inserted, run_id),
            )
    finally:
        f.close()

    return ImportResult(
        import_run_id=run_id,
        rows_inserted=rows_inserted,
        new_keywords=new_keywords,
    )
