"""Adds a sources column to messages so assistant replies keep their source
attribution (filename/page/url per Prompt 2) across page reloads and session
switches, not just for the live-streamed response.

messages is this project's chat-history table (see src/core/database.py).
Run directly with `python -m src.migrations.003_add_message_sources_column`.
"""
import sqlite3

from src.core.database import DB_FILE

TABLE = "messages"

COLUMNS = [
    ("sources", "TEXT"),
]


def _existing_columns(conn: sqlite3.Connection) -> set:
    cur = conn.execute(f"PRAGMA table_info({TABLE})")
    return {row[1] for row in cur.fetchall()}


def up(conn: sqlite3.Connection = None) -> None:
    """Add the sources column to messages."""
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
    """Remove the sources column from messages."""
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
    print(f"Applied sources column to {TABLE} in {DB_FILE}")
