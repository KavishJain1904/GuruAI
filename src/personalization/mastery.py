"""Topic mastery tracking (EMA) and spaced-repetition scheduling.

"""
import difflib
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional

from src.core.database import get_db
from src.personalization import topic_graph
from src.personalization.spaced_rep import SpacedRepetitionScheduler

# EMA smoothing factor
_EMA_ALPHA = 0.3

# Shared scheduler instance for computing spaced-repetition review dates.
scheduler = SpacedRepetitionScheduler()


@dataclass
class MasteryRecord:
    """A user's mastery record for one (subject, topic) pair, as stored in knowledge_profile."""
    user_id: int
    subject: str
    topic: str
    correct: int = 0
    total: int = 0
    ema_score: Optional[float] = None
    last_reviewed_at: Optional[datetime] = None
    review_interval_days: int = 1
    review_count: int = 0
    next_review_date: Optional[datetime] = None


# ── Global Student Profile / Knowledge Base ──

def load_global_profile(user_id: int) -> Dict:
    """Load the globally aggregated knowledge profile for a user from SQLite."""
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT subject, topic, correct, total, ema_score FROM knowledge_profile WHERE user_id = %s",
            (user_id,)
        )
        profile = {}
        for r in cur.fetchall():
            subj = r["subject"]
            topic = r["topic"]
            if subj not in profile:
                profile[subj] = {}
            profile[subj][topic] = {
                "correct": r["correct"],
                "total": r["total"],
                "ema_score": r["ema_score"]
            }
        return profile


