# kwtrack

Amazon keyword tracking across the **US, UK, DE, FR** markets.

- Ingests **Helium10 Cerebro** CSVs and **AdLabs** ad search-term exports.
- Stores everything in a single **SQLite** database, with full history (every
  import is a snapshot — nothing is overwritten).
- Persists per-keyword/per-market **tracking state** (Status, Notes) across
  re-imports.
- Generates Excel reports matching a target workbook layout.

## Install

```bash
pip install -e .
```

This installs the `kwtrack` command.

## Quick start

```bash
# 1. Create the database (default path: ./kwtrack.db)
kwtrack init

# 2. Import a Cerebro CSV for a market
kwtrack import cerebro --market US --file imports/us_cerebro.csv

# 3. Import another file later — keywords accumulate, tracking state persists,
#    and every import is preserved as a separate snapshot.
kwtrack import cerebro --market UK --file imports/uk_cerebro.csv
```

Override the DB path with `--db path/to/kwtrack.db` (or env `KWTRACK_DB`).

## Data model

- `markets` — fixed list: US, UK, DE, FR.
- `keywords` — canonical keyword phrases (case-insensitive unique).
- `keyword_market_tracking` — per-keyword/per-market `status` and `notes`.
  **Never** overwritten by importers.
- `import_runs` — one row per imported file (source, market, hash, timestamp).
- `cerebro_snapshots` / `adlabs_snapshots` — append-only history. Each import
  inserts a fresh row per keyword.
- `cerebro_latest` / `adlabs_latest` — views exposing the most recent snapshot
  per keyword/market.

## Status

- [x] Project skeleton
- [x] SQLite schema
- [x] Cerebro importer
- [ ] AdLabs importer
- [ ] Excel report generator (pending sample workbook)
