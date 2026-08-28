# The Slack handoff DM

## Anatomy

One DM per covering colleague, containing only that colleague's brands.
`scripts/build_report.py` writes these as `dm-<colleague>.md`.

```
Hey <Colleague> — <Runner> here. You're covering <N> of my brands while I'm out
<dates, if given>. Here's where each one stands over the last 7 days
(<start> – <end>), against KPI.

*<Brand>*
• Sales: $3,359 — KPI $4,000 (weekly) — 16% under
• Ad spend: $936 — KPI $1,000 (weekly) — 6% under
• ACOS: 70.0% — KPI 35% — 35.0pts over
• TACOS: 27.9% — KPI 15% — 12.9pts over
• Daily budget: $412.50 across 56 enabled campaigns
• Note: <notes from the coverage file, if any>

*<Next brand>*
…

What I'd watch: <the off-track metrics, named>.
Ping me only if something breaks — otherwise it's all yours. Thanks for covering 🙏
```

Rules for the body:

- **Money** rounded to whole units (`$3,359`), with the store's own currency symbol or code.
- **Percentages** to one decimal (`70.0%`). KPI targets shown as the runner wrote them (`35%`).
- **ACOS / TACOS deltas in percentage points**, suffixed `pts` — never "% higher".
- Every metric line names the KPI. **No KPI → the metric shows the actual and stops**, with no
  invented target and no delta.
- A metric that didn't come back reads `unavailable`. Never `0`, never a guess.
- A multi-currency brand gets one line per currency and no money delta, with a short note
  saying why.
- Prorated targets say so: `KPI $4,000 (prorated from monthly)`.
- **"What I'd watch"** lists only genuinely off-track metrics, by name. Nothing off track →
  `Everything's tracking to KPI right now.` Never manufacture a concern to fill the line.

## Tone

Colleague to colleague. Warm, short, concrete. The reader is doing the runner a favour, so the
message asks rather than instructs, and never sounds like a client report or a compliance
checklist. No jargon the reader doesn't already use daily, no emoji beyond a closing 🙏, no
"per the attached". Numbers do the work.

## Length

If a DM exceeds 3,500 characters, send a short header message first, then one message per
brand. Don't truncate a brand's numbers to fit.

## Delivery

1. `slack_search_users` per colleague name → user ID. Two matches on one first name →
   `AskUserQuestion`, never pick. No match → ask the runner for the handle.
2. **Show the runner every DM in full and get explicit approval before sending.** Every run.
   These carry client numbers to other people.
3. `slack_send_message` with the colleague's user ID as `channel_id`. If the runner prefers to
   review inside Slack, use `slack_send_message_draft` instead.
4. Return the message links. A failed send is named, per colleague — a partial run is never
   reported as complete.

## Policy reminder for the runner

From the Sophie Society PTO policy — surface this in the closing summary, because it's the one
that actually bites. There is **no cap on how many brands one colleague can cover**: however
many the coverage file gives someone is fine, so never warn about the count or suggest
redistributing.

- PTO of **more than 4 working days** needs the Squad lead told **at least 2 weeks ahead**, the
  buddy introduced to the accounts 2 weeks ahead, and a **"Days Off" ticket filed via Suptask in
  Slack** listing dates, buddy name and the accounts covered. This skill does not file that
  ticket.

Mention it once, at the end. Don't repeat it into the colleagues' DMs — it's the runner's to
action, and a coverage DM is not the place for policy.
