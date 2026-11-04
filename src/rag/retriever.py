from collections import OrderedDict
from typing import List
from langchain_core.retrievers import BaseRetriever
from langchain_core.documents import Document
from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langchain_community.retrievers import TFIDFRetriever
from pgvector import Vector

from src.core.database import get_db
from src.rag.embedder import get_embeddings


def _doc_key(doc: Document) -> str:
    """Dedup key for RRF. Includes document_id so identical text in two
    different source documents doesn't collide into a single entry."""
    return f"{doc.metadata.get('document_id', '')}|{doc.page_content}"


def reciprocal_rank_fusion(dense_results: List[Document], sparse_results: List[Document], k: int = 60) -> List[Document]:
    """
    Applies Reciprocal Rank Fusion (RRF) to merge dense and sparse search results.
    """
    rrf_scores = {}
    doc_map = {}

    for rank, doc in enumerate(dense_results):
        key = _doc_key(doc)
        doc_map[key] = doc
        r = rank + 1
        rrf_scores[key] = rrf_scores.get(key, 0.0) + (1.0 / (k + r))

    for rank, doc in enumerate(sparse_results):
        key = _doc_key(doc)
        doc_map[key] = doc
        r = rank + 1
        rrf_scores[key] = rrf_scores.get(key, 0.0) + (1.0 / (k + r))

    sorted_docs = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)
    return [doc_map[key] for key, _ in sorted_docs]


def diversify_by_document(docs: List[Document], top_n: int) -> List[Document]:
    """
    Round-robin re-ranking across source documents so a session with multiple
    uploaded documents doesn't let one document (e.g. a longer or more
    generically-similar one) monopolize every retrieval slot.

    Each document's chunks keep their relative order from `docs` (already
    ranked by RRF), but selection cycles through documents one chunk at a
    time. A document with no relevant chunks simply contributes nothing —
    this only kicks in when there's genuine cross-document competition.
    """
    buckets: "OrderedDict[str, list]" = OrderedDict()
    for doc in docs:
        doc_key = doc.metadata.get("document_id") or doc.metadata.get("source") or "unknown"
        buckets.setdefault(doc_key, []).append(doc)

    doc_keys = list(buckets.keys())
    result: List[Document] = []
    i = 0
    while len(result) < top_n and any(buckets[key] for key in doc_keys):
        key = doc_keys[i % len(doc_keys)]
        if buckets[key]:
            result.append(buckets[key].pop(0))
        i += 1
    return result[:top_n]


class HybridRetriever(BaseRetriever):
    session_id: str
    tfidf_retriever: TFIDFRetriever
    top_n: int = 4

    class Config:
        arbitrary_types_allowed = True

    def _dense_search(self, query: str, k: int) -> List[Document]:
        """Dense half: pgvector cosine-distance search over this session's chunks
        (replaces FAISS.similarity_search)."""
        query_vector = Vector(get_embeddings().embed_query(query))
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT content, metadata FROM document_chunks "
                "WHERE session_id = %s ORDER BY embedding <=> %s LIMIT %s",
                (self.session_id, query_vector, k),
            )
            rows = cur.fetchall()
        return [Document(page_content=r["content"], metadata=r["metadata"] or {}) for r in rows]

    def _get_relevant_documents(
        self, query: str, *, run_manager: CallbackManagerForRetrieverRun = None
    ) -> List[Document]:
        print(f"\n--- [HybridRetriever] Processing Query: '{query}' ---")

        # Fetch a wider candidate pool than top_n so diversify_by_document has
        # enough chunks per document to work with in multi-document sessions.
        fetch_k = max(self.top_n * 6, 20)

        # 1. Retrieve from dense (pgvector)
        dense_docs = self._dense_search(query, fetch_k)

        # 2. Retrieve from sparse (TF-IDF)
        self.tfidf_retriever.k = fetch_k
        sparse_docs = self.tfidf_retriever.invoke(query)

        # 3. Merge using RRF, then re-rank for cross-document fairness
        merged_docs = reciprocal_rank_fusion(dense_docs, sparse_docs)
        final_docs = diversify_by_document(merged_docs, self.top_n)

        return final_docs
