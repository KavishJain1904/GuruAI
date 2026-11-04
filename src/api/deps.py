"""Shared FastAPI dependencies: authentication and session ownership."""
import os
from typing import Optional

from fastapi import HTTPException, Request, Response, status

from src.auth.auth import create_access_token, verify_access_token
from src.core.database import get_db

COOKIE_NAME = "access_token"
COOKIE_MAX_AGE = 86400

# Send the auth cookie only over HTTPS when deployed. Defaults to False so local
# development over http://localhost keeps working; set COOKIE_SECURE=1 in any
# HTTPS deployment (e.g. Hugging Face Spaces).
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "").lower() in ("1", "true", "yes")


def set_auth_cookie(response: Response, user_id: int) -> None:
    """Issue a signed token for the user and attach it as an HTTPOnly cookie."""
    token = create_access_token({"user_id": user_id})
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        max_age=COOKIE_MAX_AGE,
        samesite="lax",
        secure=COOKIE_SECURE,
    )


def get_current_user(request: Request) -> int:
    """Dependency to retrieve the currently logged in user ID from the HTTPOnly cookie."""
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired or not authenticated"
        )
    payload = verify_access_token(token)
    if not payload or "user_id" not in payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token"
        )
    return payload["user_id"]


def check_auth_html(request: Request) -> Optional[int]:
    """Helper to check credentials silently for page serving (redirecting instead of JSON error)."""
    token = request.cookies.get(COOKIE_NAME)
    if token:
        payload = verify_access_token(token)
        if payload and "user_id" in payload:
            return payload["user_id"]
    return None


def verify_session_ownership(session_id: str, user_id: int) -> None:
    """Raises 403/404 if the session does not belong to the authenticated user."""
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT user_id FROM sessions WHERE id = %s", (session_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Session not found")
        if row["user_id"] != user_id:
            raise HTTPException(status_code=403, detail="Access denied")
