#!/usr/bin/env python3
"""Build PTO coverage Slack DMs and a runner summary from coverage + metrics JSON.

Does the KPI delta maths deterministically, then writes one dm-<colleague>.md per
covering colleague plus summary.md.

Usage:
    python3 build_report.py --coverage coverage.json --metrics metrics.json \
        --out-dir ./out [--runner "Petra"] [--dates "Aug 30 - Sep 5"]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# Metric -> (label, kind, kpi field). kind drives direction and formatting.
METRICS = [
    ("sales", "Sales", "money", "sales_kpi", "floor"),
    ("spend", "Ad spend", "money", "spend_kpi", "ceiling"),
    ("acos", "ACOS", "percent", "acos_kpi", "ceiling"),
    ("tacos", "TACOS", "percent", "tacos_kpi", "ceiling"),
]

# Inside these bands, actual counts as on target rather than a miss.
MONEY_TOLERANCE = 0.02      # 2% of target
PERCENT_TOLERANCE = 0.01    # 1 percentage point, as a fraction

CURRENCY_SYMBOLS = {"USD": "$", "GBP": "£", "EUR": "€", "CAD": "C$", "AUD": "A$", "JPY": "¥"}


def money(value: float | None, currency: str | None) -> str:
    if value is None:
        return "unavailable"
    symbol = CURRENCY_SYMBOLS.get((currency or "").upper())
    body = f"{round(value):,}"
    return f"{symbol}{body}" if symbol else f"{body} {currency}".strip()


def pct(fraction: float | None, decimals: int = 1) -> str:
    if fraction is None:
        return "unavailable"
    return f"{fraction * 100:.{decimals}f}%"


def clean_pct(fraction: float | None) -> str:
    """Render a KPI target percent without a pointless trailing .0."""
    if fraction is None:
        return "unavailable"
    value = fraction * 100
    return f"{value:.0f}%" if abs(value - round(value)) < 0.05 else f"{value:.1f}%"


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "colleague"


def evaluate(actual, target, kind: str, direction: str) -> dict:
    """Compare one metric to its target. Units: money absolute, percent in points."""
    if actual is None:
        return {"status": "unavailable", "delta": None, "delta_pct": None}
    if target is None:
        return {"status": "no_kpi", "delta": None, "delta_pct": None}

    delta = actual - target

    if kind == "percent":
        # Percentage points, so "over by 35pts" is unambiguous.
        within = abs(delta) <= PERCENT_TOLERANCE
        delta_display = delta * 100
        delta_pct = None
    else:
        within = target != 0 and abs(delta) / abs(target) <= MONEY_TOLERANCE
        delta_display = delta
        delta_pct = (delta / target) if target else None

    if within:
        status = "at"
    elif direction == "floor":
        status = "on" if delta > 0 else "off"
    else:
        status = "on" if delta < 0 else "off"

    return {
        "status": status,
        "delta": delta,
        "delta_display": delta_display,
        "delta_pct": delta_pct,
    }


def describe(label: str, actual, target, kind: str, direction: str, verdict: dict,
             currency: str | None, kpi_meta: dict | None) -> str:
    """One bullet line for the DM."""
    if kind == "money":
        actual_str = money(actual, currency)
    else:
        actual_str = pct(actual)

    if verdict["status"] == "unavailable":
        return f"• {label}: unavailable"

    if verdict["status"] == "no_kpi":
        return f"• {label}: {actual_str} — no KPI set"

    if kind == "money":
        target_str = money(target, currency)
    else:
        target_str = clean_pct(target)

    qualifier = ""
    if kpi_meta:
        if kpi_meta.get("prorated"):
            qualifier = f" (prorated from {kpi_meta.get('period', 'monthly')})"
        elif kpi_meta.get("period") and kind == "money":
            qualifier = f" ({kpi_meta['period']})"

    if verdict["status"] == "at":
        gap = "on target"
    elif kind == "percent":
        points = abs(verdict["delta_display"])
        gap = f"{points:.1f}pts {'over' if verdict['delta'] > 0 else 'under'}"
    else:
        if verdict["delta_pct"] is None:
            gap = f"{money(abs(verdict['delta']), currency)} {'over' if verdict['delta'] > 0 else 'under'}"
        else:
            gap = f"{abs(verdict['delta_pct']) * 100:.0f}% {'over' if verdict['delta'] > 0 else 'under'}"

    return f"• {label}: {actual_str} — KPI {target_str}{qualifier} — {gap}"


def budget_line(brand_metrics: dict, kpis: dict) -> str:
    value = brand_metrics.get("daily_budget")
    currency = brand_metrics.get("currency")
    if value is None:
        return "• Daily budget: unavailable"

    count = brand_metrics.get("daily_budget_campaigns")
    line = f"• Daily budget: {money(value, currency)}"
    if count:
        line += f" across {count} enabled campaign{'s' if count != 1 else ''}"

    missing = brand_metrics.get("campaigns_without_daily_budget") or 0
    if missing:
        line += f" ({missing} campaign{'s' if missing != 1 else ''} without a daily budget)"

    kpi = kpis.get("daily_budget_kpi")
    if kpi and kpi.get("target") is not None:
        verdict = evaluate(value, kpi["target"], "money", "ceiling")
        target_str = money(kpi["target"], currency)
        if verdict["status"] == "at":
            line += f" — KPI {target_str} — on target"
        elif verdict["delta_pct"] is not None:
            direction = "over" if verdict["delta"] > 0 else "under"
            line += f" — KPI {target_str} — {abs(verdict['delta_pct']) * 100:.0f}% {direction}"
    return line


def build_brand_block(brand: str, entry: dict, brand_metrics: dict | None) -> tuple[list[str], list[str]]:
    """Return (lines, off_track_metric_labels) for one brand. Labels are bare metric names."""
    lines = [f"*{brand}*"]
    off_track: list[str] = []

    if brand_metrics is None:
        lines.append("• No data pulled for this brand — check the brand name against the store list.")
        return lines, off_track

    reason = (brand_metrics.get("unavailable_reason") or "").strip()
    has_any_figure = any(
        brand_metrics.get(key) is not None for key, *_ in METRICS
    ) or brand_metrics.get("by_currency")

    if reason and not has_any_figure:
        # A stated reason plus four "unavailable" lines is noise — the reason is the message.
        lines.append(f"• No figures for this one: {reason}")
        notes = (entry.get("notes") or "").strip()
        if notes:
            lines.append(f"• Note: {notes}")
        return lines, off_track
    if reason:
        lines.append(f"• Partial data: {reason}")

    kpis = entry.get("kpis") or {}
    currency = brand_metrics.get("currency")
    by_currency = brand_metrics.get("by_currency")

    if by_currency:
        lines.append(
            "• This store spent in more than one currency, so the figures are split and "
            "money is not compared to KPI:"
        )
        for row in by_currency:
            cur = row.get("currency")
            lines.append(
                f"   – {cur}: sales {money(row.get('sales'), cur)}, "
                f"spend {money(row.get('spend'), cur)}, "
                f"ACOS {pct(row.get('acos'))}, TACOS {pct(row.get('tacos'))}"
            )
        for key, label, kind, kpi_field, direction in METRICS:
            if kind != "percent":
                continue
            actual = brand_metrics.get(key)
            kpi = kpis.get(kpi_field) or {}
            target = kpi.get("target")
            verdict = evaluate(actual, target, kind, direction)
            if actual is not None:
                lines.append(describe(label, actual, target, kind, direction, verdict, currency, kpi))
            if verdict["status"] == "off":
                off_track.append(label)
    else:
        for key, label, kind, kpi_field, direction in METRICS:
            actual = brand_metrics.get(key)
            kpi = kpis.get(kpi_field) or {}
            target = kpi.get("target")
            verdict = evaluate(actual, target, kind, direction)
            lines.append(describe(label, actual, target, kind, direction, verdict, currency, kpi))
            if verdict["status"] == "off":
                off_track.append(label)

    lines.append(budget_line(brand_metrics, kpis))

    notes = (entry.get("notes") or "").strip()
    if notes:
        lines.append(f"• Note: {notes}")

    return lines, off_track


def build_dm(colleague: str, entries: list[dict], metrics: dict, runner: str | None,
             dates: str | None, window: dict) -> str:
    brand_count = len(entries)
    plural = "s" if brand_count != 1 else ""

    opener = f"Hey {colleague} — "
    opener += f"{runner} here. You're" if runner else "you're"
    opener += f" covering {brand_count} of my brand{plural} while I'm out"
    opener += f" {dates}." if dates else "."
    if not runner:
        # No runner name, so the sentence starts at "you're" and needs its own capital.
        head = f"Hey {colleague} — "
        tail = opener[len(head):]
        opener = head + tail[:1].upper() + tail[1:]

    start, end = window.get("start"), window.get("end")
    window_str = f" ({start} – {end})" if start and end else ""
    opener += f" Here's where each one stands over the last 7 days{window_str}, against KPI."

    lines = [opener, ""]
    watch: list[str] = []

    for entry in sorted(entries, key=lambda e: e["brand"].lower()):
        brand = entry["brand"]
        block, off_track = build_brand_block(brand, entry, metrics.get("brands", {}).get(brand))
        lines.extend(block)
        lines.append("")
        if off_track:
            # Group per brand: "Hush & Hush (ACOS, TACOS)" beats repeating the brand name.
            watch.append(f"{brand} ({', '.join(off_track)})")

    if watch:
        lines.append(f"What I'd watch: {'; '.join(watch)}.")
    else:
        lines.append("Everything's tracking to KPI right now.")

    lines.append("Ping me only if something breaks — otherwise it's all yours. Thanks for covering 🙏")
    return "\n".join(lines).strip() + "\n"


def build_summary(coverage: dict, metrics: dict, window: dict) -> str:
    lines = ["# PTO coverage summary", ""]
    start, end = window.get("start"), window.get("end")
    if start and end:
        lines.append(f"Window: last 7 days ({start} – {end}). Recent days may still be settling.")
        lines.append("")

    header = (
        "| Brand | Covering | Sales | vs KPI | Spend | vs KPI | ACOS | vs KPI "
        "| TACOS | vs KPI | Daily budget |"
    )
    lines.append(header)
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|")

    attention: list[str] = []

    for entry in sorted(coverage["entries"], key=lambda e: e["brand"].lower()):
        brand = entry["brand"]
        colleague = entry.get("colleague") or "**unassigned**"
        bm = metrics.get("brands", {}).get(brand)
        kpis = entry.get("kpis") or {}

        if bm is None:
            lines.append(f"| {brand} | {colleague} | " + " | ".join(["—"] * 9) + " |")
            attention.append(f"{brand}: no data pulled — check the brand name against the store list.")
            continue

        currency = bm.get("currency")
        cells: list[str] = []
        for key, label, kind, kpi_field, direction in METRICS:
            actual = bm.get(key)
            target = (kpis.get(kpi_field) or {}).get("target")
            verdict = evaluate(actual, target, kind, direction)
            cells.append(money(actual, currency) if kind == "money" else pct(actual))

            if verdict["status"] == "no_kpi":
                cells.append("no KPI")
            elif verdict["status"] == "unavailable":
                cells.append("—")
            elif verdict["status"] == "at":
                cells.append("on target")
            elif kind == "percent":
                sign = "+" if verdict["delta"] > 0 else "−"
                cells.append(f"{sign}{abs(verdict['delta_display']):.1f}pts")
            elif verdict["delta_pct"] is not None:
                sign = "+" if verdict["delta"] > 0 else "−"
                cells.append(f"{sign}{abs(verdict['delta_pct']) * 100:.0f}%")
            else:
                cells.append("—")

            if verdict["status"] == "off":
                attention.append(f"{brand}: {label} off KPI ({cells[-1]}), covered by {colleague}.")

        cells.append(money(bm.get("daily_budget"), currency) if bm.get("daily_budget") is not None else "unavailable")
        lines.append(f"| {brand} | {colleague} | " + " | ".join(cells) + " |")

        if bm.get("by_currency"):
            attention.append(f"{brand}: multi-currency store — money reported per currency, not compared to KPI.")
        reason = bm.get("unavailable_reason")
        has_figures = any(bm.get(key) is not None for key, *_ in METRICS) or bm.get("by_currency")
        if reason and not has_figures:
            # The reason covers the budget gap too — don't list both.
            attention.append(f"{brand}: no figures — {reason}")
        else:
            if reason:
                attention.append(f"{brand}: partial data — {reason}")
            if bm.get("daily_budget") is None:
                attention.append(f"{brand}: daily budget unavailable.")
        if not kpis:
            attention.append(f"{brand}: no KPI in the coverage file — reported actual-only.")

    lines.append("")

    if attention:
        lines.append("## Needs your attention before you go")
        lines.append("")
        for item in dict.fromkeys(attention):
            lines.append(f"- {item}")
        lines.append("")

    warnings = coverage.get("warnings") or []
    if warnings:
        lines.append("## Coverage file warnings")
        lines.append("")
        for w in warnings:
            lines.append(f"- [{w['type']}] {w['detail']}")
        lines.append("")

    lines.append("## Before you go")
    lines.append("")
    lines.append(
        "- More than 4 working days off: tell your Squad lead at least 2 weeks ahead, introduce "
        "your buddy to the accounts 2 weeks ahead, and file a \"Days Off\" ticket via Suptask in "
        "Slack with the dates, buddy name and accounts covered. This skill does not file that ticket."
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description="Build PTO coverage DMs and summary.")
    ap.add_argument("--coverage", type=Path, required=True, help="coverage.json from parse_coverage.py")
    ap.add_argument("--metrics", type=Path, required=True, help="metrics.json (see references/metrics.md)")
    ap.add_argument("--out-dir", type=Path, required=True, help="Directory for the generated files")
    ap.add_argument("--runner", help="Name of the person going on PTO, used in the DM opener")
    ap.add_argument("--dates", help="PTO dates, e.g. 'Aug 30 - Sep 5'. Omitted = no dates line")
    args = ap.parse_args()

    for path in (args.coverage, args.metrics):
        if not path.exists():
            sys.exit(f"No such file: {path}")

    coverage = json.loads(args.coverage.read_text(encoding="utf-8"))
    metrics = json.loads(args.metrics.read_text(encoding="utf-8"))
    window = metrics.get("window") or {}

    args.out_dir.mkdir(parents=True, exist_ok=True)

    by_colleague: dict[str, list[dict]] = {}
    for entry in coverage["entries"]:
        if entry.get("colleague"):
            by_colleague.setdefault(entry["colleague"], []).append(entry)

    written: list[Path] = []
    for colleague, entries in sorted(by_colleague.items()):
        dm = build_dm(colleague, entries, metrics, args.runner, args.dates, window)
        out = args.out_dir / f"dm-{slugify(colleague)}.md"
        out.write_text(dm, encoding="utf-8")
        written.append(out)
        flag = "  ⚠ over 3500 chars — split into one message per brand" if len(dm) > 3500 else ""
        print(f"  {out}  ({len(entries)} brand(s), {len(dm)} chars){flag}")

    summary_path = args.out_dir / "summary.md"
    summary_path.write_text(build_summary(coverage, metrics, window), encoding="utf-8")
    written.append(summary_path)
    print(f"  {summary_path}")

    unassigned = [e["brand"] for e in coverage["entries"] if not e.get("colleague")]
    if unassigned:
        print(f"\n  Unassigned brands (in no DM): {', '.join(sorted(set(unassigned)))}")

    missing = [b for b in coverage["brands"] if b not in metrics.get("brands", {})]
    if missing:
        print(f"  No metrics for: {', '.join(sorted(missing))}")

    print(f"\nWrote {len(written)} file(s) to {args.out_dir}")


if __name__ == "__main__":
    main()
