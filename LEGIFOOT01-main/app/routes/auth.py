from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.responses import HTMLResponse, RedirectResponse

router = APIRouter()

@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, next: str = "/") -> HTMLResponse:
    from app.main import templates
    return templates.TemplateResponse(request, "login.html", {"page": "login", "next": next, "error": ""})


@router.post("/login")
def login_action(request: Request, password: str = Form(""), next: str = Form("/")) -> Response:
def login_action(request: Request, password: str = Form(""), next: str = Form("/")) -> RedirectResponse | HTMLResponse:
    from app.main import ADMIN_PASSWORD, templates

    if password != ADMIN_PASSWORD:
        return templates.TemplateResponse(request, "login.html", {"page": "login", "next": next, "error": "Mot de passe invalide"}, status_code=401)
    request.session["is_admin"] = True
    return RedirectResponse(url=next or "/", status_code=303)


@router.get("/logout")
def logout_action(request: Request) -> RedirectResponse:
    request.session.clear()
    return RedirectResponse(url="/", status_code=303)
