"""Learning-guidance advisor — a dedicated pre-processing LLM call, separate
from answer generation.

Given the student's question, their full knowledge profile, and the
prerequisite graph for the subjects they're tracking, it produces a short
plain-text briefing on how deep/paced the eventual answer should be — e.g.
"the student is weak on this topic's prerequisite, slow down and review that
first" or "the student is strong here, be terse and technical".

This is a deliberate extra API call (not folded into the answer-generation
prompt) so the mastery/prerequisite reasoning stays fully separate from, and
inspectable independently of, the final answer — at the cost of one more
sequential call (and its latency) before the chat response starts streaming.

The model is NOT asked to match topic names exactly against the profile or
graph — it's handed both as loosely-worded text and expected to reason past
naming differences itself (e.g. "Newton's 2nd Law" vs. "Newtons Laws Of
Motion"), the same way chain.py's adaptive section already does today.
"""
import json
import re

from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnableLambda
from langchain_groq import ChatGroq

from src.core.config import GROQ_API_KEY
from src.personalization import mastery, topic_graph

# Dedicated instance (not the shared llm_default) with reasoning_effort forced
# to "low". openai/gpt-oss-120b is a reasoning model — its latency scales hard
# with how much internal reasoning a prompt invites, and this multi-step
# "cross-reference profile against graph" prompt was measured taking ~11s at
# the default effort vs. ~0.7s at "low", with no observed drop in the quality
# of its conclusions on the same test cases. This briefing task doesn't need
# deep chain-of-thought, so it's worth capping independently of llm_default —
# which stays untouched since chain.py's answer generation may still benefit
# from its default reasoning depth.
_advisor_llm = ChatGroq(
    model="openai/gpt-oss-120b",
    api_key=GROQ_API_KEY,
    max_retries=0,
    reasoning_effort="low",
)

_ADVISOR_PROMPT = PromptTemplate(
    template="""You are a learning-guidance advisor for a CS tutoring system. You do NOT
answer the student's question — you produce a short briefing that another
model will use to decide how to answer it.

STUDENT QUESTION:
{question}

STUDENT KNOWLEDGE PROFILE (topic names are informal, may not match the graph exactly):
{profile_summary}

SUBJECT PREREQUISITE GRAPH (topic names are broad/canonical, may not match the profile exactly):
{graph_context}

TASK:
1. Identify which profile topic(s) this question is most likely about, even if the wording differs.
2. Check the prerequisite graph for that topic. If a prerequisite exists and the profile shows it's weak
   (or the profile doesn't mention it at all — treat as unproven), flag that explicitly.
3. State in 2-4 short sentences: how proficient the student likely is on this question's topic, whether a
   prerequisite gap should be addressed first, and whether the answer should be foundational/slow-paced or
   terse/advanced.

Return ONLY a JSON object with these keys:
"guidance": the 2-4 sentence briefing described above.
"recommendation": null, or an object with "subject", "target_topic", "graph_prerequisite",
and "profile_prerequisite". Recommend at most one prerequisite. Use the exact subject and topic
spellings shown above. target_topic and graph_prerequisite must name nodes in a prerequisite
path in the graph; profile_prerequisite must name a WEAK topic in the student's profile that
means the same thing as graph_prerequisite. Do not recommend a merely unassessed topic.

If the profile has nothing relevant to this question, or the graph has no data for the relevant subject,
say so briefly in guidance, recommend a normal, unmodified explanation, and set recommendation to null.

Output ONLY valid JSON — no headers, no markdown, no preamble.""",
    input_variables=["question", "profile_summary", "graph_context"],
)


_SUBJECT_LINE = re.compile(r"^\s*Subject:\s*(.+)$", re.MULTILINE)


def _weak_topics_from_summary(profile_summary: str) -> dict[str, dict[str, int]]:
    """Keep the profile's measured weak topics available for graph checks."""
    weak_topics: dict[str, dict[str, int]] = {}
    current_subject = None
    for line in profile_summary.splitlines():
        subject_match = re.match(r"\s*Subject:\s*(.+)$", line)
        if subject_match:
            current_subject = subject_match.group(1).strip().title()
            continue
        weak_match = re.match(r"\s*- Weak \((\d+)%\):\s*(.+)$", line)
        if current_subject and weak_match:
            weak_topics.setdefault(current_subject, {})[
                weak_match.group(2).strip().title()
            ] = int(weak_match.group(1))
    return weak_topics


def _direct_prerequisite_suggestion(question: str, profile_summary: str) -> dict | None:
    """Handle exact question/topic matches even if the advisor omits JSON."""
    question_text = question.casefold()
    for subject, weak_topics in _weak_topics_from_summary(profile_summary).items():
        graph = topic_graph.get_subject_graph(subject)
        targets = sorted(graph["nodes"], key=len, reverse=True)
        for target in targets:
            if not re.search(r"(?<!\w)" + re.escape(target.casefold()) + r"(?!\w)", question_text):
                continue
            for prerequisite in topic_graph.get_prerequisite_chain_from_graph(graph, target):
                if prerequisite in weak_topics:
                    return {
                        "subject": subject,
                        "topic": prerequisite,
                        "score": weak_topics[prerequisite],
                        "for_topic": target,
                    }
    return None