def _record_review(cur, *, topic_id: int, user_id: int, kind: str, score: float,
                   before: float, after: float, interval: int, next_review: datetime,
                   reviewed_at: datetime, session_id: Optional[str] = None,
                   question: Optional[str] = None, selected_answer: Optional[str] = None,
                   correct_answer: Optional[str] = None, notes: Optional[str] = None) -> None:
    """Write the event in the SAME transaction as the mastery/schedule update."""
    cur.execute(
        """INSERT INTO review_events
           (topic_id, user_id, session_id, kind, score, mastery_before, mastery_after,
            review_interval_days, next_review_date, reviewed_at,
            question, selected_answer, correct_answer, notes)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        (topic_id, user_id, session_id, kind, score, before, after, interval,
         next_review, reviewed_at, question, selected_answer, correct_answer, notes),
    )


def update_topic_performance(session_id: Optional[str], subject: str, topic: str,
                             correct: bool, *, user_id: Optional[int] = None,
                             topic_id: Optional[int] = None,
                             question: Optional[str] = None,
                             selected_answer: Optional[str] = None,
                             correct_answer: Optional[str] = None) -> dict:
    """Record a quiz answer, mastery, schedule, and history atomically.

    Session callers retain the existing interface; standalone topic quizzes pass
    the authenticated user_id. Question/answer text is a client-reported snapshot,
    as is correctness in the existing quiz API, not independently verified grading.
    """
    with get_db() as conn:
        cur = conn.cursor()
        if session_id:
            cur.execute("SELECT user_id FROM sessions WHERE id = %s", (session_id,))
            sess_row = cur.fetchone()
            if not sess_row:
                return
            if user_id is not None and user_id != sess_row["user_id"]:
                raise ValueError("Session does not belong to this user")
            user_id = sess_row["user_id"]
        if user_id is None:
            raise ValueError("A session or authenticated user is required")

        if topic_id is not None:
            cur.execute(
                "SELECT id, correct, total, ema_score, review_count, review_success_streak "
                "FROM knowledge_profile WHERE id = %s AND user_id = %s FOR UPDATE",
                (topic_id, user_id),
            )
        else:
            subj = subject.strip().title()
            t = topic.strip().title()
            cur.execute("SELECT topic FROM knowledge_profile WHERE user_id = %s AND subject = %s",
                        (user_id, subj))
            matches = difflib.get_close_matches(t, [r["topic"] for r in cur.fetchall()], n=1, cutoff=0.85)
            if not matches:
                matches = difflib.get_close_matches(
                    t, topic_graph.get_subject_node_names(subj), n=1, cutoff=0.85
                )
            if matches:
                t = matches[0]
            cur.execute(
                "INSERT INTO knowledge_profile (user_id, subject, topic) VALUES (%s, %s, %s) "
                "ON CONFLICT (user_id, subject, topic) DO NOTHING", (user_id, subj, t)
            )
            cur.execute(
                "SELECT id, correct, total, ema_score, review_count, review_success_streak "
                "FROM knowledge_profile WHERE user_id = %s AND subject = %s AND topic = %s FOR UPDATE",
                (user_id, subj, t),
            )
        row = cur.fetchone()
        if not row:
            raise ValueError("Topic does not belong to this user")
        recent = 1.0 if correct else 0.0
        prev = row["ema_score"] if row["ema_score"] is not None else 0.0
        new_ema = recent * _EMA_ALPHA + prev * (1 - _EMA_ALPHA)
        new_review_count = (row["review_count"] or 0) + 1
        now = datetime.now()
        new_streak, next_review = scheduler.schedule_review(
            new_ema, row["review_success_streak"], correct, now
        )
        interval = (next_review - now).days
        cur.execute(
            """UPDATE knowledge_profile SET correct = correct + %s, total = total + 1,
               ema_score = %s, last_reviewed_at = %s, review_interval_days = %s,
               review_count = %s, review_success_streak = %s, next_review_date = %s,
               updated_at = CURRENT_TIMESTAMP WHERE id = %s""",
            (int(correct), new_ema, now, interval, new_review_count, new_streak, next_review, row["id"]),
        )
        _record_review(cur, topic_id=row["id"], user_id=user_id, kind="quiz", score=recent,
                       before=prev, after=new_ema, interval=interval, next_review=next_review,
                       reviewed_at=now, session_id=session_id, question=question,
                       selected_answer=selected_answer, correct_answer=correct_answer)
        conn.commit()
        return {"topic_id": row["id"], "mastery": new_ema, "next_review": next_review.isoformat()}


def get_review_history(user_id: int, limit: int = 20, offset: int = 0,
                       topic_id: Optional[int] = None) -> dict:
    """Newest first, scoped to the authenticated user; no synthetic past events."""
    with get_db() as conn:
        cur = conn.cursor()
        where = "e.user_id = %s"
        params = [user_id]
        if topic_id is not None:
            where += " AND e.topic_id = %s"
            params.append(topic_id)
        cur.execute(
            "SELECT e.*, p.subject, p.topic FROM review_events e "
            "JOIN knowledge_profile p ON p.id = e.topic_id WHERE " + where +
            " ORDER BY e.id DESC LIMIT %s OFFSET %s", (*params, limit + 1, offset)
        )
        rows = cur.fetchall()
    return {"items": rows[:limit], "has_more": len(rows) > limit, "offset": offset}


def get_performance_areas(user_id: int) -> Dict:
    """Returns globally tracked topics for a user classified into weak, average, and strong."""
    profile = load_global_profile(user_id)

    result = {}
    for subj, topics in profile.items():
        weak, average, strong = [], [], []
        for t, stats in topics.items():
            if stats["total"] == 0:
                continue
            score = stats["ema_score"] if stats.get("ema_score") is not None else (stats["correct"] / stats["total"])
            val = (t, score, stats["correct"], stats["total"])
            if scheduler.get_mastery_category(score) == "Weak":
                weak.append(val)
            elif scheduler.get_mastery_category(score) == "Average":
                average.append(val)
            else:
                strong.append(val)

        result[subj] = {
            "weak": sorted(weak, key=lambda x: x[1]),
            "average": sorted(average, key=lambda x: x[1]),
            "strong": sorted(strong, key=lambda x: x[1], reverse=True)
        }

    return result


def get_root_cause_gaps(user_id: int) -> Dict:
    """For each weak topic, check whether any of its prerequisites (per the
    curriculum graph) are also weak or entirely unproven — those are the
    actual root cause, not the topic the student happened to get quizzed on.

    Returns {subject: [{"topic": ..., "score": ..., "blocked_by": [prereq, ...]}]},
    subjects/topics with nothing to flag are simply absent. Additive — doesn't
    change get_performance_areas()'s existing shape, since other code already
    depends on that.
    """
    profile = load_global_profile(user_id)
    result = {}
    for subject, topics in profile.items():
        # One query for the whole subject, reused for every topic in it below —
        # see topic_graph.get_prerequisite_chain_from_graph for why this matters
        # (no DB connection pooling; a per-topic query would be a real network
        # round trip per topic against a remote database).
        graph = topic_graph.get_subject_graph(subject)
        flagged = []
        for topic, stats in topics.items():
            if stats["total"] == 0:
                continue
            score = stats["ema_score"] if stats.get("ema_score") is not None else (
                stats["correct"] / stats["total"]
            )
            if scheduler.get_mastery_category(score) != "Weak":
                continue

            blocked_by = []
            for prereq in topic_graph.get_prerequisite_chain_from_graph(graph, topic):
                prereq_stats = topics.get(prereq)
                if prereq_stats is None:
                    blocked_by.append(prereq)  # never attempted — unproven, treat as a gap
                    continue
                prereq_score = prereq_stats["ema_score"] if prereq_stats.get("ema_score") is not None else (
                    prereq_stats["correct"] / prereq_stats["total"] if prereq_stats["total"] else 0.0
                )
                if scheduler.get_mastery_category(prereq_score) == "Weak":
                    blocked_by.append(prereq)

            if blocked_by:
                flagged.append({"topic": topic, "score": score, "blocked_by": blocked_by})

        if flagged:
            result[subject] = flagged

    return result


def delete_topic(user_id: int, subject: str, topic: str):
    """Remove a topic's score data from the global knowledge profile in SQLite."""
    subj_key = subject.strip().title()
    topic_key = topic.strip().title()
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM knowledge_profile WHERE user_id = %s AND subject = %s AND topic = %s",
            (user_id, subj_key, topic_key)
        )
        conn.commit()


