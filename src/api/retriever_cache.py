"""Process-local LRU cache of per-session hybrid retrievers.

Building a retriever means fetching a session's chunks from Postgres and
fitting a TF-IDF model over them, which is far too slow to redo on every chat
turn. Entries are evicted least-recently-used first because each one holds
that session's chunk text in RAM for the TF-IDF fit.
"""
from collections import OrderedDict
from typing import Optional

from langchain_community.retrievers import TFIDFRetriever
from langchain_core.documents import Document

from src.core.database import get_db
from src.rag.embedder import load_existing_vectorstore
from src.rag.retriever import HybridRetriever

_cache: OrderedDict = OrderedDict()
_MAX_ENTRIES = 32
_TOP_N = 4


def _fetch_session_documents(session_id: str) -> list[Document]:
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT content, metadata FROM document_chunks WHERE session_id = %s",
            (session_id,),
        )
        rows = cur.fetchall()
    return [Document(page_content=r["content"], metadata=r["metadata"] or {}) for r in rows]


def _build(session_id: str) -> HybridRetriever:
    """Fit a sparse TF-IDF retriever over this session's chunks and pair the two."""
    docs = _fetch_session_documents(session_id)
    tfidf_retriever = TFIDFRetriever.from_documents(docs)
    return HybridRetriever(session_id=session_id, tfidf_retriever=tfidf_retriever, top_n=_TOP_N)


def get(session_id: str) -> Optional[HybridRetriever]:
    """Return a cached retriever, building it if needed. None if no chunks exist yet."""
    if session_id in _cache:
        _cache.move_to_end(session_id)  # Mark as recently used
        return _cache[session_id]

    if not load_existing_vectorstore(session_id):
        return None

    retriever = _build(session_id)
    _cache[session_id] = retriever
    if len(_cache) > _MAX_ENTRIES:
        _cache.popitem(last=False)  # Evict least-recently-used
    return retriever


def refresh(session_id: str, vectorstore=None) -> None:
    """Rebuild and cache the retriever after a session's chunks change.

    `vectorstore` is accepted for call-site compatibility (sessions.py passes
    create_vectorstore's return value) but unused — the rebuild always fetches
    fresh chunks straight from Postgres for this session_id.
    """
    _cache[session_id] = _build(session_id)


def invalidate(session_id: str) -> None:
    """Drop a session's cached retriever, if present."""
    _cache.pop(session_id, None)
