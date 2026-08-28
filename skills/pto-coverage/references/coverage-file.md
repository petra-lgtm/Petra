# The coverage file

One row per **brand**. The file says who covers that brand and what its KPIs are.
`scripts/parse_coverage.py` reads `.xlsx`, `.xlsm`, `.csv` and `.tsv`.

## Columns

Only two are required: the brand and the colleague covering it. Everything else is optional —
a missing KPI means that metric reports actual-only, with no delta.

| Field | Required | Meaning |
|---|---|---|
| `brand` | **yes** | Brand / store name, matched against `list_stores` |
| `colleague` | **yes** | Who covers this brand. One name per row |
| `sales_kpi` | no | Target sales for the period in `sales_kpi_period` |
| `sales_kpi_period` | no | `weekly` (default), `monthly`, or `daily` |
| `spend_kpi` | no | Ad-spend **ceiling** for the same period basis |
| `spend_kpi_period` | no | Defaults to `sales_kpi_period`, else `weekly` |
| `acos_kpi` | no | Target ACOS, a ceiling |
| `tacos_kpi` | no | Target TACOS, a ceiling |
| `daily_budget_kpi` | no | Expected total daily ad budget, a ceiling |
| `notes` | no | Free text, passed straight through to that brand's DM row |

## Header aliases

Headers are matched case-insensitively after stripping non-alphanumerics, so
`ACOS KPI`, `acos_kpi`, `Target ACOS` and `ACOS%` all land on `acos_kpi`.

- `brand` ← brand, brand name, account, account name, client, client name, store, store name
- `colleague` ← colleague, covering, covering colleague, cover, buddy, owner, assigned to,
  assignee, covered by, pod leader, who covers
- `sales_kpi` ← sales kpi, sales target, target sales, revenue kpi, revenue target, sales goal
- `sales_kpi_period` ← sales period, kpi period, period, sales kpi period
- `spend_kpi` ← spend kpi, spend target, target spend, ad spend kpi, ad spend target, spend cap
- `spend_kpi_period` ← spend period, spend kpi period
- `acos_kpi` ← acos kpi, acos target, target acos, acos, acos goal, acos%
- `tacos_kpi` ← tacos kpi, tacos target, target tacos, tacos, tacos goal, tacos%
- `daily_budget_kpi` ← daily budget, daily budget kpi, budget, daily budget target, budget cap
- `notes` ← notes, note, comment, comments, context, flag, flags

## Normalisation the parser applies

**Percent metrics (`acos_kpi`, `tacos_kpi`).** Stored internally as fractions.
A bare number `> 1` is read as a percentage (`25` → `0.25`); a number `<= 1` is read as an
already-fractional value (`0.25` → `0.25`); an explicit `%` always means percent
(`25%` → `0.25`). The ambiguous case is exactly `1` — read as `1.0` (100%) with a warning,
because a 1% ACOS target is not a real target.

**Money.** Currency symbols, thousands separators and spaces are stripped: `$12,500` → `12500.0`.
The file's currency is **not** interpreted — a brand's currency comes from the store's own data
in Step 4. If a store reports in a currency the runner clearly didn't have in mind, flag it
rather than converting.

**Periods.** A `monthly` target is prorated to the 7-day window by `× 7 / 30.44`; a `daily`
target by `× 7`. `weekly` is used as-is. Prorated targets are marked `prorated: true` and the DM
labels them "(prorated from monthly)" — the comparison is an approximation, so say so.

**Multiple colleagues on one brand.** A `colleague` cell holding several names separated by
`,`, `/`, `&`, `+` or ` and ` becomes one row per colleague, all sharing the brand's KPIs. Each
of them gets the brand in their own DM.

**Blank and comment rows.** Rows with no brand, or a brand starting `#`, are skipped.

## Warnings the parser raises

Resolve each of these with the runner before sending anything:

- `unknown_column` — a header it couldn't map. Named so the runner can rename or confirm it's
  intentionally ignored.
- `missing_colleague` — a brand with KPIs but nobody covering it. It will not appear in any DM.
- `no_kpis` — a brand with a colleague but no KPI at all. Reports actual-only.
- `ambiguous_percent` — an `acos_kpi` / `tacos_kpi` of exactly `1`.
- `duplicate_brand` — the same brand twice for the same colleague. Deduplicated, first row wins.
- `unparseable_number` — a KPI cell that isn't a number. Dropped, and the brand keeps its
  other KPIs.
