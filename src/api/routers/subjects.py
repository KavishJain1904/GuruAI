"""The subjects a user has registered for study."""
from fastapi import APIRouter, BackgroundTasks, Depends

from src.api.deps import get_current_user
from src.api.schemas import SubjectRequest
from src.personalization import topic_graph_seed, user_memory

router = APIRouter(prefix="/api/subjects", tags=["subjects"])


@router.get("")
def get_subjects(user_id: int = Depends(get_current_user)):
    """Return all registered subjects."""
    return {"subjects": user_memory.load_subjects(user_id)}


@router.post("")
def add_subject(
    req: SubjectRequest,
    background_tasks: BackgroundTasks,
    user_id: int = Depends(get_current_user),
):
    """Add a new subject to the user's study profile.

    Also kicks off curriculum-graph seeding for the subject in the background
    (no-op if it's already seeded) — the response doesn't wait on it.
    """
    subjects = user_memory.save_subject(user_id, req.subject)
    background_tasks.add_task(topic_graph_seed.seed_subject_graph, req.subject)
    return {"subjects": subjects}


@router.delete("/{subject}")
def remove_subject(subject: str, user_id: int = Depends(get_current_user)):
    """Remove a subject from the user's study profile."""
    return {"subjects": user_memory.delete_subject(user_id, subject)}
