import os
import sqlite3
from pathlib import Path

DEFAULT_DB_PATH = "kwtrack.db"
SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def resolve_db_path(explicit: str | None = None) -> str:
    if explicit:
        return explicit
    return os.environ.get("KWTRACK_DB", DEFAULT_DB_PATH)


def connect(db_path: str | None = None) -> sqlite3.Connection:
    path = resolve_db_path(db_path)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    sql = SCHEMA_PATH.read_text(encoding="utf-8")
    with conn:
        conn.executescript(sql)


def ensure_keyword(conn: sqlite3.Connection, phrase: str) -> int:
    """Return keyword id, inserting if needed. Case-insensitive lookup."""
    phrase = phrase.strip()
    if not phrase:
        raise ValueError("empty keyword phrase")
    row = conn.execute(
        "SELECT id FROM keywords WHERE phrase = ? COLLATE NOCASE", (phrase,)
    ).fetchone()
    if row:
        return row["id"]
    cur = conn.execute("INSERT INTO keywords (phrase) VALUES (?)", (phrase,))
    return cur.lastrowid


def ensure_tracking_row(conn: sqlite3.Connection, keyword_id: int, market: str) -> None:
    """Ensure a tracking row exists. Never overwrites existing status/notes."""
    conn.execute(
        "INSERT OR IGNORE INTO keyword_market_tracking (keyword_id, market) VALUES (?, ?)",
        (keyword_id, market),
    )
