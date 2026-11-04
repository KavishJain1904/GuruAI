"""GuruAI FastAPI application entry point.

Route handlers live in src/api/routers/, one module per functional area.
Shared auth dependencies are in src/api/deps.py.

Run with:  python server.py
"""
import os

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from src.api.routers import (
    auth,
    chat,
    memory,
    pages,
    profile,
    quiz,
    sessions,
    srs,
    subjects,
    topic,
    user,
)
from src.core.database import init_db
from src.personalization.topic_graph_seed import apply_curated_graph_corrections

app = FastAPI(title="GuruAI")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup_event():
    """Initialize the SQLite schema before serving traffic.

    When SEED_DEMO is truthy (e.g. on a public demo deployment), also populate a
    demo account so reviewers can explore the app without registering or
    uploading. Seeding failures never block startup.
    """
    init_db()
    apply_curated_graph_corrections()
    if os.getenv("SEED_DEMO", "").lower() in ("1", "true", "yes"):
        try:
            from scripts.seed_demo import seed_demo
            seed_demo()
        except Exception as e:  # a broken demo must not take the app down
            print(f"[startup] demo seed skipped: {e}")


app.mount("/static", StaticFiles(directory="static"), name="static")

# JSON API. Every router below gates on Depends(get_current_user).
app.include_router(auth.router)
app.include_router(sessions.router)
app.include_router(chat.router)
app.include_router(quiz.router)
app.include_router(profile.router)
app.include_router(srs.router)
app.include_router(subjects.router)
app.include_router(topic.router)
app.include_router(memory.router)
app.include_router(user.router)

# HTML pages last, so the /api/* routes above always take precedence.
app.include_router(pages.router)


if __name__ == "__main__":
    # PORT is injected by most hosts (Hugging Face Spaces expects 7860); defaults
    # to 8000 for local dev. RELOAD=1 turns on autoreload while developing.
    port = int(os.getenv("PORT", "8000"))
    reload = os.getenv("RELOAD", "").lower() in ("1", "true", "yes")
    uvicorn.run("server:app", host="0.0.0.0", port=port, reload=reload)
