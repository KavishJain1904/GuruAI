"""User display profile and aggregate study statistics."""
from fastapi import APIRouter, Depends

from src.api.deps import get_current_user
from src.api.schemas import UserProfileRequest
from src.personalization import mastery, user_memory

router = APIRouter(prefix="/api/user", tags=["user"])


@router.get("/profile")
def get_user_profile(user_id: int = Depends(get_current_user)):
    """Return the user's stored display name and bio."""
    return user_memory.load_user_profile(user_id)


@router.post("/profile")
def save_user_profile(req: UserProfileRequest, user_id: int = Depends(get_current_user)):
    """Persist the user's display name and bio."""
    return user_memory.save_user_profile(user_id, req.name, req.bio)


@router.get("/stats")
def get_user_stats(user_id: int = Depends(get_current_user)):
    """Return total questions answered and average mastery across all topics."""
    return mastery.get_user_stats(user_id)
