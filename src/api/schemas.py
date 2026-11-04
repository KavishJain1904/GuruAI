"""Pydantic request models for the HTTP API."""
from typing import Optional

from pydantic import BaseModel, Field


class RegisterRequest(BaseModel):
    username: str
    password: str
    name: Optional[str] = "The Scholar"


class LoginRequest(BaseModel):
    username: str
    password: str


class ChatRequest(BaseModel):
    session_id: str
    question: str


class QuizAnswerRequest(BaseModel):
    session_id: Optional[str] = None
    topic_id: Optional[int] = Field(default=None, gt=0)
    subject: str = Field(min_length=1, max_length=200)
    topic: str = Field(min_length=1, max_length=200)
    is_correct: bool
    question: Optional[str] = Field(default=None, max_length=10000)
    selected_answer: Optional[str] = Field(default=None, max_length=10000)
    correct_answer: Optional[str] = Field(default=None, max_length=10000)


class MarkReviewedRequest(BaseModel):
    score: int
    notes: Optional[str] = None


class SubjectRequest(BaseModel):
    subject: str


class TopicExplainRequest(BaseModel):
    topic: str
    subject: str
    mastery_level: str  # "strong", "average", "weak"
    score_pct: int      # 0-100


class MemoryMessageRequest(BaseModel):
    message: str


class UserProfileRequest(BaseModel):
    name: str
    bio: str