def build_profile_summary(user_id: int) -> str:
    """Serialize the global knowledge profile into a compact text block
    the LLM can read and reason about.
    """
    profile = get_performance_areas(user_id)
    if not profile:
        return ""
    lines = []
    for subject, levels in profile.items():
        subject_lines = []
        for level_name, items in levels.items():
            for item in items:
                topic, score = item[0], item[1]
                pct = round(score * 100)
                subject_lines.append(f"    - {level_name.capitalize()} ({pct}%): {topic}")
        if subject_lines:
            lines.append(f"  Subject: {subject}")
            lines.extend(subject_lines)
    return "\n".join(lines) if lines else ""


# ── Spaced-repetition schedule views ──

def _parse_ts(value) -> Optional[datetime]:
    """Parse a SQLite-stored timestamp string back into a datetime, or None."""
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value)


_TOPIC_COLUMNS = """
    id, subject, topic, correct, total, ema_score,
    last_reviewed_at, review_interval_days, review_count, next_review_date
"""


def _topic_row_to_dict(row) -> dict:
    """Shape a knowledge_profile row into the schedule dict shared by the SRS endpoints."""
    ema_score = row["ema_score"]
    mastery_level = ema_score if ema_score is not None else (
        row["correct"] / row["total"] if row["total"] else 0.0
    )
    last_reviewed_at = _parse_ts(row["last_reviewed_at"])
    next_review_date = _parse_ts(row["next_review_date"])
    days_until_review = (
        (next_review_date.date() - datetime.now().date()).days if next_review_date else 0
    )
    interval_days = row["review_interval_days"] or 1
    urgency_score = round(min(1.0, max(0.0, 1 - (days_until_review / interval_days))), 2)

    return {
        "id": row["id"],
        "subject": row["subject"],
        "topic": row["topic"],
        "mastery_level": mastery_level,
        "mastery_category": scheduler.get_mastery_category(mastery_level),
        "last_reviewed": last_reviewed_at.date().isoformat() if last_reviewed_at else None,
        "next_review": next_review_date.date().isoformat() if next_review_date else None,
        "days_until_review": days_until_review,
        "review_count": row["review_count"] or 0,
        "is_due": scheduler.is_due_for_review(last_reviewed_at, next_review_date),
        "urgency_score": urgency_score,
    }


