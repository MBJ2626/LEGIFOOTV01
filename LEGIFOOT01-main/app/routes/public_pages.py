from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

router = APIRouter()

@router.get("/about", response_class=HTMLResponse)
def about_page(request: Request) -> HTMLResponse:
    from app.main import templates
    return templates.TemplateResponse(request, "about.html", {"page": "about"})


@router.get("/help", response_class=HTMLResponse)
def help_page(request: Request) -> HTMLResponse:
    from app.main import templates
    return templates.TemplateResponse(request, "help.html", {"page": "help"})


@router.get("/mes-suivis", response_class=HTMLResponse)
def favorites_page(request: Request) -> HTMLResponse:
    from app.main import templates
    return templates.TemplateResponse(request, "favorites.html", {"page": "favorites"})
