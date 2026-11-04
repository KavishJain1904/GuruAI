"""Registration, login, and logout."""
from fastapi import APIRouter, HTTPException, Response

from src.api.deps import COOKIE_NAME, set_auth_cookie
from src.api.schemas import LoginRequest, RegisterRequest
from src.auth.auth import hash_password, verify_password
from src.core.database import get_db

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/register")
def register(req: RegisterRequest, response: Response):
    """Create an account and log the new user straight in."""
    username = req.username.strip().lower()
    if not username or not req.password:
        raise HTTPException(status_code=400, detail="Username and password are required")

    # Open the database JUST ONCE for the entire function
    with get_db() as conn:
        cur = conn.cursor()

        # 1. Check if username exists using a single connection
        cur.execute("SELECT id FROM users WHERE username = %s", (username,))
        if cur.fetchone():
            raise HTTPException(status_code=400, detail="Username is already taken")

        # 2. Hash password and write the new user using the SAME connection
        pwd_hash = hash_password(req.password)
        cur.execute(
            "INSERT INTO users (username, password_hash, name) VALUES (%s, %s, %s) RETURNING id",
            (username, pwd_hash, req.name or "The Scholar")
        )
        user_id = cur.fetchone()["id"]
        conn.commit()

    # 3. Issue the token and set the browser cookie
    set_auth_cookie(response, user_id)
    return {"status": "ok", "user_id": user_id}


@router.post("/login")
def login(req: LoginRequest, response: Response):
    """Exchange credentials for an auth cookie."""
    username = req.username.strip().lower()
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, password_hash FROM users WHERE username = %s", (username,))
        row = cur.fetchone()

    if not row or not verify_password(req.password, row["password_hash"]):
        raise HTTPException(status_code=400, detail="Invalid username or password")

    user_id = row["id"]
    set_auth_cookie(response, user_id)
    return {"status": "ok", "user_id": user_id}


@router.post("/logout")
def logout(response: Response):
    """Clear the auth cookie."""
    response.delete_cookie(COOKIE_NAME)
    return {"status": "ok"}
