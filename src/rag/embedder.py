import json

from langchain_google_genai import GoogleGenerativeAIEmbeddings
from pgvector import Vector

from src.core.config import GOOGLE_API_KEY
from src.core.database import get_db

"""
This file is the Brain Builder for your application. It embeds each uploaded
chunk and stores it in the `document_chunks` table (Postgres + pgvector),
keyed by session_id, so retrieval can query it directly instead of loading a
local FAISS index.
"""

_MODEL_NAME = "models/gemini-embedding-001"
_OUTPUT_DIM = 768  # must match src.core.database.EMBEDDING_DIM

# ── Cached embedding client singleton ──
# Hosted, not local: no model weights to load, so this just avoids
# re-constructing the client object on every embed call.
_embeddings = None

def get_embeddings():
    """Return the cached embedding client (built once on first call)."""
    global _embeddings
    if _embeddings is None:
        _embeddings = GoogleGenerativeAIEmbeddings(
            model=_MODEL_NAME,
            google_api_key=GOOGLE_API_KEY,
            output_dimensionality=_OUTPUT_DIM,
        )
    return _embeddings

def get_db_path(session_id: str) -> str:
    """Legacy label, kept only for the `documents.storage_path` metadata column.
    Chunks now live in the document_chunks table, not on local disk."""
    return f"postgres:document_chunks:{session_id}"

def vectorstore_exists(session_id: str) -> bool:
    """True if a session has any embedded chunks stored."""
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM document_chunks WHERE session_id = %s LIMIT 1", (session_id,))
        return cur.fetchone() is not None

def delete_vectorstore(session_id: str) -> None:
    """Remove a session's embedded chunks. No-op if there were none."""
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM document_chunks WHERE session_id = %s", (session_id,))
        conn.commit()

def create_vectorstore(docs, session_id: str):
    """Embed each chunk and insert it into document_chunks for this session.

    Multi-document sessions accumulate naturally: this always inserts new rows
    rather than replacing existing ones, so a second upload batch adds to the
    first instead of wiping it out.
    """
    print("Generating embeddings via Gemini and saving to Postgres...")
    model = get_embeddings()
    texts = [d.page_content for d in docs]
    vectors = model.embed_documents(texts)

    with get_db() as conn:
        cur = conn.cursor()
        for doc, vector in zip(docs, vectors):
            cur.execute(
                """
                INSERT INTO document_chunks (session_id, document_id, content, metadata, embedding)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    session_id,
                    doc.metadata.get("document_id"),
                    doc.page_content,
                    json.dumps(doc.metadata),
                    Vector(vector),
                ),
            )
        conn.commit()
    return session_id

def load_existing_vectorstore(session_id: str):
    """Kept for interface compatibility with older callers; returns the
    session_id if it has embedded chunks, else None. New code should query
    document_chunks directly (see src/rag/retriever.py, src/api/retriever_cache.py,
    src/rag/quiz.py) rather than treating this as a loadable FAISS object."""
    return session_id if vectorstore_exists(session_id) else None
