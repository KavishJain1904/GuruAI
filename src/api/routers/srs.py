"""Spaced-repetition review queue and study-session recording."""
from fastapi import APIRouter, Depends, HTTPException, Query

from src.api.deps import get_current_user
from src.api.schemas import MarkReviewedRequest
from src.personalization import mastery, topic_graph

router = APIRouter(prefix="/api", tags=["srs"])


@router.get("/suggestions/review-queue")
def get_review_queue(
    category: str = Query("all", pattern="^(all|weak|average|strong)$"),
    limit: int = Query(10, ge=1, le=50),
    sort: str = Query("urgent", pattern="^(urgent|recent)$"),
    user_id: int = Depends(get_current_user),
) -> dict:
    """Return topics due for review today or earlier.

    category filters by mastery_category ('weak'/'average'/'strong'), sort picks
    between soonest-due-first ('urgent') and most-recently-studied-first ('recent').
    """
    return mastery.build_review_queue(user_id, category=category, limit=limit, sort=sort)


@router.post("/topics/{topic_id}/mark-reviewed")
def mark_topic_reviewed(
    topic_id: int,
    req: MarkReviewedRequest,
    user_id: int = Depends(get_current_user),
) -> dict:
    """Record a study session for a topic: updates its mastery EMA and spaced-repetition schedule.

    score is 0-10. Notes and the mastery/schedule change are saved in review history.
    Self-ratings never increment quiz correctness or question totals.
    """
    if not (0 <= req.score <= 10):
        raise HTTPException(status_code=400, detail="score must be between 0 and 10")

    updated = mastery.update_ema(topic_id, user_id, req.score / 10, notes=req.notes)
    if not updated:
        raise HTTPException(status_code=404, detail="Topic not found")

    return {
        "topic": updated["topic"],
        "mastery_updated": updated["mastery_level"],
        "next_review": updated["next_review"],
        "message": "Great! Study session recorded.",
    }


@router.get("/topics/statistics")
def get_topics_statistics(user_id: int = Depends(get_current_user)) -> dict:
    """Return dashboard stats summarizing the user's spaced-repetition progress."""
    return mastery.get_topic_statistics(user_id)


@router.get("/topics/graph")
def get_topics_graph(
    subject: str = Query(..., min_length=1),
    user_id: int = Depends(get_current_user),
) -> dict:
    """Return the curriculum graph (nodes/edges) for a subject, for a future
    knowledge-map visualization. The graph is shared across users (not scoped
    to user_id) — auth here just gates read access to a logged-in user, same
    as every other endpoint. Empty nodes/edges if the subject hasn't been
    seeded yet (see topic_graph_seed.py).
    """
    return topic_graph.get_subject_graph(subject)


@router.get("/reviews")
def get_review_history(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    topic_id: int | None = Query(None, ge=1),
    user_id: int = Depends(get_current_user),
) -> dict:
    """Read recorded quiz answers and self-ratings, newest first."""
    if topic_id is not None and mastery.get_topic_by_id(topic_id, user_id) is None:
        raise HTTPException(status_code=404, detail="Topic not found")
    return mastery.get_review_history(user_id, limit=limit, offset=offset, topic_id=topic_id)
