"""
User Memory — persistent cross-session preferences and facts about the student, stored in SQLite.

Two responsibilities:
1. Storage + LLM extraction of user preferences (injected into all study sessions)
2. Conversational memory chat — a dedicated LLM chat that learns about the user
   and responds warmly while silently extracting and persisting preferences.
"""

import os
import json
from langchain_core.prompts import PromptTemplate, ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser, StrOutputParser
from langchain_core.messages import HumanMessage, AIMessage
from pydantic import BaseModel, Field
from typing import List
from src.core.llm import llm_default
from src.core.database import get_db

# ── Storage ──

def load_memory(user_id: int) -> list[str]:
    """Load the preferences/memories list for a user from SQLite."""
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT memory_item FROM user_memories WHERE user_id = %s ORDER BY id ASC", 
            (user_id,)
        )
        return [r["memory_item"] for r in cur.fetchall()]

def delete_memory_item(user_id: int, index: int) -> list[str]:
    """Delete a preference item by its positional index (0-based)."""
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT id FROM user_memories WHERE user_id = %s ORDER BY id ASC LIMIT 1 OFFSET %s",
            (user_id, index)
        )
        row = cur.fetchone()
        if row:
            cur.execute("DELETE FROM user_memories WHERE id = %s", (row["id"],))
            conn.commit()
    return load_memory(user_id)

def add_memory_items(user_id: int, new_items: list[str]) -> list[str]:
    """Add new preferences to SQLite, skipping duplicates."""
    clean = [(user_id, item.strip()) for item in new_items if item and item.strip()]
    if clean:
        with get_db() as conn:
            cur = conn.cursor()
            cur.executemany(
                "INSERT INTO user_memories (user_id, memory_item) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                clean
            )
            conn.commit()
    return load_memory(user_id)

def clear_all_memory(user_id: int):
    """Wipe all stored preferences for a user in SQLite."""
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM user_memories WHERE user_id = %s", (user_id,))
        conn.commit()

# ── User Profile ──

def load_user_profile(user_id: int) -> dict:
    """Return the user's display name and bio from the users table in SQLite."""
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT name, bio FROM users WHERE id = %s", (user_id,))
        row = cur.fetchone()
        if row:
            return {"name": row["name"] or "The Scholar", "bio": row["bio"] or ""}
        return {"name": "The Scholar", "bio": ""}

def save_user_profile(user_id: int, name: str, bio: str) -> dict:
    """Persist the user's display name and bio in SQLite."""
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE users SET name = %s, bio = %s WHERE id = %s",
            (name.strip(), bio.strip(), user_id)
        )
        conn.commit()
    return {"name": name.strip(), "bio": bio.strip()}

# ── Memory Chat History ──

def get_chat_history(user_id: int) -> list[dict]:
    """Retrieve memory chatbot history for a user from SQLite."""
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT role, content FROM memory_chat_history WHERE user_id = %s ORDER BY id ASC", 
            (user_id,)
        )
        return [{"role": r["role"], "content": r["content"]} for r in cur.fetchall()]

def append_chat_message(user_id: int, role: str, content: str):
    """Append a memory chat message to SQLite."""
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO memory_chat_history (user_id, role, content) VALUES (%s, %s, %s)",
            (user_id, role, content)
        )
        conn.commit()

# ── LLM Extraction ──

class ExtractedPreferences(BaseModel):
    preferences: List[str] = Field(
        description="List of concise preference/fact statements about the user, max 12 words each."
    )

EXTRACT_PROMPT = PromptTemplate(
    template="""You are a user-preference extraction system for a CS tutoring AI.

Extract any persistent preferences, learning styles, technical choices, or personal facts
from the student's message that would help a tutor serve them better.

Rules:
- Each item: concise statement starting with "User" (max 12 words)
  e.g. "User prefers Python for all code examples"
  e.g. "User is a 3rd year Computer Science student"
- Only extract meaningful, actionable, persistent preferences
- Return empty list if nothing extractable
- Do NOT duplicate already stored preferences

Already stored:
{existing}

Student's message: "{message}"

{format_instructions}""",
    input_variables=["message", "existing"],
    partial_variables={},
)

