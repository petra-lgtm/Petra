#!/usr/bin/env python3
"""Parse a PTO coverage file into normalised JSON.

Reads .xlsx/.xlsm/.csv/.tsv, maps header aliases, normalises percent and money
values, prorates period-based targets to a 7-day window, and explodes rows that
name several covering colleagues.

Usage:
    python3 parse_coverage.py <coverage-file> [--out coverage.json] [--window-days 7]
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

DAYS_PER_MONTH = 30.44

FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "brand": (
        "brand", "brandname", "account", "accountname", "client", "clientname",
        "store", "storename",
    ),
    "colleague": (
        "colleague", "covering", "coveringcolleague", "cover", "buddy", "owner",
        "assignedto", "assignee", "coveredby", "podleader", "whocovers",
    ),
    "sales_kpi": (
        "saleskpi", "salestarget", "targetsales", "revenuekpi", "revenuetarget",
        "salesgoal",
    ),
    "sales_kpi_period": ("salesperiod", "kpiperiod", "period", "saleskpiperiod"),
    "spend_kpi": (
        "spendkpi", "spendtarget", "targetspend", "adspendkpi", "adspendtarget",
        "spendcap",
    ),
    "spend_kpi_period": ("spendperiod", "spendkpiperiod"),
    "acos_kpi": ("acoskpi", "acostarget", "targetacos", "acos", "acosgoal", "acos%"),
    "tacos_kpi": ("tacoskpi", "tacostarget", "targettacos", "tacos", "tacosgoal", "tacos%"),
    "daily_budget_kpi": (
        "dailybudget", "dailybudgetkpi", "budget", "dailybudgettarget", "budgetcap",
    ),
    "notes": ("notes", "note", "comment", "comments", "context", "flag", "flags"),
}

MONEY_FIELDS = ("sales_kpi", "spend_kpi", "daily_budget_kpi")
PERCENT_FIELDS = ("acos_kpi", "tacos_kpi")
VALID_PERIODS = ("daily", "weekly", "monthly")

# Split a colleague cell holding several names. Order matters: " and " before "&".
NAME_SPLIT = re.compile(r"\s+and\s+|[,/&+;]", re.IGNORECASE)


def norm_header(raw: str) -> str:
    """Lowercase and strip everything but alphanumerics and a trailing percent."""
    s = str(raw or "").strip().lower()
    s = re.sub(r"[^a-z0-9%]", "", s)
    return s


def map_headers(headers: list[str]) -> tuple[dict[int, str], list[str]]:
    """Map column index -> canonical field. Returns (mapping, unmapped headers)."""
    lookup = {alias: field for field, aliases in FIELD_ALIASES.items() for alias in aliases}
    mapping: dict[int, str] = {}
    unmapped: list[str] = []
    for idx, raw in enumerate(headers):
        key = norm_header(raw)
        if not key:
            continue
        field = lookup.get(key)
        if field is None:
            unmapped.append(str(raw).strip())
        elif field not in mapping.values():
            mapping[idx] = field
        # A duplicate mapping to an already-claimed field: first column wins.
    return mapping, unmapped


def parse_money(raw) -> float | None:
    """'$12,500' -> 12500.0. Returns None when not a number."""
    if raw is None:
        return None
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return float(raw)
    s = str(raw).strip()
    if not s:
        return None
    s = re.sub(r"[^\d.\-]", "", s)
    if s in ("", "-", ".", "-."):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def parse_percent(raw) -> tuple[float | None, bool]:
    """Return (fraction, ambiguous). '25%'/25 -> 0.25; 0.25 -> 0.25; 1 -> 1.0 + flag."""
    if raw is None:
        return None, False
    explicit = "%" in str(raw)
    value = parse_money(raw)
    if value is None:
        return None, False
    if explicit:
        return value / 100.0, False
    if value > 1:
        return value / 100.0, False
    if value == 1:
        # Could be 1% or 100%. 100% is the only plausible target, so take it and flag.
        return 1.0, True
    return value, False


def parse_period(raw, default: str = "weekly") -> str:
    s = str(raw or "").strip().lower()
    for period in VALID_PERIODS:
        if s.startswith(period[:3]):
            return period
    if s in ("wk", "w", "week"):
        return "weekly"
    if s in ("mo", "m", "month", "mth"):
        return "monthly"
    if s in ("d", "day"):
        return "daily"
    return default


def prorate(value: float, period: str, window_days: int) -> tuple[float, bool]:
    """Scale a period target onto the window. Returns (scaled, was_prorated)."""
    if period == "weekly":
        # A weekly target maps 1:1 onto a 7-day window; anything else is scaled.
        if window_days == 7:
            return value, False
        return value * window_days / 7.0, True
    if period == "monthly":
        return value * window_days / DAYS_PER_MONTH, True
    if period == "daily":
        return value * window_days, True
    return value, False


def read_rows(path: Path) -> list[list]:
    """Return the sheet as a list of rows (list of cells). First row is the header."""
    suffix = path.suffix.lower()
    if suffix in (".csv", ".tsv", ".txt"):
        with path.open(newline="", encoding="utf-8-sig") as fh:
            sample = fh.read(8192)
            fh.seek(0)
            try:
                dialect = csv.Sniffer().sniff(sample, delimiters=",\t;")
            except csv.Error:
                dialect = csv.excel_tab if suffix == ".tsv" else csv.excel
            return [list(row) for row in csv.reader(fh, dialect)]
    if suffix in (".xlsx", ".xlsm"):
        try:
            from openpyxl import load_workbook
        except ImportError:
            sys.exit(
                "openpyxl is needed to read .xlsx/.xlsm files.\n"
                "  pip install openpyxl\n"
                "Or re-save the coverage file as .csv and pass that instead."
            )
        wb = load_workbook(path, data_only=True, read_only=True)
        ws = wb.active
        rows = [list(r) for r in ws.iter_rows(values_only=True)]
        wb.close()
        return rows
    sys.exit(f"Unsupported file type: {suffix}. Use .xlsx, .xlsm, .csv or .tsv.")


def find_header_row(rows: list[list]) -> int:
    """Index of the first row that maps at least a brand and a colleague column."""
    for idx, row in enumerate(rows[:20]):
        mapping, _ = map_headers([c if c is not None else "" for c in row])
        fields = set(mapping.values())
        if "brand" in fields and "colleague" in fields:
            return idx
    for idx, row in enumerate(rows[:20]):
        mapping, _ = map_headers([c if c is not None else "" for c in row])
        if "brand" in set(mapping.values()):
            return idx
    sys.exit(
        "Couldn't find a header row with a brand column in the first 20 rows.\n"
        "The file needs at least a brand column and a covering-colleague column — "
        "see references/coverage-file.md, or start from assets/coverage-template.csv."
    )


def cell(row: list, idx: int):
    return row[idx] if idx < len(row) else None


def parse(path: Path, window_days: int) -> dict:
    rows = read_rows(path)
    if not rows:
        sys.exit(f"{path} is empty.")

    header_idx = find_header_row(rows)
    headers = [c if c is not None else "" for c in rows[header_idx]]
    mapping, unmapped = map_headers(headers)
    col = {field: idx for idx, field in mapping.items()}

    warnings: list[dict] = []
    for header in unmapped:
        warnings.append({
            "type": "unknown_column",
            "detail": f"Column {header!r} wasn't recognised and is being ignored.",
        })
    if "colleague" not in col:
        warnings.append({
            "type": "missing_colleague",
            "detail": "No covering-colleague column found — no brand can be assigned.",
        })

    entries: list[dict] = []
    seen: set[tuple[str, str]] = set()

    for offset, row in enumerate(rows[header_idx + 1:], start=header_idx + 2):
        brand = str(cell(row, col["brand"]) or "").strip() if "brand" in col else ""
        if not brand or brand.startswith("#"):
            continue

        kpis: dict[str, dict] = {}

        sales_period = parse_period(
            cell(row, col["sales_kpi_period"]) if "sales_kpi_period" in col else None
        )
        spend_period = parse_period(
            cell(row, col["spend_kpi_period"]) if "spend_kpi_period" in col else None,
            default=sales_period,
        )
        periods = {"sales_kpi": sales_period, "spend_kpi": spend_period}

        for field in MONEY_FIELDS:
            if field not in col:
                continue
            raw = cell(row, col[field])
            if raw is None or str(raw).strip() == "":
                continue
            value = parse_money(raw)
            if value is None:
                warnings.append({
                    "type": "unparseable_number",
                    "detail": f"Row {offset} ({brand}): {field} value {raw!r} isn't a number — dropped.",
                })
                continue
            if field == "daily_budget_kpi":
                # A daily budget is already a per-day figure; the window never scales it.
                kpis[field] = {"target": value, "period": "daily", "prorated": False}
            else:
                scaled, was_prorated = prorate(value, periods[field], window_days)
                kpis[field] = {
                    "target": round(scaled, 2),
                    "target_raw": value,
                    "period": periods[field],
                    "prorated": was_prorated,
                }

        for field in PERCENT_FIELDS:
            if field not in col:
                continue
            raw = cell(row, col[field])
            if raw is None or str(raw).strip() == "":
                continue
            fraction, ambiguous = parse_percent(raw)
            if fraction is None:
                warnings.append({
                    "type": "unparseable_number",
                    "detail": f"Row {offset} ({brand}): {field} value {raw!r} isn't a number — dropped.",
                })
                continue
            if ambiguous:
                warnings.append({
                    "type": "ambiguous_percent",
                    "detail": (
                        f"Row {offset} ({brand}): {field} of 1 read as 100%. "
                        "Write 1% or 0.01 if that's what you meant."
                    ),
                })
            kpis[field] = {"target": fraction, "prorated": False}

        notes = str(cell(row, col["notes"]) or "").strip() if "notes" in col else ""

        raw_colleagues = str(cell(row, col["colleague"]) or "").strip() if "colleague" in col else ""
        names = [n.strip() for n in NAME_SPLIT.split(raw_colleagues) if n.strip()]

        if not names:
            warnings.append({
                "type": "missing_colleague",
                "detail": f"Row {offset}: {brand} has no covering colleague — it won't appear in any DM.",
            })
            entries.append({
                "brand": brand, "colleague": None, "kpis": kpis, "notes": notes, "row": offset,
            })
            continue

        if not kpis:
            warnings.append({
                "type": "no_kpis",
                "detail": f"Row {offset}: {brand} has no KPI — metrics will report actual-only.",
            })

        for name in names:
            key = (brand.lower(), name.lower())
            if key in seen:
                warnings.append({
                    "type": "duplicate_brand",
                    "detail": f"Row {offset}: {brand} / {name} appears more than once — first row kept.",
                })
                continue
            seen.add(key)
            entries.append({
                "brand": brand, "colleague": name, "kpis": kpis, "notes": notes, "row": offset,
            })

    assigned = [e for e in entries if e["colleague"]]
    colleagues: dict[str, list[str]] = {}
    for entry in assigned:
        colleagues.setdefault(entry["colleague"], []).append(entry["brand"])

    return {
        "source_file": str(path),
        "window_days": window_days,
        "entries": entries,
        "colleagues": colleagues,
        "brands": sorted({e["brand"] for e in entries}),
        "warnings": warnings,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Parse a PTO coverage file into normalised JSON.")
    ap.add_argument("file", type=Path, help="Coverage file (.xlsx/.xlsm/.csv/.tsv)")
    ap.add_argument("--out", type=Path, default=Path("coverage.json"), help="Output JSON path")
    ap.add_argument("--window-days", type=int, default=7, help="Reporting window (default 7)")
    args = ap.parse_args()

    if not args.file.exists():
        sys.exit(f"No such file: {args.file}")
    if args.window_days < 1:
        sys.exit("--window-days must be at least 1.")

    result = parse(args.file, args.window_days)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2), encoding="utf-8")

    print(f"Parsed {args.file}")
    print(f"  {len(result['brands'])} brands, {len(result['colleagues'])} colleagues")
    for name, brands in sorted(result["colleagues"].items()):
        print(f"    {name}: {', '.join(sorted(brands))}")
    unassigned = [e["brand"] for e in result["entries"] if not e["colleague"]]
    if unassigned:
        print(f"  unassigned: {', '.join(sorted(set(unassigned)))}")
    if result["warnings"]:
        print(f"\n  {len(result['warnings'])} warning(s) — resolve before sending:")
        for w in result["warnings"]:
            print(f"    [{w['type']}] {w['detail']}")
    print(f"\nWrote {args.out}")


if __name__ == "__main__":
    main()
