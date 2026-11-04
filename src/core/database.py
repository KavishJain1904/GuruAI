import os
from contextlib import contextmanager

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv
from pgvector.psycopg2 import register_vector

# Load .env here too (not just in config.py) — this module reads DATABASE_URL
# at import time, and which module gets imported first (and therefore whose
# load_dotenv() call runs first) isn't guaranteed, so this can't rely on
# config.py having already loaded it.
load_dotenv()

DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://guruai:guruai_dev_pw@localhost:5432/guruai_dev"
)

# 768 = the configured output_dimensionality of gemini-embedding-001 (src/rag/embedder.py).
EMBEDDING_DIM = 768

# NOTE: a connection pool was tried here (each get_db() call opening a fresh
# connection to a remote DATABASE_URL like Neon was measured at ~2-4s of pure
# handshake time). It was reverted: a persistent pool needs eager pre-warming
# to avoid a *worse* regression (a lazily-grown pool serializes concurrent
# requests behind a single lock while it grows — measured 11.5s for 6
# concurrent requests), but pre-warming itself costs ~15-30s at every server
# startup, which dominates for a single-user workflow with frequent restarts
# during development — and it still isn't free of failure modes (hit a live
# "connection reset by peer" from Neon's pooler while warming 10 connections
# at once). Plain per-call connect/close has none of that fragility and no
# startup tax; it's simply not worth the complexity here. If this app ever
# serves real concurrent multi-user traffic, revisit pooling — with the
# pool pre-warmed at startup and sized to measured concurrency, not a guess.
def close_pool() -> None:
    """No-op kept so existing callers (e.g. tests/smoke_test.py, which calls
    this before DROP DATABASE) don't need to change now that there's no pool."""
    pass


@contextmanager
def get_db():
    """Returns a Postgres connection that auto-closes on exit. Always use with `with get_db() as conn:`."""
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)
    register_vector(conn)
    try:
        yield conn
    finally:
        conn.close()

