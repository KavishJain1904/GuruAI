"""Static HTML page serving.

These routes gate layout files on authentication. Unlike the /api/* endpoints,
an unauthenticated visitor is redirected to the login screen rather than given a
401, and a logged-in visitor is bounced off the login screen.
"""
from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, RedirectResponse

from src.api.deps import check_auth_html

router = APIRouter(tags=["pages"])


def _serve_protected(request: Request, page: str):
    """Serve static/<page>, or redirect to the login screen if not signed in."""
    if not check_auth_html(request):
        return RedirectResponse(url="/login.html")
    return FileResponse(f"static/{page}")


@router.get("/")
def root(request: Request):
    """Landing route — same content as /index.html."""
    return _serve_protected(request, "index.html")


@router.get("/index.html")
def index_page(request: Request):
    return _serve_protected(request, "index.html")


@router.get("/knowledge.html")
def knowledge_page(request: Request):
    return _serve_protected(request, "knowledge.html")


@router.get("/topic.html")
def topic_page(request: Request):
    return _serve_protected(request, "topic.html")


@router.get("/user.html")
def user_page(request: Request):
    return _serve_protected(request, "user.html")


@router.get("/login.html")
def login_page(request: Request):
    """Login screen. Already-authenticated users are sent to the app."""
    if check_auth_html(request):
        return RedirectResponse(url="/index.html")
    return FileResponse("static/login.html")
