import difflib
import json
import random
from langchain_core.prompts import PromptTemplate
from src.core.llm import llm_creative
from langchain_core.output_parsers import JsonOutputParser
from pydantic import BaseModel, Field
from typing import List, Optional
from src.core.database import get_db
from src.personalization import topic_graph
from src.rag.embedder import load_existing_vectorstore

class QuizQuestion(BaseModel):
    subject: str = Field(description="The broad subject this question belongs to.")
    topic: str = Field(description="A broad topic area (1-3 words) from a short, reusable list "
                                    "(at most 10-15 per subject) — NOT a narrow, question-specific concept.")
    question: str = Field(description="The question text")
    options: List[str] = Field(description="Exactly 4 options for the question")
    correct_index: int = Field(description="Index of the correct option (0 to 3)")
    explanation: str = Field(description="Detailed explanation of why the answer is correct and others are wrong")

class Quiz(BaseModel):
    questions: List[QuizQuestion] = Field(description="List of 6 relevant questions based on chat history")


def _graph_node_lists(user_subjects: Optional[List[str]]) -> dict:
    """{subject: [node names]} for whichever of the user's subjects already
    have a seeded curriculum graph (topic_graph_seed.py) — empty for subjects
    with no graph yet, so callers degrade gracefully instead of erroring."""
    if not user_subjects:
        return {}
    lists = {}
    for s in user_subjects:
        nodes = topic_graph.get_subject_graph(s)["nodes"]
        if nodes:
            lists[s] = nodes
    return lists


def _build_topic_constraint(node_lists: dict) -> str:
    """Prompt section telling the model to pick 'topic' only from a subject's
    graph node list, when one exists — this is what makes a quiz-graded topic
    land on the SAME name topic_edges already uses, so mastery.py's
    review-queue/root-cause-gap logic can match them by plain string equality
    instead of needing fuzzy matching."""
    if not node_lists:
        return ""
    lines = ["TOPIC FIELD CONSTRAINT (overrides RULE 3 for these subjects):"]
    for subject, nodes in node_lists.items():
        node_list_str = ", ".join(f'"{n}"' for n in nodes)
        lines.append(f'- If a question\'s "subject" is "{subject}", its "topic" MUST be EXACTLY one of: {node_list_str}.')
    lines.append("For any other subject not listed above, follow RULE 3 as normal (broad, reused topics).")
    return "\n".join(lines)


def _canonicalize_topics(quiz: dict, node_lists: dict) -> dict:
    """Safety net, not the primary mechanism: the prompt constraint above
    should already make the model output an exact node name, but LLMs aren't
    perfectly reliable at hard constraints — snap a near-miss (typo, case,
    minor rewording) onto the closest real node rather than silently leaving
    a mismatched topic that'll never line up with the graph. Left alone
    (no match close enough) rather than forced, since a wrong snap is worse
    than an uncanonicalized topic."""
    if not quiz or not quiz.get("questions") or not node_lists:
        return quiz
    for q in quiz["questions"]:
        nodes = node_lists.get(q.get("subject", ""))
        if not nodes or q.get("topic") in nodes:
            continue
        match = difflib.get_close_matches(q.get("topic", ""), nodes, n=1, cutoff=0.6)
        if match:
            q["topic"] = match[0]
    return quiz


def generate_quiz_for_session_db(session_id: str, user_subjects: Optional[List[str]] = None) -> dict:
    """Generates a JSON-structured quiz drawing directly from the session's uploaded chunks."""
    if not load_existing_vectorstore(session_id):
        return {"questions": []}

    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT content FROM document_chunks WHERE session_id = %s", (session_id,))
        rows = cur.fetchall()

    if not rows:
        return {"questions": []}

    sample_size = min(10, len(rows))
    sampled_rows = random.sample(rows, sample_size)
    text_corpus = "\n\n---\n\n".join([r["content"] for r in sampled_rows])
    
    # Build subject constraint section
    if user_subjects and len(user_subjects) > 0:
        subject_list = ", ".join(f'"{s}"' for s in user_subjects)
        subject_instruction = f"""CRITICAL SUBJECT CONSTRAINT:
The student is ONLY studying these subjects: {subject_list}.
You MUST assign every question's 'subject' field to one of these EXACT names (case-sensitive).
Do NOT invent or use any other subject name whatsoever."""
    else:
        subject_instruction = """CRITICAL INSTRUCTION FOR CATEGORIZATION:
When generating the 'subject' field, use a broadly recognized CS subject (e.g., "Cyber Security", "Data Structures", "Machine Learning", "Operating Systems", "Computer Networks").
Then specify the precise sub-topic in the 'topic' field."""

    model = llm_creative
    parser = JsonOutputParser(pydantic_object=Quiz)

    if user_subjects and len(user_subjects) > 0:
        subject_list = ", ".join(f'"{s}"' for s in user_subjects)
        subject_label_rule = f"""SUBJECT LABELLING RULE (for the 'subject' field ONLY):
After writing each question from the textbook content, assign the 'subject' field to whichever of these matches best: {subject_list}.
This is ONLY a label — it does NOT affect what the question is about. The question content must still come entirely from the textbook excerpts above."""
    else:
        subject_label_rule = """SUBJECT LABELLING RULE (for the 'subject' field ONLY):
Assign a broad CS subject label (e.g., "Cyber Security", "Machine Learning", "Data Structures") to each question based on what the textbook content is about."""

    # Constrain 'topic' to the subject's curriculum graph, when one's been
    # seeded (topic_graph_seed.py) — see _build_topic_constraint's docstring
    # for why this matters (it's what lets mastery.py match a quiz topic
    # against a graph node by plain string equality, no fuzzy matching).
    node_lists = _graph_node_lists(user_subjects)
    topic_constraint = _build_topic_constraint(node_lists)
    rule_3 = topic_constraint if topic_constraint else ""

    prompt = PromptTemplate(
        template="""You are Study AI generating a quiz STRICTLY from the following uploaded textbook content.

RULE 1 — CONTENT SOURCE (most important):
Every single question, option, and answer MUST be based ONLY on the textbook excerpts below.
Do NOT use your general knowledge. Do NOT add information not present in the text.
If the text is about V2X communication, ALL 6 questions must be about V2X communication.

RULE 2 — SUBJECT LABELLING:
{subject_label_rule}

RULE 3 — TOPIC FIELD (keep this BROAD, not per-question):
Before writing questions, first decide on a short list of broad topic areas this content covers —
at most 10-15 for the whole subject, and usually just 2-5 for a single document's worth of content
(e.g. "V2X Architecture", "DSRC Protocol", "Network Security" — NOT narrow one-off concepts like
"DSRC Frequency Band" or "IEEE 802.11p Header Format"). Then assign each question's 'topic' field to
one of those broad topics. Multiple questions should share the same topic where the content overlaps —
do NOT invent a new, more specific topic for every single question.

{rule_3_override}

Generate exactly 6 questions.

Textbook Excerpts:
{text_corpus}

{format_instructions}
Do not include markdown outside the JSON block.""",
        input_variables=["text_corpus", "subject_label_rule", "rule_3_override"],
        partial_variables={"format_instructions": parser.get_format_instructions()},
    )

    chain = prompt | model | parser

    try:
        quiz = chain.invoke({
            "text_corpus": text_corpus,
            "subject_label_rule": subject_label_rule,
            "rule_3_override": rule_3,
        })
        return _canonicalize_topics(quiz, node_lists)
    except Exception as e:
        print(f"Error generating quiz: {e}")
        return {"questions": []}
