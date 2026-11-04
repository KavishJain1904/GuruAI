"""Chat session and message persistence.
"""
import json
import uuid
from datetime import datetime
from typing import Dict, List, Optional

from src.core.database import get_db
from src.rag.embedder import delete_vectorstore


def load_all_sessions(user_id: int) -> Dict:
    """Load the session dictionary for a specific user from SQLite."""
    with get_db() as conn:
        cur = conn.cursor()

        # 1. Single query: all sessions for this user
        cur.execute(
            "SELECT id, title, updated_at FROM sessions WHERE user_id = %s ORDER BY updated_at DESC",
            (user_id,)
        )
        session_rows = cur.fetchall()
        session_ids = [r["id"] for r in session_rows]

        if not session_ids:
            return {}

        placeholders = ",".join(["%s"] * len(session_ids))

        # 2. Single query: ALL messages across ALL sessions at once
        cur.execute(
            f"SELECT session_id, role, content FROM messages WHERE session_id IN ({placeholders}) ORDER BY id ASC",
            session_ids
        )
        messages_by_session = {}
        for mr in cur.fetchall():
            sid = mr["session_id"]
            role, content = mr["role"], mr["content"]
            if role == "quiz":
                try:
                    content = json.loads(content)
                except Exception:
                    pass
            messages_by_session.setdefault(sid, []).append({"role": role, "content": content})

        # 3. Single query: ALL documents across ALL sessions at once
        cur.execute(
            f"SELECT session_id, name, size FROM documents WHERE session_id IN ({placeholders})",
            session_ids
        )
        docs_by_session = {}
        for dr in cur.fetchall():
            docs_by_session.setdefault(dr["session_id"], []).append(
                {"name": dr["name"], "size": dr["size"]}
            )

        # Assemble final dict from pre-fetched data
        sessions = {}
        for r in session_rows:
            sid = r["id"]
            sessions[sid] = {
                "title": r["title"],
                "messages": messages_by_session.get(sid, []),
                "documents": docs_by_session.get(sid, []),
                "updated_at": r["updated_at"]
            }

        return sessions


def create_session(user_id: int, title: str = "New Chat") -> str:
    """Generate a new session ID for a user and save it to SQLite."""
    session_id = str(uuid.uuid4())
    now = str(datetime.now())
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO sessions (id, user_id, title, created_at, updated_at) VALUES (%s, %s, %s, %s, %s)",
            (session_id, user_id, title, now, now)
        )
        conn.commit()
    return session_id


def get_session_messages(session_id: str) -> List[Dict[str, str]]:
    """Get message history for one specific session from SQLite.

    Assistant messages that were answered with retrieved context carry a
    `sources` list (filename/page/etc.) alongside their content, so the chat UI
    can show source attribution again after a reload.
    """
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT role, content, sources, recommendation FROM messages WHERE session_id = %s ORDER BY id ASC",
            (session_id,)
        )
        messages = []
        for r in cur.fetchall():
            role = r["role"]
            content = r["content"]
            if role == "quiz":
                try:
                    content = json.loads(content)
                except Exception:
                    pass
            msg = {"role": role, "content": content}
            if r["sources"]:
                try:
                    msg["sources"] = json.loads(r["sources"])
                except Exception:
                    pass
            if r["recommendation"]:
                try:
                    msg["recommendation"] = json.loads(r["recommendation"])
                except Exception:
                    pass
            messages.append(msg)
        return messages


def add_message(session_id: str, role: str, content, sources: Optional[list] = None,
                recommendation: Optional[dict] = None):
    """Append a message to a session in SQLite and update the session timestamp.

    If content is a dict (e.g. a quiz), it is auto-serialized to JSON.
    `sources` (the CRAG sources_metadata list) is stored alongside assistant
    messages so source attribution survives a reload.
    """
    if isinstance(content, dict):
        content = json.dumps(content)
    sources_json = json.dumps(sources) if sources else None
    recommendation_json = json.dumps(recommendation) if recommendation else None
    now = str(datetime.now())
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO messages (session_id, role, content, sources, recommendation) "
            "VALUES (%s, %s, %s, %s, %s)",
            (session_id, role, content, sources_json, recommendation_json)
        )
        cur.execute(
            "UPDATE sessions SET updated_at = %s WHERE id = %s",
            (now, session_id)
        )
        conn.commit()


def update_session_title(session_id: str, new_title: str):
    """Rename a session in SQLite."""
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE sessions SET title = %s WHERE id = %s",
            (new_title, session_id)
        )
        conn.commit()


def delete_session(session_id: str):
    """Delete a chat session entirely from SQLite, including its isolated FAISS database."""
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM sessions WHERE id = %s", (session_id,))
        conn.commit()

    # Attempt to remove the FAISS vector database. Cleanup failure must not
    # surface as an error: the session row is already gone.
    try:
        delete_vectorstore(session_id)
    except Exception as e:
        print(f"Error removing db folder: {e}")


def save_quiz(session_id: str, quiz: dict):
    """Persist the generated quiz inside the session in SQLite so it survives navigation."""
    quiz_str = json.dumps(quiz)
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE sessions SET quiz_json = %s WHERE id = %s",
            (quiz_str, session_id)
        )
        conn.commit()


def get_quiz(session_id: str) -> dict:
    """Retrieve the saved quiz for a session from SQLite, or empty if none."""
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT quiz_json FROM sessions WHERE id = %s", (session_id,))
        row = cur.fetchone()
        if row and row["quiz_json"]:
            try:
                return json.loads(row["quiz_json"])
            except Exception:
                return {}
        return {}
