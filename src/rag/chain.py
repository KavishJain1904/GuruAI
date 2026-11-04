from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnableLambda
from src.core.llm import llm_default
from src.rag.crag import build_crag_context           # ← CRAG grading step


def _log_final_prompt(prompt_value):
    """Debug visibility: print the fully-rendered prompt exactly as it goes to
    the answer-generation model — every section (base rules, adaptive-mastery
    rules, and the learning_advisor.py guidance block if present) already
    resolved, plus the actual chat history and CRAG context for this request."""
    print("\n" + "=" * 80)
    print("[chain.py] FINAL PROMPT SENT TO ANSWER-GENERATION MODEL:")
    print("=" * 80)
    print(prompt_value.to_string())
    print("=" * 80 + "\n")
    return prompt_value


def build_rag_chain(retriever, knowledge_profile_summary: str = "", user_memory_context: str = "",
                     learning_guidance: str = "", general_knowledge_mode: bool = False):
    # Same Groq / Llama model as before — only the retrieval step changes.
    model = llm_default

    # ── 1. User Memory ────────────────────────────────────────────────────────
    memory_section = ""
    if user_memory_context:
        memory_section = f"""ABOUT THIS STUDENT (treat as ground truth):
{user_memory_context}

MEMORY APPLICATION RULES — read carefully:
- "likes analogies / simple explanations" → ALWAYS shape your explanation style accordingly
- "likes C++ / Python / any language" → this is a code PREFERENCE, NOT a reason to add code
  ▶ ONLY write code if the user's message explicitly asks for code, implementation, or an example
  ▶ A conceptual question like "explain X" or "what is X" → NO code, ever
- Background facts (year, field) → calibrate depth only
- Questions about own preferences → answer from this memory directly

"""

    # ── 2. Core tutor behaviour ────────────────────────────────────────────────
    source_rule = (
        "Answer from your general knowledge. No documents were uploaded for this session, "
        "so do not imply that your answer came from the student's documents. "
        "If you are unsure about a factual claim, say so."
        if general_knowledge_mode else
        "Use the Textbook Context to gather the facts, but NEVER copy-paste it verbatim — "
        "synthesize it in your own words so the student actually understands it."
    )
    citation_rule = (
        "No uploaded-document sources are available for this answer."
        if general_knowledge_mode else
        "The Textbook Facts below are broken into blocks, each preceded by a "
        "\"[Source: <filename>]\" tag — that's for your own grounding only. "
        "Do NOT mention filenames, pages, \"[Web Search]\"/\"[General knowledge]\" labels, "
        "or a \"Sources Used\" section in your response — sources are shown to the student separately by the UI."
    )
    list_rule = (
        "If the question asks for a list or categories, cover the major relevant points and explain each one."
        if general_knowledge_mode else
        "If the question asks for a list/categories/\"the uses of X\", extract EVERY relevant point "
        "from the context and explain each one conceptually (don't just reproduce the source's own "
        "numbering, and don't compress it into one sentence)."
    )
    base_system = f"""{memory_section}You are Study AI — a sharp, concise CS tutor.
TEACHING RULES:
- {source_rule}
- {list_rule}

RESPONSE LENGTH:
- Simple question → short and crisp. List/enumeration question → full detail regardless of length.
- No filler intros like "Great question!". No code unless explicitly requested.

CITATION RULE:
- {citation_rule}"""

    # ── 3. Adaptive depth ─────────────────────────────────────────────────────
    # Mutually exclusive, not additive: when learning_advisor.py's dedicated
    # call already reasoned over the profile + prerequisite graph, its
    # conclusion IS the adaptation instruction — repeating the full raw-profile
    # rules on top would just have this model redo the same reasoning it was
    # explicitly told it didn't need to (openai/gpt-oss-120b's latency scales
    # with how much reasoning a prompt invites, so that redundancy isn't free).
    # The raw-profile fallback only kicks in when the advisor was skipped
    # (brand-new user, no quiz history) or its call failed.
    adaptive_section = ""
    if learning_guidance:
        adaptive_section = f"""

LEARNING GUIDANCE (from a dedicated mastery + prerequisite analysis — treat as authoritative):
{learning_guidance}
Follow this for depth, tone, and pacing."""
    elif knowledge_profile_summary:
        adaptive_section = f"""

STUDENT KNOWLEDGE PROFILE:
{knowledge_profile_summary}

ADAPTATION RULE: cross-reference the question's topic with the profile above.
Weak (<50%) → simple, analogy-driven, step-by-step, no jargon. Strong (>75%) → terse, technical, no analogies.
Average (50-75%) or topic not found → normal balanced answer, no special tag."""

    system_prompt = base_system + adaptive_section

    human_prompt = (
        "Student Question: {question}\nYour Explanation:"
        if general_knowledge_mode else
        "Use the following textbook facts as your ground-truth to teach the student.\n\n"
        "Textbook Facts (Corrective RAG — only relevant documents kept):\n{context}\n\n"
        "Student Question: {question}\nYour Explanation:"
    )
    prompt = ChatPromptTemplate.from_messages([
        ("system", system_prompt),
        MessagesPlaceholder(variable_name="chat_history"),
        ("human", human_prompt)
    ])

    # ── 4. CRAG-aware chain ────────────────────────────────────────────────────
    # build_crag_context now returns (context_str, source_label, sources_metadata).
    # The chain only needs the context string [0]; sources_metadata is collected
    # separately in server.py (before streaming) and sent as a final SSE event.
    chain = (
        {
            "context": lambda x: x.get("context", ""),
            "question": lambda x: x["question"],
            "chat_history": lambda x: x["chat_history"],
        }
        | prompt
        | RunnableLambda(_log_final_prompt)
        | model
        | StrOutputParser()
    )
    return chain
