"""Per-topic tutoring: mastery-scaled explanations and quizzes."""
from fastapi import APIRouter, Depends

from src.api.deps import get_current_user
from src.api.schemas import TopicExplainRequest
from src.rag.topic_tutor import generate_topic_explanation, generate_topic_quiz

router = APIRouter(prefix="/api/topic", tags=["topic-tutor"])


@router.post("/explain")
def explain_topic(req: TopicExplainRequest, user_id: int = Depends(get_current_user)):
    """Explain a topic at a depth matched to the student's current mastery."""
    explanation = generate_topic_explanation(
        req.topic, req.subject, req.mastery_level, req.score_pct
    )
    return {"explanation": explanation}


@router.post("/quiz")
def topic_quiz(req: TopicExplainRequest, user_id: int = Depends(get_current_user)):
    """Generate a difficulty-adjusted quiz for a single topic."""
    return generate_topic_quiz(
        req.topic, req.subject, req.mastery_level, req.score_pct
    )
