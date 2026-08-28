# pto-coverage

A Claude skill for handing your brands to colleagues before you go on PTO.

You give it two things — **who's covering** and a **coverage file** (which colleague covers
which brand, plus each brand's KPIs). It pulls the last 7 days of sales, ad spend, ACOS and
TACOS per brand from Sophie Hub, compares every metric to its KPI, reads the live total daily
ad budget, and DMs each colleague a handoff with only their own brands. You approve every
message before it sends.

## Using it

Say any of: `PTO coverage`, `PTO handoff`, `I'm going on PTO`, `brief my buddy`,
`hand over my accounts`. Or just drop your coverage spreadsheet and say `PTO`.

Claude asks who's covering and for the file, then walks the rest.

## Sharing it with your team

The skill has to be installed into a Claude profile before anyone can trigger it by name — a
copy sitting in this repo won't fire. Two routes:

**Per person (quickest).** Package it and send the `.skill` file to whoever needs it:

```bash
python3 -m scripts.package_skill skills/pto-coverage ./dist
```

Run that from the `skill-creator` skill directory, passing the path to this folder. It validates
first (the `description` has a hard 1024-character limit) and writes `pto-coverage.skill`. When
that file is shared in a Claude conversation, its file card shows a **Save skill** button —
clicking it installs the skill into that person's profile. They then say "PTO coverage" and it
runs. Re-packaging and re-saving replaces the old copy, so updates are just a re-send.

**Whole team (better once it's settled).** Upload the same `.skill` to the org's skill set in
Claude settings. It then syncs to everyone automatically and nobody has to install anything —
this is how `eod-summary` and `weekly-client-actions` already reach the team. Needs an admin
with skill-management rights.

Either way the runner needs **Sophie Hub and Slack connected** in their own Claude account. The
skill reads whatever stores their connection can see, so each person gets their own brands —
there's nothing account-specific baked into the skill itself.

## Your coverage file

One row per brand. Only two columns are required — the brand and who's covering it.
Start from [`assets/coverage-template.csv`](assets/coverage-template.csv):

| Brand | Covering Colleague | Sales KPI | Sales KPI Period | Spend KPI | ACOS KPI | TACOS KPI | Daily Budget | Notes |
|---|---|---|---|---|---|---|---|---|
| Hush & Hush | Maria | 4000 | weekly | 1000 | 35% | 15% | 400 | Serum launch mid-week |

`.xlsx`, `.xlsm`, `.csv` and `.tsv` all work. Header names are flexible — `Target ACOS`,
`ACOS KPI` and `ACOS%` all land in the same place. A monthly sales target gets prorated to the
7-day window automatically. Leave a KPI blank and that metric just reports its actual with no
comparison. Full column list and alias table: [`references/coverage-file.md`](references/coverage-file.md).

## What it will not do

- **It never changes an account.** Reads only — no campaign, budget or bid edits.
- **It never sends unapproved.** Every DM is shown to you in full first.
- **It never invents a number.** A metric that didn't come back reads `unavailable`, not `0`.
- **It doesn't file your Suptask ticket.** More than 4 working days off still needs the "Days
  Off" ticket and 2 weeks' notice to your Squad lead. It reminds you; you file it.
- **It won't second-guess your split.** There's no cap on how many brands one colleague covers —
  give someone twelve and it reports all twelve without complaint.

## Requirements

Sophie Hub and Slack connected in Claude. `openpyxl` only if your coverage file is `.xlsx`
(`pip install openpyxl`) — CSV needs nothing.

## Layout

```
SKILL.md                          the workflow Claude follows
README.md                         this file
assets/coverage-template.csv      fill-in-the-blanks starting point
references/coverage-file.md       accepted columns, aliases, normalisation rules
references/metrics.md             MCP calls, field mapping, KPI delta maths
references/messaging.md           DM anatomy, tone, delivery rules
scripts/parse_coverage.py         coverage file -> normalised JSON
scripts/build_report.py           KPI deltas -> per-colleague DMs + summary
```
