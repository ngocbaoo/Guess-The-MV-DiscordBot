"""SQLite access layer.

Catalog tables (songs/aliases/frames) are read-only here. The bot only ever
writes to `scores`, which it creates itself with CREATE TABLE IF NOT EXISTS so
it never touches the crawler's schema.
"""
import sqlite3
from pathlib import Path

# Default db location mirrors the crawler: <repo>/db/bot.db
ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = ROOT / "db" / "bot.db"

SCORES_SCHEMA = """
CREATE TABLE IF NOT EXISTS scores (
  guild_id      TEXT NOT NULL,
  user_id       TEXT NOT NULL,
  period        TEXT NOT NULL,      -- 'all' or a week key 'YYYY-Www'
  points        INTEGER DEFAULT 0,
  correct_count INTEGER DEFAULT 0,
  fastest_ms    INTEGER,            -- fastest correct-answer time seen
  PRIMARY KEY (guild_id, user_id, period)
);
"""


def connect(db_path=DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Open the db with Row access and the scores table ensured."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    ensure_scores_table(conn)
    return conn


def ensure_scores_table(conn: sqlite3.Connection) -> None:
    conn.executescript(SCORES_SCHEMA)
    conn.commit()


def resolve_frame_path(file_path: str, db_path=DEFAULT_DB_PATH) -> Path:
    """frames.file_path is stored relative to the db/ directory; make it absolute.

    Play time never hits the network — frames are local files under db/frames/.
    """
    db_base = Path(db_path).resolve().parent
    return (db_base / file_path).resolve()