def init_db():
    """Initializes the database schema if tables do not exist."""
    schema = f"""
    CREATE EXTENSION IF NOT EXISTS vector;

    CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        name TEXT DEFAULT 'The Scholar',
        bio TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS sessions (
        id TEXT PRIMARY KEY,
        user_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        quiz_json TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS messages (
        id SERIAL PRIMARY KEY,
        session_id TEXT NOT NULL,
        role TEXT NOT NULL,
        content TEXT NOT NULL,
        sources TEXT,
        recommendation TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
    );

    ALTER TABLE messages ADD COLUMN IF NOT EXISTS recommendation TEXT;

    CREATE TABLE IF NOT EXISTS documents (
        id SERIAL PRIMARY KEY,
        session_id TEXT NOT NULL,
        doc_id TEXT,
        name TEXT NOT NULL,
        size INTEGER NOT NULL,
        file_type TEXT,
        status TEXT NOT NULL DEFAULT 'ready',
        storage_path TEXT,
        chunk_count INTEGER DEFAULT 0,
        error TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS knowledge_profile (
        id SERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL,
        subject TEXT NOT NULL,
        topic TEXT NOT NULL,
        correct INTEGER DEFAULT 0,
        total INTEGER DEFAULT 0,
        ema_score REAL,
        last_reviewed_at TIMESTAMP DEFAULT NULL,
        review_interval_days INTEGER DEFAULT 1,
        review_count INTEGER DEFAULT 0,
        next_review_date TIMESTAMP DEFAULT NULL,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
        UNIQUE(user_id, subject, topic)
    );

    -- Additive upgrade for databases created before outcome-aware SRS.
    -- Existing attempt counts do not establish a success streak.
    ALTER TABLE knowledge_profile
        ADD COLUMN IF NOT EXISTS review_success_streak INTEGER NOT NULL DEFAULT 0;

    CREATE TABLE IF NOT EXISTS review_events (
        id BIGSERIAL PRIMARY KEY,
        topic_id INTEGER NOT NULL REFERENCES knowledge_profile(id) ON DELETE CASCADE,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        session_id TEXT REFERENCES sessions(id) ON DELETE SET NULL,
        kind TEXT NOT NULL CHECK (kind IN ('quiz', 'self_rating')),
        score REAL NOT NULL CHECK (score >= 0 AND score <= 1),
        mastery_before REAL NOT NULL,
        mastery_after REAL NOT NULL,
        review_interval_days INTEGER NOT NULL,
        next_review_date TIMESTAMP NOT NULL,
        reviewed_at TIMESTAMP NOT NULL,
        question TEXT,
        selected_answer TEXT,
        correct_answer TEXT,
        notes TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_review_events_user_id ON review_events(user_id, id DESC);
    CREATE INDEX IF NOT EXISTS idx_review_events_topic_id ON review_events(topic_id, id DESC);
    CREATE INDEX IF NOT EXISTS idx_review_events_session_id ON review_events(session_id);

    -- Curriculum graph: shared per-subject topic relationships (prerequisites,
    -- related topics). Not per-user — per-user mastery stays in knowledge_profile.
    -- Keyed on the same (subject, topic) text pairs knowledge_profile uses,
    -- normalized the same way (see mastery.py's .strip().title()); there's no
    -- separate topics dimension table to hang a foreign key off of.
    CREATE TABLE IF NOT EXISTS topic_edges (
        id SERIAL PRIMARY KEY,
        subject TEXT NOT NULL,
        from_topic TEXT NOT NULL,       -- the prerequisite
        to_topic TEXT NOT NULL,         -- the topic that depends on it
        relation TEXT NOT NULL DEFAULT 'prerequisite_of',
        weight REAL DEFAULT 1.0,
        source TEXT NOT NULL DEFAULT 'llm',  -- 'seed' | 'llm' | 'manual' — provenance,
                                              -- so a future regen only touches 'llm' rows
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(subject, from_topic, to_topic, relation)
    );

    CREATE TABLE IF NOT EXISTS user_subjects (
        id SERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL,
        subject TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
        UNIQUE(user_id, subject)
    );

    CREATE TABLE IF NOT EXISTS user_memories (
        id SERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL,
        memory_item TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
        UNIQUE(user_id, memory_item)
    );

    CREATE TABLE IF NOT EXISTS memory_chat_history (
        id SERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL,
        role TEXT NOT NULL,
        content TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    );

    -- Replaces the local per-session FAISS index: one row per chunk, embedding
    -- stored directly alongside its text and source metadata (see src/rag/embedder.py).
    CREATE TABLE IF NOT EXISTS document_chunks (
        id SERIAL PRIMARY KEY,
        session_id TEXT NOT NULL,
        document_id TEXT,
        content TEXT NOT NULL,
        metadata JSONB,
        embedding vector({EMBEDDING_DIM}),
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
    );

    -- Performance indexes: every foreign-key column used in a WHERE clause.
    CREATE INDEX IF NOT EXISTS idx_sessions_user_id        ON sessions(user_id);
    CREATE INDEX IF NOT EXISTS idx_messages_session_id      ON messages(session_id);
    CREATE INDEX IF NOT EXISTS idx_documents_session_id     ON documents(session_id);
    CREATE INDEX IF NOT EXISTS idx_memory_chat_user_id      ON memory_chat_history(user_id);
    CREATE INDEX IF NOT EXISTS idx_knowledge_profile_user   ON knowledge_profile(user_id);
    CREATE INDEX IF NOT EXISTS idx_user_memories_user_id    ON user_memories(user_id);
    CREATE INDEX IF NOT EXISTS idx_user_subjects_user_id    ON user_subjects(user_id);
    CREATE INDEX IF NOT EXISTS idx_document_chunks_session_id ON document_chunks(session_id);
    CREATE INDEX IF NOT EXISTS idx_topic_edges_subject      ON topic_edges(subject);
    CREATE INDEX IF NOT EXISTS idx_topic_edges_from         ON topic_edges(subject, from_topic);
    CREATE INDEX IF NOT EXISTS idx_topic_edges_to           ON topic_edges(subject, to_topic);

    CREATE UNIQUE INDEX IF NOT EXISTS idx_documents_session_name ON documents(session_id, name);
    """
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(schema)
        conn.commit()
