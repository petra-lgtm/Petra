---
name: pto-coverage
description: >
  PTO coverage handoff for Sophie Society pod leaders. Asks who is covering and for the
  coverage file (which colleague covers which brand, plus each brand's KPIs), then pulls the
  last 7 days of sales, ad spend, ACOS and TACOS per brand from Sophie Hub, compares each metric
  to its KPI, reads the live total daily ad budget, and DMs each colleague a Slack handoff with
  only their own brands. Use whenever the user says anything like "PTO coverage", "PTO handoff",
  "I'm going on PTO", "going on vacation / leave / holiday", "buddy handoff", "brief my buddy",
  "who's covering my brands", "hand over my accounts", "cover my accounts while I'm away",
  "send the coverage message", "coverage brief", "OOO handoff", or any variation implying they
  are going away and their brands need handing to colleagues with current numbers against KPI.
  Also trigger when the user drops a coverage or handover spreadsheet naming colleagues and
  brands. Even if the user just says "PTO" or "handoff" in passing — trigger this skill.
---

# PTO Coverage Handoff

Turns a coverage plan into (a) a per-colleague Slack handoff DM and (b) a KPI-vs-actual table
for the person going away. Built for the buddy system in the Sophie Society PTO policy: a buddy
watches for irregular ad spend and keeps campaigns stable, so the handoff has to carry real
numbers, not just brand names.

Anyone on the team can run this. Never assume the runner is a specific person — the runner is
whoever invoked the skill, and the DMs go to the colleagues they name.

## Deliverables

1. One Slack DM per covering colleague, containing **only the brands that colleague covers**.
2. One summary table back in chat for the runner, covering **all** brands and colleagues.

## Workflow

Run these steps in order. Do not skip the intake, and do not send any Slack message before
Step 6's approval.

### Step 1 — Intake

Ask for both of these in a single turn, in plain language:

1. **Who is covering?** Names of the covering colleagues (first name is enough).
2. **The coverage file** — which colleague covers which brand, and each brand's KPIs.
   Accepts `.xlsx`, `.xlsm`, `.csv`, or `.tsv`. If they don't have one, offer
   `assets/coverage-template.csv` and let them fill it in.

Also ask, as optional extras — do **not** block on these:

- **PTO dates** ("Aug 30 – Sep 5"). Omitted → leave the dates line out of the DM entirely.
- **Anything to flag per brand** (a launch mid-PTO, a pending client reply, a campaign to
  leave alone). Goes into that brand's `Notes` in the DM.

If the file already names the covering colleagues, still confirm the list against Step 1's
answer — a name in the file that the runner didn't mention is usually a stale row, so ask
rather than DMing someone unexpected.

### Step 2 — Parse the coverage file

Run the parser — it handles the header aliases and the percent/period normalisation so you
don't have to eyeball them:

```bash
python3 scripts/parse_coverage.py <coverage-file> --out /tmp/coverage.json
```

It prints a human-readable summary and writes `coverage.json`. Read
`references/coverage-file.md` for the accepted columns, the alias list, and the normalisation
rules **before** interpreting anything the parser flags.

If the parser reports `warnings`, resolve them with the runner before continuing. A missing KPI
is not fatal — that metric just reports as actual-only, no delta.

### Step 3 — Resolve each brand to a store

Call `list_stores` (`compact: true`) and match each coverage-file brand to a store name.

Matching rules:

- Case-insensitive, ignore punctuation and trademark marks (`™`, `®`, `©`), collapse whitespace,
  treat `&` and `and` as equivalent. So `hush and hush` → `Hush & Hush`, `auris` → `Auris™`.
- **Ambiguity must go to the runner.** The store list genuinely contains near-duplicates
  (two `Caroline's Cats`, plus `Auris™` and `Auris®`). When a brand matches more than one
  store, use `AskUserQuestion` listing the candidates with their store names — never pick one
  silently and never merge two stores into one row.
- No match at all → ask. Don't guess from a partial substring.

Keep a `brand → seller_id + profile_id(s) + marketplace_id(s)` map for the rest of the run.
Get `profile_id` and `marketplace_id` from Step 5's `list_ad_campaigns` response, or from
`list_stores` with `compact: false`.

### Step 4 — Pull last-7-days performance per brand

For each store, one call:

```
get_account_performance_summary(store: <seller_id>, days: 7)
```

Read `references/metrics.md` for the exact field mapping, the multi-currency rule, and the
KPI-delta maths. The short version:

- **Sales** = `data.derived.total_revenue` (total, not ad sales)
- **Spend** = `data.derived.ad_spend`
- **ACOS** = `data.derived.acos`, **TACOS** = `data.derived.tacos` — both are **fractions**
  (`0.6996` = 69.96%), so multiply by 100 for display
- Window actually used = `data.window.start` / `.end`. Quote these dates, don't assume.

**Never** average or sum money across currencies. If the money fields come back `null`, the
store spent in more than one currency — read `data.ads.by_currency` and report each currency
separately. Say so in the DM rather than reporting a blank.

The last day or two of Sales & Traffic can still be settling, so label the window
"last 7 days (<start> – <end>)" and don't present a 7-day figure as final.

A store with no registered ads profiles makes this call **error**, not return zeros. Record that
brand with `null` metrics and an `unavailable_reason` (see `references/metrics.md`) and keep
going — it still belongs in its colleague's DM.

### Step 5 — Read live daily ad budgets

Daily budgets are current campaign state, not report data — they need the live Amazon Ads path.
Full procedure in `references/metrics.md` (§ Daily budgets). Summary:

1. `list_ad_campaigns(store, state: "ENABLED")` → campaign IDs, `profile_id`, `ad_type`.
   This gives structure only, **no budgets** — don't stop here.
2. Per `ad_type` present (SP / SB / SD), call
   `sophie_call_amazon_ads_mcp(profile_id, "campaign_management-query_campaign", …)` with
   `campaignIdFilter` batches and read `budgets[].budgetValue.monetaryBudgetValue.monetaryBudget.value`
   where `recurrenceTimePeriod == "DAILY"`.
3. Report the **sum of DAILY budgets across ENABLED campaigns**, per currency, and the
   campaign count behind it.

This is a read-only call. Never call `campaign_management-update_campaign_budget` or any other
`update_*` / `create_*` / `delete_*` tool in this skill — a coverage handoff never changes an
account. If the budget read fails or is unauthorised, write "Daily budget: unavailable" and
carry on; it must not block the handoff.

### Step 6 — Build the messages and get approval

Write the metrics you gathered to `/tmp/metrics.json` in the shape documented in
`references/metrics.md` (§ metrics.json contract), then:

```bash
python3 scripts/build_report.py --coverage /tmp/coverage.json --metrics /tmp/metrics.json \
  --out-dir /tmp/pto-coverage --runner "<runner's first name>" --dates "<PTO dates>"
```

Drop `--dates` if the runner didn't give any — the DM then leaves the dates out rather than
inventing a range. `--runner` shapes the DM opener; omit it and the opener still reads correctly.

This does the delta maths and the on/off-track calls deterministically, and writes one
`dm-<colleague>.md` per colleague plus `summary.md`. Read `references/messaging.md` for the
message anatomy and the tone rules.

Then:

1. Resolve each colleague to a Slack user ID with `slack_search_users`. Two people matching one
   first name → `AskUserQuestion`, don't pick. No match → ask the runner for the handle.
2. **Show the runner every DM in full, in chat, and ask for explicit approval to send.** These
   messages go to colleagues and carry client numbers; the runner approves them first, every
   run. If the runner wants edits, edit and re-show.
3. Approved → send with `slack_send_message` to each colleague's user ID as `channel_id`.
   If the runner would rather review inside Slack, use `slack_send_message_draft` instead.

Report the message links back. If a send fails, say which colleague didn't get theirs —
never report a partial run as complete.

### Step 7 — Summary back to the runner

Print `summary.md` in chat: every brand, its covering colleague, the four metrics, the deltas,
and the daily budget. Then flag anything that needs the runner's attention before they leave —
metrics off-track against KPI, brands with no KPI in the file, brands with no assigned
colleague, and any budget or currency gaps.

Close with the one policy reminder that actually bites (see `references/messaging.md`): a PTO of
more than 4 working days needs the Squad lead told at least 2 weeks ahead, with a Suptask
"Days Off" ticket filed.

There is **no limit** on how many brands one colleague may cover. Report the split as the
coverage file states it — never flag a count as too high and never propose redistributing.

## Rules

- **Read-only on accounts.** This skill reads. It never edits campaigns, budgets, bids or listings.
- **Approval before every send.** No Slack message reaches a colleague unapproved.
- **Never invent a number.** A metric that didn't come back is "unavailable", not zero and not
  an estimate. Same for a KPI the file doesn't specify.
- **Split by colleague.** A DM contains only that colleague's brands. Don't broadcast the whole
  coverage plan to everyone.
- **Currency-honest.** Report each currency separately; never convert or blend.
- **Pace the calls.** Many brands → the ads reads are the heavy ones. Work store by store
  rather than firing everything at once.
