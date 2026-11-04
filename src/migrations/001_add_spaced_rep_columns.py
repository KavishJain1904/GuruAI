"""Adds spaced-repetition scheduling columns to knowledge_profile.

knowledge_profile is this project's per-topic mastery table (see
src/core/database.py). Run directly with `python -m src.migrations.001_add_spaced_rep_columns`.
"""
import sqlite3

from src.core.database import DB_FILE

TABLE = "knowledge_profile"

COLUMNS = [
    ("last_reviewed_at", "TIMESTAMP DEFAULT NULL"),
    ("review_interval_days", "INTEGER DEFAULT 1"),
    ("review_count", "INTEGER DEFAULT 0"),
    ("next_review_date", "TIMESTAMP DEFAULT NULL"),
]


def _existing_columns(conn: sqlite3.Connection) -> set:
    cur = conn.execute(f"PRAGMA table_info({TABLE})")
    return {row[1] for row in cur.fetchall()}


def up(conn: sqlite3.Connection = None) -> None:
    """Add the spaced-repetition columns to knowledge_profile."""
    owns_conn = conn is None
    if owns_conn:
        conn = sqlite3.connect(DB_FILE)
    try:
        existing = _existing_columns(conn)
        for name, ddl in COLUMNS:
            if name not in existing:
                conn.execute(f"ALTER TABLE {TABLE} ADD COLUMN {name} {ddl}")
        conn.commit()
    finally:
        if owns_conn:
            conn.close()


def down(conn: sqlite3.Connection = None) -> None:
    """Remove the spaced-repetition columns from knowledge_profile."""
    owns_conn = conn is None
    if owns_conn:
        conn = sqlite3.connect(DB_FILE)
    try:
        existing = _existing_columns(conn)
        for name, _ in COLUMNS:
            if name in existing:
                conn.execute(f"ALTER TABLE {TABLE} DROP COLUMN {name}")
        conn.commit()
    finally:
        if owns_conn:
            conn.close()


if __name__ == "__main__":
    up()
    print(f"Applied spaced-repetition columns to {TABLE} in {DB_FILE}")
