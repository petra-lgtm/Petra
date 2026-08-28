# Metrics: where each number comes from

## The four headline metrics — one call per store

```
get_account_performance_summary(store: <seller_id>, days: 7)
```

Field mapping, from a verified response:

| Reported as | Path in the response | Note |
|---|---|---|
| Sales | `data.derived.total_revenue` | **Total** revenue (organic + ad-driven), not `ads.sales` |
| Ad spend | `data.derived.ad_spend` | |
| ACOS | `data.derived.acos` | **Fraction** — `0.6996` = 69.96% |
| TACOS | `data.derived.tacos` | **Fraction** — `0.2786` = 27.86% |
| Currency | `data.derived.currency` | |
| Window | `data.window.start` / `data.window.end` | Quote these; don't assume today−7 |
| Ad sales | `data.derived.ad_sales` | Optional context in the DM |
| Organic share | `data.derived.organic_share` | Fraction. Optional context |

Definitions the tool uses, worth restating in the DM footnote so nobody re-derives them wrong:
ACOS = ad spend ÷ ad sales. TACOS = ad spend ÷ total revenue.

### Multi-currency stores

When a store's ad profiles spent in more than one currency, **every money field comes back
`null`** and the real figures sit in `data.ads.by_currency[]`. Read those and report each
currency on its own line. Never sum, average or convert across currencies — and never report
`null` as zero or as "no data" when `by_currency` is populated.

To force a single-currency answer for one marketplace, add
`marketplace_id: "ATVPDKIKX0DER"` (or the relevant one) to the call.

### When a store has no ads profiles

`get_account_performance_summary` **errors outright** — `No ads profiles registered for store
"<id>"` — rather than returning zeros. Verified against a real store. Catch it: record the brand
with all metrics `null` plus

```json
"unavailable_reason": "no ads profiles registered for this store, so ads and TACOS can't be pulled"
```

`build_report.py` then prints the reason instead of four "unavailable" lines. Never report the
brand as zero sales, and never drop it silently — the colleague still needs to know it's theirs.

### Freshness

Sales & Traffic for the most recent day or two can still be settling. Always label the window
`last 7 days (<start> – <end>)` and never present the figure as final or reconciled.

## Daily budgets

`list_ad_campaigns` is **structure only** — name, ad type, state, portfolio, `profile_id`,
`marketplace_id`. It carries no budget. Budgets are live campaign state and need the Amazon Ads
campaign-management read.

### Procedure

1. `list_ad_campaigns(store: <seller_id>, state: "ENABLED")`.
   Collect `campaign_id`, `ad_type` and `profile_id`. Group the IDs by `(profile_id, ad_type)`.

2. For each group, in batches of **20 campaign IDs** (see the batch-size note below):

```
sophie_call_amazon_ads_mcp(
  profile_id: "<profile_id>",
  tool_name: "campaign_management-query_campaign",
  arguments: {
    "body": {
      "accessRequestedAccount": { "advertiserAccountId": "<profile_id>" },
      "adProductFilter": { "include": ["SPONSORED_PRODUCTS"] },
      "campaignIdFilter": { "include": ["<id>", "<id>", ...] },
      "maxResults": 20
    }
  }
)
```

- `accessRequestedAccount` is **required** even on reads — the call is rejected without it.
  Using the `profile_id` as `advertiserAccountId` is the working default (verified). If a store
  rejects it, read the real `advertiserAccountId` off any campaign object this tool returns for
  that profile, or from `ads_accounts-list_ads_accounts`, and retry.
- `adProductFilter.include` takes **exactly one** ad product (`maxItems: 1`). One query per ad
  type: `SPONSORED_PRODUCTS`, `SPONSORED_BRANDS`, `SPONSORED_DISPLAY`.
- A `nextToken` in the response means more results — pass it back to continue.

