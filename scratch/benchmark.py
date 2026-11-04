import os
import time
import numpy as np
from langchain_core.documents import Document
from langchain_community.vectorstores import FAISS
from langchain_community.retrievers import TFIDFRetriever
from src.rag.embedder import get_embeddings
from src.rag.retriever import HybridRetriever

def run_benchmarks():
    print("==================================================")
    print("       STARTING LOCAL RAG BENCHMARK SUITE         ")
    print("==================================================")
    
    # 1. Prepare Dataset (100 synthetic documents to simulate a textbook chapter)
    print("\n1. Preparing dataset (100 documents)...")
    docs = []
    for i in range(99):
        docs.append(Document(
            page_content=f"This is document number {i}. It contains general educational information about computer science topic {i % 10}. We discuss algorithms, data structures, and software engineering principles.",
            metadata={"source": "textbook.txt", "chunk": i}
        ))
    # Add a specific target document with a unique keyword for the accuracy test
    special_doc = Document(
        page_content="CRITICAL_KEYWORD_X: The unique configuration code is A109-B208. Use this for server authentication.",
        metadata={"source": "config.txt", "chunk": 99}
    )
    docs.append(special_doc)

    # 2. Measure Vector Store Creation & Embedding Latency
    print("\n2. Initializing Local Embedding Model & Indexing...")
    start_time = time.perf_counter()
    embeddings = get_embeddings()
    db = FAISS.from_documents(docs, embeddings)
    tfidf_retriever = TFIDFRetriever.from_documents(docs)
    end_time = time.perf_counter()
    init_duration = end_time - start_time
    print(f"   [RESULT] Created FAISS and TF-IDF index for {len(docs)} docs in: {init_duration:.4f} seconds")

    # 3. Instantiate Hybrid Retriever
    retriever = HybridRetriever(vectorstore=db, tfidf_retriever=tfidf_retriever, top_n=4)

    # 4. Measure Retrieval Latencies
    print("\n3. Measuring Retrieval Latencies (100 iterations each)...")
    
    # Dense Retrieval (FAISS)
    dense_times = []
    for _ in range(100):
        t0 = time.perf_counter()
        _ = db.similarity_search("algorithms and data structures", k=4)
        dense_times.append(time.perf_counter() - t0)
    
    # Sparse Retrieval (TF-IDF)
    sparse_times = []
    for _ in range(100):
        t0 = time.perf_counter()
        _ = tfidf_retriever.invoke("algorithms and data structures")
        sparse_times.append(time.perf_counter() - t0)
        
    # Hybrid Retrieval (FAISS + TF-IDF + RRF)
    hybrid_times = []
    for _ in range(100):
        t0 = time.perf_counter()
        _ = retriever.invoke("algorithms and data structures")
        hybrid_times.append(time.perf_counter() - t0)
        
    print(f"   [RESULT] Dense (FAISS) Mean Latency:  {np.mean(dense_times)*1000:.2f} ms")
    print(f"   [RESULT] Sparse (TF-IDF) Mean Latency: {np.mean(sparse_times)*1000:.2f} ms")
    print(f"   [RESULT] Hybrid (RRF) Mean Latency:    {np.mean(hybrid_times)*1000:.2f} ms")

    # 5. Retrieval Accuracy Proof (Keyword vs Semantic)
    print("\n4. Proving Hybrid Retrieval Accuracy...")
    query = "Where can I find CRITICAL_KEYWORD_X config?"
    
    # Dense only
    dense_results = db.similarity_search(query, k=4)
    dense_found = any("CRITICAL_KEYWORD_X" in doc.page_content for doc in dense_results)
    
    # Sparse only
    sparse_results = tfidf_retriever.invoke(query)
    sparse_found = any("CRITICAL_KEYWORD_X" in doc.page_content for doc in sparse_results)
    
    # Hybrid
    hybrid_results = retriever.invoke(query)
    hybrid_found = any("CRITICAL_KEYWORD_X" in doc.page_content for doc in hybrid_results)
    
    print(f"   Query: '{query}'")
    print(f"   [RESULT] Dense (Vector) found target: {dense_found}")
    print(f"   [RESULT] Sparse (Keyword) found target: {sparse_found}")
    print(f"   [RESULT] Hybrid (Merged) found target: {hybrid_found}")
    
    # 6. CRAG Context/Token Reduction Simulation
    print("\n5. Simulating Corrective RAG (CRAG) Token Savings...")
    # Assume 4 documents are retrieved initially
    initial_char_count = sum(len(doc.page_content) for doc in hybrid_results)
    
    # Simulate CRAG filtering out 2 irrelevant documents (representing a 50% filter rate)
    filtered_results = hybrid_results[:2]
    filtered_char_count = sum(len(doc.page_content) for doc in filtered_results)
    
    saved_chars = initial_char_count - filtered_char_count
    savings_pct = (saved_chars / initial_char_count) * 100 if initial_char_count > 0 else 0
    
    print(f"   [RESULT] Raw Context Size:      {initial_char_count} characters")
    print(f"   [RESULT] CRAG Filtered Size:    {filtered_char_count} characters")
    print(f"   [RESULT] Token/Context Savings: {savings_pct:.1f}% reduction in prompt size")
    print("==================================================")

if __name__ == "__main__":
    run_benchmarks()
