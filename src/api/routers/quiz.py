"""Session quiz generation and answer recording."""
from fastapi import APIRouter, Depends, HTTPException

from src.api.deps import get_current_user, verify_session_ownership
from src.api.schemas import QuizAnswerRequest
from src.personalization import mastery, user_memory
from src.rag.embedder import vectorstore_exists
from src.rag.quiz import generate_quiz_for_session_db
from src.sessions import store

router = APIRouter(prefix="/api", tags=["quiz"])


@router.post("/sessions/{session_id}/quiz")
def generate_quiz(session_id: str, user_id: int = Depends(get_current_user)):
    """Generate a quiz from the session's uploaded documents."""
    verify_session_ownership(session_id, user_id)
    if not vectorstore_exists(session_id):
        raise HTTPException(status_code=400, detail="Build the database first.")
    quiz = generate_quiz_for_session_db(
        session_id, user_subjects=user_memory.load_subjects(user_id)
    )
    if not quiz or not quiz.get("questions"):
        raise HTTPException(status_code=500, detail="Quiz generation failed.")
    store.save_quiz(session_id, quiz)          # Keep for topic.html backwards compat
    store.add_message(session_id, "quiz", quiz)  # Embed in chat feed for inline rendering
    return quiz


@router.get("/sessions/{session_id}/quiz")
def get_quiz(session_id: str, user_id: int = Depends(get_current_user)):
    """Return the session's most recently generated quiz."""
    verify_session_ownership(session_id, user_id)
    return store.get_quiz(session_id)


@router.post("/quiz/answer")
def submit_answer(req: QuizAnswerRequest, user_id: int = Depends(get_current_user)):
    """Record one quiz answer and fold it into the topic's mastery score."""
    if req.session_id:
        verify_session_ownership(req.session_id, user_id)
    try:
        result = mastery.update_topic_performance(
        req.session_id, req.subject, req.topic, req.is_correct, user_id=user_id,
        topic_id=req.topic_id,
        question=req.question, selected_answer=req.selected_answer, correct_answer=req.correct_answer,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"status": "recorded", **result}