def list_topics_with_schedule(user_id: int) -> List[dict]:
    """Return every tracked topic for a user with its spaced-repetition schedule info."""
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            f"SELECT {_TOPIC_COLUMNS} FROM knowledge_profile WHERE user_id = %s",
            (user_id,)
        )
        rows = cur.fetchall()
    return [_topic_row_to_dict(row) for row in rows]


def get_topic_by_id(topic_id: int, user_id: int) -> Optional[dict]:
    """Fetch a single topic's schedule info, scoped to its owning user."""
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            f"SELECT {_TOPIC_COLUMNS} FROM knowledge_profile WHERE id = %s AND user_id = %s",
            (topic_id, user_id)
        )
        row = cur.fetchone()
    return _topic_row_to_dict(row) if row else None


def update_ema(topic_id: int, user_id: int, score: float, notes: Optional[str] = None) -> Optional[dict]:
    """Record a manual review score (0.0-1.0) for a topic and advance its review schedule.

    Smooth the normalized self-rating into mastery without changing quiz totals.
    Quiz correctness remains evidence from quiz answers only.
    Returns the updated topic dict, or None if no such topic exists for this user.
    """
    with get_db() as conn:
        cur = conn.cursor()
        # FOR UPDATE locks this row so a concurrent update to the same topic can't
        # read the same stale values and clobber this one (see update_topic_performance).
        cur.execute(
            "SELECT correct, total, ema_score, review_count, review_success_streak FROM knowledge_profile "
            "WHERE id = %s AND user_id = %s FOR UPDATE",
            (topic_id, user_id)
        )
        row = cur.fetchone()
        if not row:
            return None

        prev_ema = row["ema_score"] if row["ema_score"] is not None else 0.0
        new_ema = (score * _EMA_ALPHA) + (prev_ema * (1 - _EMA_ALPHA))
        new_review_count = (row["review_count"] or 0) + 1

        now = datetime.now()
        new_streak, next_review_date = scheduler.schedule_review(
            new_ema, row["review_success_streak"], score >= 0.5, now
        )
        review_interval_days = (next_review_date - now).days

        cur.execute(
            """
            UPDATE knowledge_profile
            SET ema_score = %s, last_reviewed_at = %s,
                review_interval_days = %s, review_count = %s, review_success_streak = %s, next_review_date = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s AND user_id = %s
            """,
            (
                new_ema, now,
                review_interval_days, new_review_count, new_streak, next_review_date,
                topic_id, user_id
            )
        )
        _record_review(cur, topic_id=topic_id, user_id=user_id, kind="self_rating", score=score,
                       before=prev_ema, after=new_ema, interval=review_interval_days,
                       next_review=next_review_date, reviewed_at=now, notes=notes)
        conn.commit()

    return get_topic_by_id(topic_id, user_id)


def build_review_queue(user_id: int, category: str = "all", limit: int = 10, sort: str = "urgent") -> dict:
    """Return topics due for review today or earlier, filtered and sorted.

    category filters by mastery_category ('weak'/'average'/'strong'), sort picks
    between soonest-due-first ('urgent') and most-recently-studied-first ('recent').
    """
    topics = list_topics_with_schedule(user_id)
    due_topics = [t for t in topics if t["is_due"]]

    if category != "all":
        due_topics = [t for t in due_topics if t["mastery_category"].lower() == category]

    if sort == "urgent":
        due_topics.sort(key=lambda t: t["days_until_review"])
    else:
        due_topics.sort(key=lambda t: t["last_reviewed"] or "", reverse=True)

    # Bump a still-weak prerequisite ahead of the (already-due, already-weak)
    # topic it blocks, within the ordering above — see topic_graph.py.
    due_topics = topic_graph.prioritize_prerequisites(due_topics)

    overdue_count = sum(1 for t in topics if t["days_until_review"] < 0)

    queue = [
        {
            "id": t["id"],
            "subject": t["subject"],
            "topic": t["topic"],
            "mastery_level": t["mastery_level"],
            "mastery_category": t["mastery_category"],
            "days_until_review": t["days_until_review"],
            "last_reviewed": t["last_reviewed"],
            "next_review": t["next_review"],
            "review_count": t["review_count"],
            "urgency_score": t["urgency_score"],
        }
        for t in due_topics[:limit]
    ]

    return {
        "queue": queue,
        "total_topics": len(topics),
        "overdue_count": overdue_count,
    }