def extract_preferences_from_message(user_id: int, message: str) -> list[str]:
    """Query Groq LLM to extract user preferences from text and return them."""
    model = llm_default
    parser = JsonOutputParser(pydantic_object=ExtractedPreferences)
    prompt = EXTRACT_PROMPT.partial(format_instructions=parser.get_format_instructions())
    chain = prompt | model | parser
    existing = load_memory(user_id)
    existing_str = "\n".join(f"- {i}" for i in existing) if existing else "None"
    try:
        result = chain.invoke({"message": message, "existing": existing_str})
        return result.get("preferences", [])
    except Exception as e:
        print(f"Memory extraction error: {e}")
        return []

# ── Conversational Memory Chat ──

MEMORY_CHAT_SYSTEM = """You are the student's personal Study Companion — a warm, friendly AI whose only job in this chat is to learn about the student and remember their preferences.

Your role here:
- Have a natural, friendly conversation to understand the student's preferences, background, and learning style
- When the student shares preferences (e.g. "I like Python", "explain with analogies"), warmly acknowledge them and confirm you'll remember
- Keep responses SHORT (2-4 sentences max) — this is a quick preference-setting chat, not a tutoring session
- If the student asks an academic question, politely redirect: "I'll note that! For actual study help, head to a Study Session — I'll apply your preferences there."
- Do not give long explanations or teach here

Current stored preferences (for your awareness, don't re-ask for these):
{stored_preferences}

Be warm, brief, and confirmatory."""

def memory_chat(user_id: int, user_message: str) -> tuple[str, list[str]]:
    """
    Send a message to the memory chat LLM. Returns (bot_reply, newly_extracted_items).
    Also persists the conversation and any extracted preferences in SQLite.
    """
    # 1. Get history and save current message
    history = get_chat_history(user_id)
    append_chat_message(user_id, "user", user_message)

    # 2. Build formatted history for LLM
    formatted_history = []
    for h in history:
        if h["role"] == "user":
            formatted_history.append(HumanMessage(content=h["content"]))
        else:
            formatted_history.append(AIMessage(content=h["content"]))

    stored = load_memory(user_id)
    stored_str = "\n".join(f"- {i}" for i in stored) if stored else "None yet"

    # 3. Call LLM for conversational response
    model = llm_default
    prompt = ChatPromptTemplate.from_messages([
        ("system", MEMORY_CHAT_SYSTEM),
        *[(("human" if m.type == "human" else "ai"), m.content) for m in formatted_history],
        ("human", "{message}"),
    ])
    chain = prompt | model | StrOutputParser()
    reply = chain.invoke({"stored_preferences": stored_str, "message": user_message})

    # 4. Persist bot reply
    append_chat_message(user_id, "assistant", reply)

    # 5. Extract preferences silently
    extracted = extract_preferences_from_message(user_id, user_message)
    if extracted:
        add_memory_items(user_id, extracted)

    return reply, extracted

# ── System Context for Study Sessions ──

def get_memory_as_system_context(user_id: int) -> str:
    """Load user preferences and format them as system prompt context."""
    items = load_memory(user_id)
    if not items:
        return ""
    lines = "\n".join(f"- {item}" for item in items)
    return f"""PERSISTENT USER PREFERENCES (apply these in every response without being asked):
{lines}"""

# ── Subject Management ──

def load_subjects(user_id: int) -> list[str]:
    """Return the list of subjects the student has registered from SQLite."""
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT subject FROM user_subjects WHERE user_id = %s ORDER BY id ASC", 
            (user_id,)
        )
        return [r["subject"] for r in cur.fetchall()]

def save_subject(user_id: int, subject: str) -> list[str]:
    """Add a subject if not already present in SQLite. Returns updated list."""
    subject_title = subject.strip().title()
    if subject_title:
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO user_subjects (user_id, subject) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (user_id, subject_title)
            )
            conn.commit()
    return load_subjects(user_id)

def delete_subject(user_id: int, subject: str) -> list[str]:
    """Remove a subject by name from SQLite. Returns updated list."""
    subject_title = subject.strip().title()
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM user_subjects WHERE user_id = %s AND subject = %s",
            (user_id, subject_title)
        )
        conn.commit()
    return load_subjects(user_id)
