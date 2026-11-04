"""Populates topic_edges for a subject the first time it's needed.

Two tiers, checked in order:
  1. CURATED_SEEDS — a small, hand-reviewed set of common subjects (source='seed').
  2. LLM generation — one Groq call producing a broad topic list + prerequisite
     edges for anything not curated (source='llm'), validated before insert.

Idempotent: seed_subject_graph() is a no-op if the subject already has edges,
so it's safe to call on every subject creation without re-seeding or
re-billing an LLM call for subjects other users already triggered.
"""
from collections import defaultdict, deque
from typing import Dict, List, Optional, Tuple

from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from pydantic import BaseModel, Field

from src.core.llm import llm_default
from src.personalization import topic_graph

# Hard bounds on LLM-generated graphs — keeps a bad/rambling generation from
# becoming a permanent, shared, oversized graph everyone else inherits.
_MIN_TOPICS = 5
_MAX_TOPICS = 20


# ── Tier 1: curated seeds (source='seed') ────────────────────────────────────
# Keys are the same .strip().title() normalization mastery.py/topic_graph.py use.
# Each value is a list of (prerequisite, dependent) edges — kept as a DAG.

CURATED_SEEDS: Dict[str, List[Tuple[str, str]]] = {
    # Keys match the CS subject vocabulary quiz.py already uses as examples
    # (see generate_quiz_for_session_db's subject_instruction), since that's
    # the same free-text a user types into POST /api/subjects.
    "Data Structures": [
        ("Complexity Analysis", "Arrays And Strings"),
        ("Arrays And Strings", "Linked Lists"),
        ("Linked Lists", "Stacks And Queues"),
        ("Arrays And Strings", "Recursion"),
        ("Recursion", "Trees"),
        ("Trees", "Binary Search Trees"),
        ("Trees", "Heaps"),
        ("Arrays And Strings", "Hashing"),
        ("Trees", "Graphs"),
        ("Arrays And Strings", "Sorting Algorithms"),
        ("Sorting Algorithms", "Searching Algorithms"),
        ("Recursion", "Dynamic Programming"),
        ("Graphs", "Dynamic Programming"),
        ("Sorting Algorithms", "Greedy Algorithms"),
        ("Heaps", "Greedy Algorithms"),
    ],
    "Operating Systems": [
        ("Introduction To Operating Systems", "Processes And Threads"),
        ("Processes And Threads", "CPU Scheduling"),
        ("Processes And Threads", "Process Synchronization"),
        ("Process Synchronization", "Deadlocks"),
        ("Introduction To Operating Systems", "Memory Management"),
        ("Memory Management", "Virtual Memory"),
        ("Introduction To Operating Systems", "File Systems"),
        ("Introduction To Operating Systems", "Input Output Systems"),
        ("Process Synchronization", "Concurrency And Multithreading"),
        ("CPU Scheduling", "Distributed Systems Basics"),
        ("Virtual Memory", "Distributed Systems Basics"),
    ],
    "Computer Networks": [
        ("Network Fundamentals", "Osi And Tcp-Ip Models"),
        ("Osi And Tcp-Ip Models", "Physical And Data Link Layer"),
        ("Osi And Tcp-Ip Models", "Network Layer And Routing"),
        ("Network Layer And Routing", "Network Addressing"),
        ("Osi And Tcp-Ip Models", "Transport Layer Protocols"),
        ("Transport Layer Protocols", "Application Layer Protocols"),
        ("Physical And Data Link Layer", "Wireless Networks"),
        ("Network Layer And Routing", "Network Security Basics"),
        ("Transport Layer Protocols", "Network Security Basics"),
        ("Transport Layer Protocols", "Network Performance And Qos"),
    ],
    "Database Management": [
        ("Database Fundamentals", "Er Modeling"),
        ("Er Modeling", "Relational Model"),
        ("Relational Model", "Sql Basics"),
        ("Sql Basics", "Advanced Sql"),
        ("Relational Model", "Normalization"),
        ("Relational Model", "Transactions And Concurrency Control"),
        ("Advanced Sql", "Indexing And Query Optimization"),
        ("Transactions And Concurrency Control", "Indexing And Query Optimization"),
        ("Database Fundamentals", "Nosql Databases"),
        ("Transactions And Concurrency Control", "Database Security"),
    ],
}


def apply_curated_graph_corrections() -> None:
    """Repair known gaps in already-seeded graphs without replacing user data.

    Existing users may have either "Operating System" or "Operating Systems"
    as their subject name. Some older generated maps omitted the link between
    Scheduling Algorithms and Kernel Design.
    """
    prerequisite = "Scheduling Algorithms"
    target = "Kernel Design"
    for subject in ("Operating System", "Operating Systems"):
        graph = topic_graph.get_subject_graph(subject)
        if prerequisite not in graph["nodes"] or target not in graph["nodes"]:
            continue
        if prerequisite in topic_graph.get_prerequisite_chain_from_graph(graph, target):
            continue
        # Never introduce a cycle into a graph that may have been LLM-generated.
        if target in topic_graph.get_prerequisite_chain_from_graph(graph, prerequisite):
            print(f"[topic_graph_seed] Skipped {subject} correction: would create a cycle")
            continue
        topic_graph.add_edge(subject, prerequisite, target, source="seed")