def _fallback_guidance(recommendation: dict) -> str:
    return (
        f"The student is weak in {recommendation['topic']} "
        f"({recommendation['score']}%), a prerequisite of {recommendation['for_topic']}. "
        "Answer the question directly, but explain the needed foundation slowly and clearly."
    )


def _log_advisor_prompt(prompt_value):
    """Debug visibility: print the fully-rendered prompt exactly as it goes to
    the advisor model — this is the "first LLM" call, upstream of chain.py's
    answer-generation prompt (which embeds this call's OUTPUT, not this
    prompt itself, as its "LEARNING GUIDANCE" section)."""
    print("\n" + "=" * 80)
    print("[learning_advisor.py] PROMPT SENT TO ADVISOR MODEL (runs BEFORE the answer-generation call):")
    print("=" * 80)
    print(prompt_value.to_string())
    print("=" * 80 + "\n")
    return prompt_value


def _validate_recommendation(candidate: object, profile_summary: str) -> dict | None:
    """Only surface a measured weak topic on a real prerequisite path."""
    if not isinstance(candidate, dict):
        return None
    subject = str(candidate.get("subject") or "").strip().title()
    target = str(candidate.get("target_topic") or "").strip().title()
    graph_prerequisite = str(candidate.get("graph_prerequisite") or "").strip().title()
    profile_prerequisite = str(candidate.get("profile_prerequisite") or "").strip().title()
    if not all((subject, target, graph_prerequisite, profile_prerequisite)):
        return None

    # The advisor may reason across informal topic names, but the suggested
    # destination must actually be a weak topic recorded for this subject.
    weak_score = _weak_topics_from_summary(profile_summary).get(subject, {}).get(profile_prerequisite)
    if weak_score is None:
        return None

    graph = topic_graph.get_subject_graph(subject)
    if target not in graph["nodes"] or graph_prerequisite not in graph["nodes"]:
        return None
    if graph_prerequisite not in topic_graph.get_prerequisite_chain_from_graph(graph, target):
        return None
    return {
        "subject": subject,
        "topic": profile_prerequisite,
        "score": weak_score,
        "for_topic": target,
    }


def build_learning_guidance_with_recommendation(
    user_id: int, question: str, profile_summary: str = None
) -> tuple[str, dict | None]:
    """Return answer guidance and an optional validated weak prerequisite."""

    if profile_summary is None:
        profile_summary = mastery.build_profile_summary(user_id)
    if not profile_summary:
        return "", None

    # Subject names are parsed out of the summary text itself rather than a
    # second query (mastery.load_global_profile) — build_profile_summary's
    # "  Subject: X" lines already name exactly the subjects we need.
    subjects = _SUBJECT_LINE.findall(profile_summary)
    graph_context = topic_graph.format_graph_context(subjects)
    direct_recommendation = _direct_prerequisite_suggestion(question, profile_summary)

    chain = _ADVISOR_PROMPT | RunnableLambda(_log_advisor_prompt) | _advisor_llm | StrOutputParser()
    try:
        raw = chain.invoke({
            "question": question,
            "profile_summary": profile_summary,
            "graph_context": graph_context or "(no prerequisite graph data for these subjects yet)",
        }).strip()
        # A malformed advisor response must never block the student's answer.
        try:
            json_text = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.IGNORECASE)
            result = json.loads(json_text)
        except (ValueError, TypeError):
            if direct_recommendation:
                return _fallback_guidance(direct_recommendation), direct_recommendation
            return raw, None
        if not isinstance(result, dict):
            if direct_recommendation:
                return _fallback_guidance(direct_recommendation), direct_recommendation
            return "", None
        guidance = result.get("guidance")
        recommendation = _validate_recommendation(
            result.get("recommendation"), profile_summary
        ) if isinstance(guidance, str) and guidance.strip() else None
        if not recommendation and direct_recommendation:
            return _fallback_guidance(direct_recommendation), direct_recommendation
        return (guidance if isinstance(guidance, str) else ""), recommendation
    except Exception as e:
        print(f"[learning_advisor] Guidance generation failed: {e}")
        if direct_recommendation:
            return _fallback_guidance(direct_recommendation), direct_recommendation
        return "", None


def build_learning_guidance(user_id: int, question: str, profile_summary: str = None) -> str:
    """Backward-compatible guidance-only interface."""
    guidance, _ = build_learning_guidance_with_recommendation(
        user_id, question, profile_summary=profile_summary
    )
    return guidance