**Batch size matters.** Each campaign object comes back at roughly 1,000 characters — full
budget, placement adjustments, bid strategy, delivery status. A verified 56-campaign query
returned every campaign in one page (no `nextToken`) but the response **exceeded the tool
output cap** and had to be spilled to a file. So cap batches at **20 IDs**, and sum as you go
rather than holding every response in context. A store with 56 enabled campaigns is 3 calls,
not 1.

3. Per campaign, read the DAILY monetary budget:

```
budgets[] where recurrenceTimePeriod == "DAILY" and budgetType == "MONETARY"
  → budgetValue.monetaryBudgetValue.monetaryBudget.value
    budgetValue.monetaryBudgetValue.monetaryBudget.currencyCode
```

Verified shape:

```json
{"budgets":[{"budgetType":"MONETARY","recurrenceTimePeriod":"DAILY",
  "budgetValue":{"monetaryBudgetValue":{"monetaryBudget":{"currencyCode":"USD","value":15.0}}}}]}
```

4. Report **the sum of DAILY budgets over ENABLED campaigns, per currency**, plus the campaign
count behind the sum. Verified example: Hush & Hush's 56 enabled SP campaigns summed to
**$1,474.00/day**, with none lacking a daily budget. A campaign with no DAILY budget row (e.g. lifetime-budget only) is
excluded from the sum and counted separately as `campaigns_without_daily_budget`.

### Read-only, and never blocking

Use only `query_*` tools here. **Never** call `campaign_management-update_campaign_budget` or any
`create_*` / `update_*` / `delete_*` tool — a coverage handoff never changes an account.

If the budget read fails, is unauthorised, or the store has no enabled campaigns, record
`"daily_budget": null` and continue. The DM says "Daily budget: unavailable". A budget gap never
blocks the handoff.

## KPI delta maths

`scripts/build_report.py` does this deterministically. Documented here so the output can be
checked.

**Direction.** Sales is a floor — higher is better. Spend, ACOS, TACOS and daily budget are all
ceilings — lower is better.

**Delta.** Always `actual − target`, in the metric's own units, so the sign is stable:

- Sales / spend / budget: an absolute money delta, plus `delta_pct = (actual − target) / target`.
- ACOS / TACOS: a **percentage-point** delta (`actual_pct − target_pct`), because a "10% higher
  ACOS" is ambiguous and points are not.

**On/off track.** A floor metric is on track when `actual >= target`; a ceiling metric when
`actual <= target`. Within ±2% of target (±1 percentage point for ACOS/TACOS) is reported as
`at` — on target — rather than a hair over or under, so a rounding artefact doesn't read as a
miss.

**No target** → `delta: null`, `status: "no_kpi"`, actual reported alone. Never substitute a
default target, a house benchmark, or last period's figure.

**Prorated targets** carry `prorated: true`; label them "(prorated from monthly)" wherever the
delta appears.

## metrics.json contract

Write this file from the MCP results before running `build_report.py`. One object per brand,
keyed by the brand string **exactly as it appears in the coverage file** — that is the join key.

```json
{
  "window": { "start": "2026-08-22", "end": "2026-08-28" },
  "brands": {
    "Hush & Hush": {
      "store": "A3VF2IR7U3KD86",
      "store_name": "Hush & Hush",
      "currency": "USD",
      "sales": 3359.29,
      "spend": 935.9,
      "acos": 0.6996,
      "tacos": 0.2786,
      "ad_sales": 1337.73,
      "organic_share": 0.6018,
      "daily_budget": 412.5,
      "daily_budget_campaigns": 56,
      "campaigns_without_daily_budget": 0,
      "window": { "start": "2026-08-22", "end": "2026-08-28" }
    }
  }
}
```

- `acos` / `tacos` stay **fractions** — the script converts for display.
- Any unavailable metric is `null`, never `0`.
- Per-brand `window` is optional; it overrides the top-level one when a store's window differs.
- A multi-currency store instead carries
  `"by_currency": [{ "currency": "GBP", "sales": …, "spend": …, "acos": …, "tacos": … }, …]`
  with the scalar money fields left `null`. The script reports each currency on its own line
  and skips money deltas for that brand.
