"""
Shared LLM singletons — one per temperature config.

LangChain's ChatGroq constructor sets up HTTP sessions, SSL contexts, and
retry configs each time.  By reusing module-level instances we avoid that
overhead on every request (6+ call sites) and let the underlying httpx
client pool connections.
"""

from langchain_groq import ChatGroq

from src.core.config import GROQ_API_KEY

# ── Deterministic (temperature ≈ 0, the default) ──
llm_default = ChatGroq(
    model="openai/gpt-oss-120b",
    api_key=GROQ_API_KEY,
    max_retries=0,
)

# ── Balanced creativity (explanations) ──
llm_balanced = ChatGroq(
    model="openai/gpt-oss-120b",
    api_key=GROQ_API_KEY,
    max_retries=0,
    temperature=0.5,
)

# ── Creative (quizzes — higher variety) ──
llm_creative = ChatGroq(
    model="openai/gpt-oss-120b",
    api_key=GROQ_API_KEY,
    max_retries=0,
    temperature=0.7,
)
