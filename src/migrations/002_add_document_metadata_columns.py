"""Adds multi-document tracking columns to documents.

documents is this project's per-session uploaded-file table (see
src/core/database.py). Run directly with `python -m src.migrations.002_add_document_metadata_columns`.
"""
import sqlite3

from src.core.database import DB_FILE

TABLE = "documents"

COLUMNS = [
    ("doc_id", "TEXT"),
    ("file_type", "TEXT"),
    ("status", "TEXT NOT NULL DEFAULT 'ready'"),
    ("storage_path", "TEXT"),
    ("chunk_count", "INTEGER DEFAULT 0"),
    ("error", "TEXT"),
]


def _existing_columns(conn: sqlite3.Connection) -> set:
    cur = conn.execute(f"PRAGMA table_info({TABLE})")
    return {row[1] for row in cur.fetchall()}


def up(conn: sqlite3.Connection = None) -> None:
    """Add the document-metadata columns to documents."""
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
    """Remove the document-metadata columns from documents."""
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
    print(f"Applied document-metadata columns to {TABLE} in {DB_FILE}")
