-- kwtrack SQLite schema.
-- Safe to run repeatedly: every object uses IF NOT EXISTS.

PRAGMA foreign_keys = ON;

-- Fixed list of markets we track.
CREATE TABLE IF NOT EXISTS markets (
    code TEXT PRIMARY KEY,
    name TEXT NOT NULL
);

INSERT OR IGNORE INTO markets (code, name) VALUES
    ('US', 'United States'),
    ('UK', 'United Kingdom'),
    ('DE', 'Germany'),
    ('FR', 'France');

-- Canonical keyword phrases. NOCASE collation so "Coffee Mug" and
-- "coffee mug" are treated as the same keyword (Amazon ignores case).
CREATE TABLE IF NOT EXISTS keywords (
    id INTEGER PRIMARY KEY,
    phrase TEXT NOT NULL UNIQUE COLLATE NOCASE,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Persistent tracking state per (keyword, market).
-- Importers create empty rows here as needed but NEVER overwrite
-- status/notes once set.
CREATE TABLE IF NOT EXISTS keyword_market_tracking (
    keyword_id INTEGER NOT NULL REFERENCES keywords(id) ON DELETE CASCADE,
    market    TEXT    NOT NULL REFERENCES markets(code),
    status    TEXT,
    notes     TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (keyword_id, market)
);

-- One row per imported file. Used to group snapshots and detect duplicate
-- imports via file_hash.
CREATE TABLE IF NOT EXISTS import_runs (
    id          INTEGER PRIMARY KEY,
    source      TEXT NOT NULL CHECK (source IN ('cerebro', 'adlabs')),
    market      TEXT NOT NULL REFERENCES markets(code),
    file_path   TEXT NOT NULL,
    file_hash   TEXT,
    imported_at TEXT NOT NULL DEFAULT (datetime('now')),
    row_count   INTEGER,
    notes       TEXT
);

CREATE INDEX IF NOT EXISTS idx_import_runs_source_market
    ON import_runs(source, market, imported_at);

CREATE UNIQUE INDEX IF NOT EXISTS uq_import_runs_hash
    ON import_runs(source, market, file_hash) WHERE file_hash IS NOT NULL;

-- Append-only Cerebro snapshots. Each (import_run, keyword) yields one row.
CREATE TABLE IF NOT EXISTS cerebro_snapshots (
    id              INTEGER PRIMARY KEY,
    import_run_id   INTEGER NOT NULL REFERENCES import_runs(id) ON DELETE CASCADE,
    keyword_id      INTEGER NOT NULL REFERENCES keywords(id) ON DELETE CASCADE,
    market          TEXT    NOT NULL REFERENCES markets(code),
    captured_at     TEXT    NOT NULL,
    -- Core Cerebro metrics. All numeric fields are nullable; Cerebro often
    -- emits blanks or "-" which we coerce to NULL.
    cerebro_iq_score        INTEGER,
    search_volume           INTEGER,
    search_volume_trend     REAL,
    sponsored_asins         INTEGER,
    competing_products      INTEGER,
    cpr                     INTEGER,
    title_density           INTEGER,
    amazon_recommended_rank INTEGER,
    sponsored_rank          INTEGER,
    organic_rank            INTEGER,
    keyword_sales           INTEGER,
    aba_total_click_share   REAL,
    aba_total_conv_share    REAL,
    -- Catch-all for fields we don't model individually (per-ASIN ranks,
    -- new Cerebro columns, etc.). JSON object.
    extra_json TEXT,
    UNIQUE (import_run_id, keyword_id)
);

CREATE INDEX IF NOT EXISTS idx_cerebro_kw_market
    ON cerebro_snapshots(keyword_id, market, captured_at);

-- AdLabs (ad search-term) snapshot stub. Filled in when we wire that
-- importer; declaring it now keeps the schema stable.
CREATE TABLE IF NOT EXISTS adlabs_snapshots (
    id              INTEGER PRIMARY KEY,
    import_run_id   INTEGER NOT NULL REFERENCES import_runs(id) ON DELETE CASCADE,
    keyword_id      INTEGER NOT NULL REFERENCES keywords(id) ON DELETE CASCADE,
    market          TEXT    NOT NULL REFERENCES markets(code),
    captured_at     TEXT    NOT NULL,
    impressions     INTEGER,
    clicks          INTEGER,
    spend           REAL,
    sales           REAL,
    orders          INTEGER,
    acos            REAL,
    roas            REAL,
    extra_json      TEXT,
    UNIQUE (import_run_id, keyword_id)
);

CREATE INDEX IF NOT EXISTS idx_adlabs_kw_market
    ON adlabs_snapshots(keyword_id, market, captured_at);

-- Latest snapshot per (keyword, market) for each source.
CREATE VIEW IF NOT EXISTS cerebro_latest AS
SELECT s.*
FROM cerebro_snapshots s
JOIN (
    SELECT keyword_id, market, MAX(captured_at) AS max_captured
    FROM cerebro_snapshots
    GROUP BY keyword_id, market
) m
  ON m.keyword_id  = s.keyword_id
 AND m.market      = s.market
 AND m.max_captured = s.captured_at;

CREATE VIEW IF NOT EXISTS adlabs_latest AS
SELECT s.*
FROM adlabs_snapshots s
JOIN (
    SELECT keyword_id, market, MAX(captured_at) AS max_captured
    FROM adlabs_snapshots
    GROUP BY keyword_id, market
) m
  ON m.keyword_id  = s.keyword_id
 AND m.market      = s.market
 AND m.max_captured = s.captured_at;