def get_topic_statistics(user_id: int) -> dict:
    """Return dashboard-level stats summarizing a user's spaced-repetition progress."""
    topics = list_topics_with_schedule(user_id)
    if not topics:
        return {
            "total_topics": 0,
            "topics_due": 0,
            "topics_overdue": 0,
            "avg_mastery": 0.0,
            "strongest_topic": None,
            "strongest_subject": None,
            "strongest_mastery": None,
            "weakest_topic": None,
            "weakest_subject": None,
            "weakest_mastery": None,
        }

    topics_due = sum(1 for t in topics if t["is_due"])
    topics_overdue = sum(1 for t in topics if t["days_until_review"] < 0)
    avg_mastery = round(sum(t["mastery_level"] for t in topics) / len(topics), 3)
    strongest = max(topics, key=lambda t: t["mastery_level"])
    weakest = min(topics, key=lambda t: t["mastery_level"])

    return {
        "total_topics": len(topics),
        "topics_due": topics_due,
        "topics_overdue": topics_overdue,
        "avg_mastery": avg_mastery,
        "strongest_topic": strongest["topic"],
        "strongest_subject": strongest["subject"],
        "strongest_mastery": strongest["mastery_level"],
        "weakest_topic": weakest["topic"],
        "weakest_subject": weakest["subject"],
        "weakest_mastery": weakest["mastery_level"],
    }


def get_user_stats(user_id: int) -> dict:
    """Aggregate totals for the user dashboard.

    total_questions: quiz questions answered across all sessions.
    average_mastery_pct: mean EMA score (0-100) across all unique topics.
    """
    global_profile = load_global_profile(user_id)
    total_questions = 0
    all_ema_scores = []

    for subj_topics in global_profile.values():
        for stats in subj_topics.values():
            total_questions += stats.get("total", 0)
            score = stats.get("ema_score")
            if score is not None:
                all_ema_scores.append(score)

    avg_mastery = round((sum(all_ema_scores) / len(all_ema_scores)) * 100, 1) if all_ema_scores else 0.0

    return {
        "total_questions": total_questions,
        "average_mastery_pct": avg_mastery,
    }


def get_review_schedule(topic: str, user_id: int) -> dict:
    """Return the spaced-repetition review schedule for a topic across all subjects.

    Backward compatible: topics that predate spaced repetition (no reviews yet)
    are reported as due today with a review_count of 0.
    """
    topic_key = topic.strip().title()
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT subject, topic, ema_score, correct, total, last_reviewed_at,
                   review_interval_days, review_count, next_review_date
            FROM knowledge_profile
            WHERE user_id = %s AND topic = %s
            """,
            (user_id, topic_key)
        )
        row = cur.fetchone()

    if not row:
        return {}

    ema_score = row["ema_score"]
    mastery_level = ema_score if ema_score is not None else (
        row["correct"] / row["total"] if row["total"] else 0.0
    )
    last_reviewed_at = _parse_ts(row["last_reviewed_at"])
    next_review_date = _parse_ts(row["next_review_date"])
    days_until_review = (next_review_date.date() - datetime.now().date()).days if next_review_date else 0

    return {
        "topic": row["topic"],
        "mastery_level": mastery_level,
        "mastery_category": scheduler.get_mastery_category(mastery_level),
        "last_reviewed": last_reviewed_at.date().isoformat() if last_reviewed_at else None,
        "next_review": next_review_date.date().isoformat() if next_review_date else None,
        "days_until_review": days_until_review,
        "review_count": row["review_count"] or 0,
    }