# ── Tier 2: LLM generation (source='llm') ────────────────────────────────────

class _TopicNode(BaseModel):
    topic: str = Field(description="A broad topic name, 1-4 words.")
    prerequisites: List[str] = Field(
        default_factory=list,
        description="Names of other topics IN THIS SAME LIST that must be learned "
                    "first. Empty list if this is a foundational/starting topic."
    )


class _SubjectCurriculum(BaseModel):
    topics: List[_TopicNode] = Field(
        description=f"Between {_MIN_TOPICS} and {_MAX_TOPICS} broad topics covering "
                    "this subject end to end, ordered roughly foundational-to-advanced."
    )


_CURRICULUM_PROMPT = PromptTemplate(
    template="""You are designing a curriculum map for the subject "{subject}".

List the broad topic areas a student needs to cover, from foundational to advanced.
- Use BROAD topics (1-4 words each), not narrow sub-concepts — think chapter titles,
  not individual facts.
- Produce between {min_topics} and {max_topics} topics total.
- For each topic, list which OTHER topics from your own list are prerequisites for it.
  Leave this empty for topics that need no prior topic from the list.
- Do not create a prerequisite cycle (topic A requiring B which requires A).

{format_instructions}
Do not include markdown outside the JSON block.""",
    input_variables=["subject"],
    partial_variables={
        "min_topics": str(_MIN_TOPICS),
        "max_topics": str(_MAX_TOPICS),
    },
)


def _is_dag(nodes: List[str], edges: List[Tuple[str, str]]) -> bool:
    """Kahn's algorithm: true iff `edges` (from -> to) form no cycle over `nodes`."""
    indegree = {n: 0 for n in nodes}
    adjacency = defaultdict(list)
    for src, dst in edges:
        adjacency[src].append(dst)
        indegree[dst] += 1

    queue = deque(n for n in nodes if indegree[n] == 0)
    visited = 0
    while queue:
        n = queue.popleft()
        visited += 1
        for m in adjacency[n]:
            indegree[m] -= 1
            if indegree[m] == 0:
                queue.append(m)
    return visited == len(nodes)


def _generate_llm_graph(subject: str) -> Optional[List[Tuple[str, str]]]:
    """One Groq call producing a validated (prerequisite, dependent) edge list,
    or None if the model's output fails validation (subject is left unseeded
    and will simply be retried on its next creation)."""
    parser = JsonOutputParser(pydantic_object=_SubjectCurriculum)
    chain = _CURRICULUM_PROMPT.partial(
        format_instructions=parser.get_format_instructions()
    ) | llm_default | parser

    try:
        result = chain.invoke({"subject": subject})
    except Exception as e:
        print(f"[topic_graph_seed] LLM curriculum generation failed for {subject!r}: {e}")
        return None

    topics = result.get("topics") or []
    if not (_MIN_TOPICS <= len(topics) <= _MAX_TOPICS):
        print(f"[topic_graph_seed] Rejecting curriculum for {subject!r}: "
              f"{len(topics)} topics (expected {_MIN_TOPICS}-{_MAX_TOPICS}).")
        return None

    names = [t["topic"].strip().title() for t in topics if t.get("topic", "").strip()]
    if len(names) != len(set(names)):
        print(f"[topic_graph_seed] Rejecting curriculum for {subject!r}: duplicate topic names.")
        return None
    name_set = set(names)

    edges: List[Tuple[str, str]] = []
    for t in topics:
        to_topic = t["topic"].strip().title()
        for prereq in t.get("prerequisites") or []:
            from_topic = prereq.strip().title()
            # Silently drop a prerequisite that doesn't name another topic in
            # the same list, rather than rejecting the whole generation over it.
            if from_topic in name_set and from_topic != to_topic:
                edges.append((from_topic, to_topic))

    if not _is_dag(names, edges):
        print(f"[topic_graph_seed] Rejecting curriculum for {subject!r}: prerequisite cycle detected.")
        return None

    return edges


# ── Entry point ───────────────────────────────────────────────────────────────

def seed_subject_graph(subject: str) -> None:
    """Populate topic_edges for `subject` if it has none yet. Safe to call on
    every subject creation — idempotent, and cheap (one indexed lookup) on the
    common case where the subject is already seeded."""
    if topic_graph.has_edges(subject):
        return

    subj = subject.strip().title()
    if subj in CURATED_SEEDS:
        edges = CURATED_SEEDS[subj]
        source = "seed"
    else:
        edges = _generate_llm_graph(subj)
        source = "llm"
        if edges is None:
            return

    for from_topic, to_topic in edges:
        topic_graph.add_edge(subj, from_topic, to_topic, source=source)

    print(f"[topic_graph_seed] Seeded {len(edges)} edge(s) for subject={subj!r} (source={source}).")
