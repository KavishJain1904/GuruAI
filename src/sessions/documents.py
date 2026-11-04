"""Uploaded-document metadata for a session.

Tracks one row per file so retrieved chunks stay traceable to their source.
The chunks themselves live in the session's FAISS index (src/rag/embedder.py).
"""
from typing import Optional

from src.core.database import get_db
from src.rag.embedder import delete_vectorstore


def add_document(
    session_id: str,
    doc_id: str,
    filename: str,
    size: int,
    file_type: str,
    status: str = "ready",
    storage_path: Optional[str] = None,
    chunk_count: int = 0,
    error: Optional[str] = None,
):
    """Save/update an uploaded document's metadata for the session in SQLite.

    Re-uploading a file with the same name in the same session updates its
    existing row (new doc_id, status, chunk_count, etc.) rather than creating
    a duplicate, matching the (session_id, name) uniqueness already in place.
    """
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO documents (session_id, doc_id, name, size, file_type, status, storage_path, chunk_count, error)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT(session_id, name) DO UPDATE SET
                doc_id = excluded.doc_id,
                size = excluded.size,
                file_type = excluded.file_type,
                status = excluded.status,
                storage_path = excluded.storage_path,
                chunk_count = excluded.chunk_count,
                error = excluded.error
            """,
            (session_id, doc_id, filename, size, file_type, status, storage_path, chunk_count, error)
        )
        conn.commit()


def get_session_documents(session_id: str) -> list:
    """Retrieve the list of documents for a specific session from SQLite."""
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT doc_id, name, size, file_type, status, storage_path, chunk_count, error, created_at "
            "FROM documents WHERE session_id = %s ORDER BY id ASC",
            (session_id,)
        )
        return [
            {
                "doc_id": r["doc_id"],
                "name": r["name"],
                "size": r["size"],
                "file_type": r["file_type"],
                "status": r["status"],
                "storage_path": r["storage_path"],
                "chunk_count": r["chunk_count"],
                "error": r["error"],
                "created_at": r["created_at"],
            }
            for r in cur.fetchall()
        ]


def clear_session_knowledge_base(session_id: str):
    """Wipe FAISS files and document metadata from SQLite, keeping chat history."""
    # 1. Clear the hard drive folder
    delete_vectorstore(session_id)

    # 2. Clear the SQLite rows
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM documents WHERE session_id = %s", (session_id,))
        conn.commit()
