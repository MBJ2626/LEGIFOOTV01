from __future__ import annotations

import base64
import csv
import hashlib
import hmac
import json
import os
import re
import shutil
from io import StringIO
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from . import database as db
from .extractor import extract_document, sha256_file
from .parser import parse_match_sheet
from .routes.auth import router as auth_router
from .routes.public_pages import router as public_pages_router
from .routes.api_export import router as api_export_router

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = Path(os.getenv("LEGIFOOT_UPLOAD_DIR", BASE_DIR / "uploads"))
EXPORT_DIR = Path(os.getenv("LEGIFOOT_EXPORT_DIR", BASE_DIR / "data" / "exports"))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
EXPORT_DIR.mkdir(parents=True, exist_ok=True)

SESSION_COOKIE = "legifoot_session"
SESSION_MAX_AGE = 60 * 60 * 24 * 14
ENVIRONMENT = os.getenv("LEGIFOOT_ENV", "development").lower()
SESSION_SECRET_KEY = os.getenv("LEGIFOOT_SECRET_KEY", "legifoot-dev-secret-change-me")
SESSION_HTTPS_ONLY = os.getenv("LEGIFOOT_HTTPS_ONLY", "0") == "1" or ENVIRONMENT == "production"
MAX_UPLOAD_SIZE_MB = int(os.getenv("LEGIFOOT_MAX_UPLOAD_MB", "20"))
MAX_UPLOAD_BYTES = MAX_UPLOAD_SIZE_MB * 1024 * 1024


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _session_signature(payload: str) -> str:
    digest = hmac.new(SESSION_SECRET_KEY.encode("utf-8"), payload.encode("ascii"), hashlib.sha256).digest()
    return _b64encode(digest)


def _load_session(cookie_value: str | None) -> dict[str, Any]:
    if not cookie_value or "." not in cookie_value:
        return {}
    payload, signature = cookie_value.rsplit(".", 1)
    if not hmac.compare_digest(_session_signature(payload), signature):
        return {}
    try:
        data = json.loads(_b64decode(payload).decode("utf-8"))
    except (ValueError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _dump_session(session: dict[str, Any]) -> str:
    payload = _b64encode(json.dumps(session, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    return f"{payload}.{_session_signature(payload)}"


app = FastAPI(title="LEGIFOOT", version="0.3.0")


@app.middleware("http")
async def signed_cookie_session(request: Request, call_next: Any) -> Response:
    request.scope["session"] = _load_session(request.cookies.get(SESSION_COOKIE))
    response = await call_next(request)
    if request.scope["session"]:
        response.set_cookie(
            SESSION_COOKIE,
            _dump_session(request.scope["session"]),
            max_age=SESSION_MAX_AGE,
            httponly=True,
            samesite="strict" if ENVIRONMENT == "production" else "lax",
            secure=SESSION_HTTPS_ONLY,
        )
    else:
        response.delete_cookie(SESSION_COOKIE, samesite="strict" if ENVIRONMENT == "production" else "lax", secure=SESSION_HTTPS_ONLY)
    return response


app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")

ALLOWED_SUFFIXES = {".pdf", ".docx", ".xlsx", ".xlsm", ".xls", ".csv"}
ADMIN_PASSWORD = os.getenv("LEGIFOOT_ADMIN_PASSWORD", "admin123")

if ENVIRONMENT == "production":
    if SESSION_SECRET_KEY == "legifoot-dev-secret-change-me":
        raise RuntimeError("LEGIFOOT_SECRET_KEY must be set in production")
    if ADMIN_PASSWORD == "admin123":
        raise RuntimeError("LEGIFOOT_ADMIN_PASSWORD must be set in production")

COMPETITIONS = [
    {"value": "Ligue 1 Professionnelle", "label": "Ligue 1", "short": "L1", "description": "Championnat élite tunisien"},
    {"value": "Ligue 2 Professionnelle", "label": "Ligue 2", "short": "L2", "description": "Deuxième niveau national"},
    {"value": "Coupe de Tunisie", "label": "Coupe de Tunisie", "short": "CT", "description": "Compétition nationale à élimination"},
]
COMPETITION_VALUES = {item["value"] for item in COMPETITIONS}



def is_admin_user(request: Request) -> bool:
    return bool(request.session.get("is_admin"))


def admin_login_redirect(request: Request) -> RedirectResponse:
    path = request.url.path
    return RedirectResponse(url=f"/login?next={path}", status_code=303)


def require_admin(request: Request) -> None:
    if not is_admin_user(request):
        raise HTTPException(status_code=403, detail="Accès administrateur requis")


def normalize_competition(value: str | None) -> str:
    value = (value or "").strip()
    if value in COMPETITION_VALUES:
        return value
    key = value.lower().replace("é", "e").replace("è", "e").replace("2eme", "2").replace("ii", "2").replace("i", "1")
    if "coupe" in key:
        return "Coupe de Tunisie"
    if "ligue 2" in key or "ligue2" in key or "l2" in key:
        return "Ligue 2 Professionnelle"
    return "Ligue 1 Professionnelle"


def apply_import_context(payload: dict[str, Any], *, competition: str = "", season: str = "", round_label: str = "") -> dict[str, Any]:
    selected_competition = normalize_competition(competition) if competition else ""

    def apply_one(item: dict[str, Any]) -> None:
        match = item.setdefault("match", {})
        if selected_competition:
            match["competition"] = selected_competition
        elif not match.get("competition"):
            match["competition"] = "Ligue 1 Professionnelle"
        if season.strip():
            match["season"] = season.strip()
        if round_label.strip():
            match["round"] = round_label.strip()

    if isinstance(payload.get("matches"), list):
        for child in payload.get("matches", []):
            if isinstance(child, dict):
                apply_one(child)
    else:
        apply_one(payload)
    payload.setdefault("_meta", {})["platform"] = "LEGIFOOT"
    return payload



def safe_filename(name: str) -> str:
    stem = Path(name).stem[:80]
    suffix = Path(name).suffix.lower()
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", stem).strip("._") or "document"
    return f"{stem}{suffix}"


def json_pretty(value: Any) -> str:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except Exception:
            return value
    return json.dumps(value, ensure_ascii=False, indent=2)


def dash(value: Any) -> str:
    return "—" if value is None or value == "" else str(value)


def score(match: dict[str, Any]) -> str:
    if match.get("score_home") is None or match.get("score_away") is None:
        return "—"
    return f"{match.get('score_home')} - {match.get('score_away')}"


def minute_label(row: dict[str, Any]) -> str:
    if row.get("minute") is None:
        return "—"
    label = str(row.get("minute"))
    if row.get("stoppage"):
        label += f"+{row.get('stoppage')}"
    return label + "'"


def event_label(row: dict[str, Any]) -> str:
    event_type = row.get("event_type") or "note"
    if event_type == "goal":
        return "But"
    if event_type == "card":
        return "Carton jaune" if row.get("card_color") == "yellow" else "Carton rouge" if row.get("card_color") == "red" else "Carton"
    if event_type == "substitution":
        return "Remplacement"
    return event_type.capitalize()


def csv_safe(value: Any) -> str:
    text = str(value or "")
    if text[:1] in {"=", "+", "-", "@"}:
        return "'" + text
    return text


def pct(value: Any) -> str:
    try:
        return f"{float(value) * 100:.0f}%"
    except Exception:
        return "—"


templates.env.filters["json_pretty"] = json_pretty
templates.env.filters["dash"] = dash
templates.env.filters["score"] = score
templates.env.filters["minute_label"] = minute_label
templates.env.filters["event_label"] = event_label
templates.env.filters["pct"] = pct


def status_label(status: Any) -> str:
    mapping = {
        "draft": "Brouillon", "to_review": "À vérifier", "validated": "Validé",
        "published": "Publié", "played": "Joué", "archived": "Archivé", "incomplete": "Incomplet"
    }
    return mapping.get(str(status or "played"), str(status or "Joué"))

def status_class(status: Any) -> str:
    mapping = {"draft":"muted", "to_review":"yellow", "validated":"green", "published":"green", "played":"blue", "archived":"muted", "incomplete":"red"}
    return mapping.get(str(status or "played"), "blue")

def completeness(match_id: Any) -> dict[str, Any]:
    try:
        return db.match_completeness(int(match_id))
    except Exception:
        return {"score": 0, "label": "À vérifier", "missing": [], "class": "yellow"}

def is_public_status(status: Any) -> bool:
    return db.public_status(str(status or "played"))

templates.env.filters["status_label"] = status_label
templates.env.filters["status_class"] = status_class
templates.env.globals["completeness"] = completeness
templates.env.globals["is_public_status"] = is_public_status
templates.env.globals["competitions"] = COMPETITIONS
templates.env.globals["app_name"] = "LEGIFOOT"
templates.env.globals["is_admin"] = is_admin_user



def split_semicolon_lines(text: str | None) -> list[list[str]]:
    rows: list[list[str]] = []
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        rows.append([part.strip() for part in line.split(";")])
    return rows


def get_part(parts: list[str], index: int, default: str = "") -> str:
    return parts[index].strip() if index < len(parts) and parts[index] is not None else default


def manual_truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "oui", "yes", "true", "vrai", "x", "c", "capitaine", "g", "gardien"}


def normalize_manual_role(value: str) -> tuple[str, bool, bool]:
    role_key = value.strip().lower().replace("é", "e").replace("ç", "c")
    starter = role_key in {"titulaire", "starter", "t", "11"}
    substitute = role_key in {"remplacant", "remplaçant", "substitute", "bench", "r"}
    role = "titulaire" if starter else "remplaçant" if substitute else (value.strip() or "joueur")
    return role, starter, substitute


def parse_manual_players(text: str | None) -> list[dict[str, Any]]:
    players: list[dict[str, Any]] = []
    for parts in split_semicolon_lines(text):
        role, starter, substitute = normalize_manual_role(get_part(parts, 3, "titulaire"))
        name = get_part(parts, 1)
        if not name:
            continue
        players.append(
            {
                "number": get_part(parts, 0),
                "name": name,
                "license_number": get_part(parts, 2),
                "role": role,
                "starter": starter,
                "substitute": substitute,
                "captain": manual_truthy(get_part(parts, 4)),
                "goalkeeper": manual_truthy(get_part(parts, 5)),
                "position": get_part(parts, 6),
                "nationality": get_part(parts, 7),
                "notes": get_part(parts, 8),
            }
        )
    return players


def parse_manual_staff(text: str | None) -> list[dict[str, Any]]:
    staff: list[dict[str, Any]] = []
    for parts in split_semicolon_lines(text):
        name = get_part(parts, 0)
        if name:
            staff.append({"name": name, "role": get_part(parts, 1) or "Staff"})
    return staff


def parse_manual_officials(text: str | None) -> list[dict[str, Any]]:
    officials: list[dict[str, Any]] = []
    for parts in split_semicolon_lines(text):
        role = get_part(parts, 0)
        name = get_part(parts, 1)
        if name:
            officials.append({"role": role or "OFFICIEL", "name": name})
    return officials


def card_color_value(value: str) -> str:
    key = value.strip().lower()
    if key in {"rouge", "red", "r"}:
        return "red"
    return "yellow"


def build_manual_payload(
    *,
    competition: str,
    season: str,
    round_label: str,
    status: str,
    match_date: str,
    match_time: str,
    stadium: str,
    city: str,
    home_team: str,
    away_team: str,
    score_home: str,
    score_away: str,
    halftime_home: str,
    halftime_away: str,
    home_players: str,
    away_players: str,
    home_staff: str,
    away_staff: str,
    officials: str,
    goals: str,
    cards: str,
    substitutions: str,
    observations: str,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "_meta": {"source": "manual_entry", "confidence": 1.0, "warnings": []},
        "match": {
            "competition": competition.strip(),
            "season": season.strip(),
            "round": round_label.strip(),
            "date": match_date.strip(),
            "time": match_time.strip(),
            "stadium": stadium.strip(),
            "city": city.strip(),
            "home_team": home_team.strip(),
            "away_team": away_team.strip(),
            "score_home": score_home.strip(),
            "score_away": score_away.strip(),
            "halftime_home": halftime_home.strip(),
            "halftime_away": halftime_away.strip(),
            "status": status.strip() or "played",
        },
        "teams": [
            {"side": "home", "name": home_team.strip(), "players": parse_manual_players(home_players), "staff": parse_manual_staff(home_staff)},
            {"side": "away", "name": away_team.strip(), "players": parse_manual_players(away_players), "staff": parse_manual_staff(away_staff)},
        ],
        "officials": parse_manual_officials(officials),
        "events": [],
        "observations": [],
    }

    for parts in split_semicolon_lines(goals):
        if get_part(parts, 2):
            payload["events"].append({"event_type": "goal", "minute": get_part(parts, 0), "team": get_part(parts, 1), "player": get_part(parts, 2), "detail": get_part(parts, 3)})

    for parts in split_semicolon_lines(cards):
        if get_part(parts, 2):
            color = card_color_value(get_part(parts, 3))
            payload["events"].append({"event_type": "card", "minute": get_part(parts, 0), "team": get_part(parts, 1), "player": get_part(parts, 2), "card_color": color, "detail": get_part(parts, 4)})

    for parts in split_semicolon_lines(substitutions):
        if get_part(parts, 2) or get_part(parts, 3):
            payload["events"].append({"event_type": "substitution", "minute": get_part(parts, 0), "team": get_part(parts, 1), "player": get_part(parts, 2), "related_player": get_part(parts, 3), "detail": get_part(parts, 4)})

    for parts in split_semicolon_lines(observations):
        note = get_part(parts, 3) or get_part(parts, 0)
        if note:
            payload["observations"].append({"minute": get_part(parts, 0) if len(parts) > 3 else "", "author": get_part(parts, 1), "severity": get_part(parts, 2) or "note", "note": note})

    home_starters = sum(1 for p in payload["teams"][0]["players"] if p.get("starter"))
    away_starters = sum(1 for p in payload["teams"][1]["players"] if p.get("starter"))
    if home_starters and home_starters != 11:
        payload["_meta"]["warnings"].append(f"Domicile: {home_starters} titulaires saisis au lieu de 11.")
    if away_starters and away_starters != 11:
        payload["_meta"]["warnings"].append(f"Extérieur: {away_starters} titulaires saisis au lieu de 11.")
    return payload


def list_filter_options(matches: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    rows = matches if matches is not None else db.list_matches()
    seasons = sorted({str(m.get("season") or "").strip() for m in rows if str(m.get("season") or "").strip()})
    clubs = sorted({
        str(v).strip()
        for m in rows
        for v in (m.get("home_team"), m.get("away_team"))
        if str(v or "").strip()
    })
    discovered = sorted({str(m.get("competition") or "").strip() for m in rows if str(m.get("competition") or "").strip()})
    known_values = {c["value"] for c in COMPETITIONS}
    competitions = list(COMPETITIONS)
    for value in discovered:
        if value not in known_values:
            competitions.append({"value": value, "label": value, "short": "AUT", "description": "Compétition détectée"})
    return {"seasons": seasons, "clubs": clubs, "competitions": competitions}


def match_passes_filters(
    row: dict[str, Any],
    competition: str = "",
    season: str = "",
    club: str = "",
    date_from: str = "",
    date_to: str = "",
    round_label: str = "",
    q: str = "",
) -> bool:
    competition = (competition or "").strip()
    season = (season or "").strip()
    club = (club or "").strip()
    date_from = (date_from or "").strip()
    date_to = (date_to or "").strip()
    round_label = (round_label or "").strip().lower()
    q = (q or "").strip().lower()
    if competition and (row.get("competition") or "") != competition:
        return False
    if season and (row.get("season") or "") != season:
        return False
    if club and club not in {(row.get("home_team") or ""), (row.get("away_team") or "")}:
        return False
    match_date = str(row.get("match_date") or "")
    if date_from and match_date and match_date < date_from:
        return False
    if date_to and match_date and match_date > date_to:
        return False
    if round_label and round_label not in str(row.get("round_label") or "").lower():
        return False
    if q:
        haystack = " ".join(str(row.get(k) or "") for k in ("home_team", "away_team", "stadium", "competition", "season", "round_label", "match_date")).lower()
        if q not in haystack:
            return False
    return True


def build_filtered_dashboard_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    clubs = {
        v
        for row in rows
        for v in (row.get("home_team"), row.get("away_team"))
        if v
    }
    total_goals = 0
    for row in rows:
        try:
            total_goals += int(row.get("score_home") or 0) + int(row.get("score_away") or 0)
        except Exception:
            pass
    match_ids = {row.get("id") for row in rows}
    events = [e for e in db.list_events() if e.get("match_id") in match_ids]
    return {
        "matches": len(rows),
        "clubs": len(clubs),
        "goals": sum(1 for e in events if e.get("event_type") == "goal"),
        "events": len(events),
        "yellow_cards": sum(1 for e in events if e.get("event_type") == "card" and e.get("card_color") == "yellow"),
        "red_cards": sum(1 for e in events if e.get("event_type") == "card" and e.get("card_color") == "red"),
        "score_goals": total_goals,
    }


def dashboard_context(competition: str = "", season: str = "", club: str = "", date_from: str = "", date_to: str = "", round_label: str = "", q: str = "") -> dict[str, Any]:
    stats = db.dashboard_stats()
    all_matches = db.list_matches()
    rows = [m for m in all_matches if match_passes_filters(m, competition, season, club, date_from, date_to, round_label, q)]
    return {
        "stats": stats,
        "quick_stats": build_filtered_dashboard_stats(rows),
        "filtered_matches": rows[:10],
        "filters": {"competition": competition, "season": season, "club": club, "date_from": date_from, "date_to": date_to, "round_label": round_label, "q": q},
        "filter_options": list_filter_options(all_matches),
        "charts": db.dashboard_chart_data(competition=competition, season=season, club=club),
        "todo": db.admin_todo_board(),
        "missing": db.list_missing_data(),
        "activity": db.recent_activity(),
        "page": "dashboard",
        "competitions": COMPETITIONS,
    }


@app.on_event("startup")
def on_startup() -> None:
    db.init_db()



@app.get("/", response_class=HTMLResponse)
def dashboard_home(request: Request, competition: str = "", season: str = "", club: str = "", date_from: str = "", date_to: str = "", round_label: str = "", q: str = "") -> HTMLResponse:
    return templates.TemplateResponse(request, "dashboard.html", dashboard_context(competition, season, club, date_from, date_to, round_label, q))


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, competition: str = "", season: str = "", club: str = "", date_from: str = "", date_to: str = "", round_label: str = "", q: str = "") -> HTMLResponse:
    return templates.TemplateResponse(request, "dashboard.html", dashboard_context(competition, season, club, date_from, date_to, round_label, q))


@app.get("/upload", response_class=HTMLResponse)
def upload_page(request: Request) -> Response:
    if not is_admin_user(request):
        return admin_login_redirect(request)
    return templates.TemplateResponse(request, "upload.html", {"page": "upload", "allowed": sorted(ALLOWED_SUFFIXES), "competitions": COMPETITIONS})




@app.get("/manual", response_class=HTMLResponse)
def manual_entry_page(request: Request) -> Response:
    if not is_admin_user(request):
        return admin_login_redirect(request)
    return templates.TemplateResponse(request, "manual_entry.html", {"page": "manual", "competitions": COMPETITIONS})


@app.post("/manual")
def create_manual_match(
    request: Request,
    competition: str = Form(""),
    season: str = Form(""),
    round_label: str = Form(""),
    status: str = Form("played"),
    match_date: str = Form(""),
    match_time: str = Form(""),
    stadium: str = Form(""),
    city: str = Form(""),
    home_team: str = Form(...),
    away_team: str = Form(...),
    score_home: str = Form(""),
    score_away: str = Form(""),
    halftime_home: str = Form(""),
    halftime_away: str = Form(""),
    home_players: str = Form(""),
    away_players: str = Form(""),
    home_staff: str = Form(""),
    away_staff: str = Form(""),
    officials: str = Form(""),
    goals: str = Form(""),
    cards: str = Form(""),
    substitutions: str = Form(""),
    observations: str = Form(""),
) -> RedirectResponse:
    require_admin(request)
    payload = build_manual_payload(
        competition=competition,
        season=season,
        round_label=round_label,
        status=status,
        match_date=match_date,
        match_time=match_time,
        stadium=stadium,
        city=city,
        home_team=home_team,
        away_team=away_team,
        score_home=score_home,
        score_away=score_away,
        halftime_home=halftime_home,
        halftime_away=halftime_away,
        home_players=home_players,
        away_players=away_players,
        home_staff=home_staff,
        away_staff=away_staff,
        officials=officials,
        goals=goals,
        cards=cards,
        substitutions=substitutions,
        observations=observations,
    )
    match_ids = db.insert_matches_from_payload(payload, document_id=None)
    if not match_ids:
        raise HTTPException(status_code=400, detail="Aucun match n'a pu être créé depuis la saisie manuelle.")
    return RedirectResponse(url=f"/matches/{match_ids[0]}", status_code=303)


@app.post("/upload")
async def upload_files(
    request: Request,
    files: list[UploadFile] = File(...),
    competition: str = Form("Ligue 1 Professionnelle"),
    season: str = Form(""),
    round_label: str = Form(""),
) -> RedirectResponse:
    require_admin(request)
    created_ids: list[int] = []
    for uploaded in files:
        suffix = Path(uploaded.filename or "").suffix.lower()
        if suffix not in ALLOWED_SUFFIXES:
            continue
        base_name = safe_filename(uploaded.filename or f"document{suffix}")
        target = UPLOAD_DIR / base_name
        counter = 1
        while target.exists():
            target = UPLOAD_DIR / f"{Path(base_name).stem}_{counter}{suffix}"
            counter += 1
        written = 0
        with target.open("wb") as f:
            while True:
                chunk = uploaded.file.read(1024 * 1024)
                if not chunk:
                    break
                written += len(chunk)
                if written > MAX_UPLOAD_BYTES:
                    target.unlink(missing_ok=True)
                    raise HTTPException(status_code=413, detail=f"Fichier trop volumineux (max {MAX_UPLOAD_SIZE_MB} Mo)")
                f.write(chunk)
        content_hash = sha256_file(target)
        extracted = extract_document(target)
        payload = parse_match_sheet(
            extracted.text,
            extracted.tables,
            source_name=uploaded.filename,
            extractor_warnings=extracted.warnings,
            extractor_confidence=extracted.confidence,
        )
        payload = apply_import_context(payload, competition=competition, season=season, round_label=round_label)
        doc_id = db.create_document(
            original_filename=uploaded.filename or base_name,
            stored_filename=target.name,
            stored_path=str(target),
            file_type=extracted.file_type,
            sha256=content_hash,
            raw_text=extracted.text,
            extracted_json=payload,
            confidence=payload.get("_meta", {}).get("confidence", extracted.confidence),
            status="draft",
            error_message="; ".join(extracted.warnings) if extracted.warnings else None,
        )
        created_ids.append(doc_id)
    if not created_ids:
        return RedirectResponse(url="/upload?error=unsupported", status_code=303)
    if len(created_ids) == 1:
        return RedirectResponse(url=f"/review/{created_ids[0]}", status_code=303)
    return RedirectResponse(url="/documents", status_code=303)


@app.get("/documents", response_class=HTMLResponse)
def documents(request: Request) -> Response:
    if not is_admin_user(request):
        return admin_login_redirect(request)
    return templates.TemplateResponse(request, "documents.html", {"documents": db.list_documents(), "page": "documents"})


@app.get("/review/{document_id}", response_class=HTMLResponse)
def review_document(request: Request, document_id: int) -> Response:
    if not is_admin_user(request):
        return admin_login_redirect(request)
    document = db.get_document(document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document introuvable")
    try:
        payload = json.loads(document.get("extracted_json") or "{}")
    except json.JSONDecodeError:
        payload = {}
    return templates.TemplateResponse(request, "review.html", {"document": document, "payload": payload, "payload_text": json_pretty(payload), "page": "documents"})


@app.post("/review/{document_id}/save")
def save_review(request: Request, document_id: int, payload_text: str = Form(...)) -> RedirectResponse:
    require_admin(request)
    try:
        payload = json.loads(payload_text)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"JSON invalide: {exc}")
    db.update_document_payload(document_id, payload, status="draft")
    return RedirectResponse(url=f"/review/{document_id}?saved=1", status_code=303)


@app.post("/review/{document_id}/finalize")
def finalize_document(request: Request, document_id: int, payload_text: str = Form(...)) -> RedirectResponse:
    require_admin(request)
    document = db.get_document(document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document introuvable")
    if document.get("match_id"):
        return RedirectResponse(url=f"/matches/{document['match_id']}", status_code=303)
    try:
        payload = json.loads(payload_text)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"JSON invalide: {exc}")
    db.update_document_payload(document_id, payload, status="draft")
    match_ids = db.insert_matches_from_payload(payload, document_id=document_id)
    if len(match_ids) == 1:
        return RedirectResponse(url=f"/matches/{match_ids[0]}", status_code=303)
    return RedirectResponse(url="/matches", status_code=303)




@app.get("/competitions", response_class=HTMLResponse)
def competitions_page(request: Request) -> HTMLResponse:
    overview = db.list_competition_overview()
    overview_by_name = {row.get("competition"): row for row in overview}
    cards = []
    for item in COMPETITIONS:
        row = overview_by_name.get(item["value"], {})
        cards.append({**item, **row})
    extra = [row for row in overview if row.get("competition") not in COMPETITION_VALUES]
    return templates.TemplateResponse(request, "competitions.html", {"page": "competitions", "competition_cards": cards, "extra_competitions": extra})

def notification_key(item: dict[str, Any]) -> str:
    return f"{item.get('kind')}:{item.get('player')}:{item.get('match_id')}"


def notification_redirect_url(request: Request, message: str = "") -> str:
    url = str(request.headers.get("referer") or "/notifications")
    if not message:
        return url
    parts = urlsplit(url)
    query = [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True) if key != "toast"]
    query.append(("toast", message))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def build_notification_context(period: int = 10, threshold: int = 3, include_watch: int = 1, competition: str = "", season: str = "", club: str = "") -> dict[str, Any]:
    period = max(1, min(period, 50))
    threshold = max(1, min(threshold, 10))
    all_items = db.list_notifications(period_matches=period, yellow_threshold=threshold, include_watch=bool(include_watch))
    all_matches = db.list_matches()
    match_by_id = {m.get("id"): m for m in all_matches}
    states = db.get_notification_states()
    items = []
    for item in all_items:
        m = match_by_id.get(item.get("match_id"))
        if not m:
            continue
        if match_passes_filters(m, competition, season, club):
            key = notification_key(item)
            item["key"] = key
            item.update(states.get(key, {"status": "new", "admin_comment": ""}))
            items.append(item)
    stats = {
        "notifications_total": len(items),
        "notifications_critical": sum(1 for n in items if n.get("severity") == "critical"),
        "yellow_suspension_alerts": sum(1 for n in items if n.get("kind") == "yellow_suspension_risk"),
        "yellow_watch_alerts": sum(1 for n in items if n.get("kind") == "yellow_watch"),
        "red_card_alerts": sum(1 for n in items if n.get("kind") == "red_card"),
        "new_alerts": sum(1 for n in items if n.get("status") in {None, "", "new"}),
        "review_alerts": sum(1 for n in items if n.get("status") == "review"),
        "ignored_alerts": sum(1 for n in items if n.get("status") == "ignored"),
        "treated_alerts": sum(1 for n in items if n.get("status") == "treated"),
    }
    return {
        "page": "notifications",
        "notifications": items,
        "stats": stats,
        "period": period,
        "threshold": threshold,
        "include_watch": include_watch,
        "selected_competition": competition.strip(),
        "selected_season": season.strip(),
        "selected_club": club.strip(),
        "filter_options": list_filter_options(all_matches),
    }


@app.get("/notifications", response_class=HTMLResponse)
def notifications(request: Request, period: int = 10, threshold: int = 3, include_watch: int = 1, competition: str = "", season: str = "", club: str = "") -> HTMLResponse:
    return templates.TemplateResponse(request, "notifications.html", build_notification_context(period, threshold, include_watch, competition, season, club))


@app.get("/api/notifications")
def api_notifications(period: int = 10, threshold: int = 3, include_watch: int = 1) -> list[dict[str, Any]]:
    return db.list_notifications(period_matches=period, yellow_threshold=threshold, include_watch=bool(include_watch))

@app.get("/matches", response_class=HTMLResponse)
def matches(request: Request, competition: str = "", season: str = "", club: str = "", date_from: str = "", date_to: str = "", round_label: str = "", q: str = "") -> HTMLResponse:
    all_matches = db.list_matches()
    rows = [m for m in all_matches if match_passes_filters(m, competition, season, club, date_from, date_to, round_label, q)]
    if not is_admin_user(request):
        rows = [m for m in rows if db.public_status(m.get("status"))]
    return templates.TemplateResponse(
        request,
        "matches.html",
        {
            "matches": rows,
            "page": "matches",
            "selected_competition": competition.strip(),
            "selected_season": season.strip(),
            "selected_club": club.strip(),
            "date_from": date_from.strip(), "date_to": date_to.strip(), "selected_round": round_label.strip(), "q": q.strip(),
            "filter_options": list_filter_options(all_matches),
            "competitions": COMPETITIONS,
        },
    )


@app.get("/matches/{match_id}", response_class=HTMLResponse)
def match_detail(request: Request, match_id: int) -> HTMLResponse:
    detail = db.get_match_detail(match_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Match introuvable")
    match_row = detail.get("match") or {}
    if not is_admin_user(request) and not db.public_status(match_row.get("status")):
        raise HTTPException(status_code=404, detail="Match non publié")
    return templates.TemplateResponse(request, "match_detail.html", {"detail": detail, "page": "matches", "completeness_info": db.match_completeness(match_id)})


@app.post("/matches/{match_id}/observations")
def add_observation(request: Request, match_id: int, minute: str = Form(""), author: str = Form(""), severity: str = Form("note"), note: str = Form(...)) -> RedirectResponse:
    require_admin(request)
    minute_int = None
    if minute.strip():
        try:
            minute_int = int(minute.strip().replace("'", ""))
        except ValueError:
            minute_int = None
    db.add_observation(match_id, minute_int, author or None, note, severity)
    return RedirectResponse(url=f"/matches/{match_id}#observations", status_code=303)


@app.get("/players", response_class=HTMLResponse)
def players(request: Request, competition: str = "", season: str = "", club: str = "") -> HTMLResponse:
    all_matches = db.list_matches()
    rows = db.list_players_filtered(competition=competition, season=season, club=club) if (competition or season or club) else db.list_players()
    return templates.TemplateResponse(request, "players.html", {
        "players": rows, "page": "players",
        "selected_competition": competition.strip(), "selected_season": season.strip(), "selected_club": club.strip(),
        "filter_options": list_filter_options(all_matches),
    })


@app.get("/events", response_class=HTMLResponse)
def events(request: Request, competition: str = "", season: str = "", club: str = "", event_type: str = "") -> HTMLResponse:
    all_matches = db.list_matches()
    rows = db.list_events_filtered(competition=competition, season=season, club=club, event_type=event_type) if (competition or season or club or event_type) else db.list_events()
    return templates.TemplateResponse(request, "events.html", {
        "events": rows, "page": "events",
        "selected_competition": competition.strip(), "selected_season": season.strip(), "selected_club": club.strip(), "selected_event_type": event_type.strip(),
        "filter_options": list_filter_options(all_matches),
    })


@app.get("/officials", response_class=HTMLResponse)
def officials(request: Request, competition: str = "", season: str = "", club: str = "") -> HTMLResponse:
    all_matches = db.list_matches()
    rows = db.list_officials_filtered(competition=competition, season=season, club=club) if (competition or season or club) else db.list_officials()
    return templates.TemplateResponse(request, "officials.html", {
        "officials": rows, "page": "officials",
        "selected_competition": competition.strip(), "selected_season": season.strip(), "selected_club": club.strip(),
        "filter_options": list_filter_options(all_matches),
    })




@app.get("/admin", response_class=HTMLResponse)
def admin_center(request: Request) -> Response:
    if not is_admin_user(request):
        return admin_login_redirect(request)
    return templates.TemplateResponse(request, "admin_center.html", {"page": "admin", "todo": db.admin_todo_board(), "stats": db.dashboard_stats(), "missing": db.list_missing_data(), "activity": db.recent_activity()})


@app.get("/search", response_class=HTMLResponse)
def search_page(request: Request, q: str = "") -> HTMLResponse:
    results = db.global_search(q) if q.strip() else {"matches": [], "players": [], "clubs": [], "officials": [], "events": [], "documents": []}
    return templates.TemplateResponse(request, "search.html", {"page": "search", "q": q, "results": results, "suggestions": ["EST", "Club Africain", "carton rouge", "Ligue 1", "arbitre"]})


@app.get("/clubs", response_class=HTMLResponse)
def clubs_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "clubs.html", {"page": "clubs", "clubs": db.list_clubs()})


@app.get("/clubs/{club_id}", response_class=HTMLResponse)
def club_detail(request: Request, club_id: int) -> HTMLResponse:
    detail = db.get_club_detail(club_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Club introuvable")
    return templates.TemplateResponse(request, "club_detail.html", {"page": "clubs", "detail": detail})


@app.get("/players/{player_id}", response_class=HTMLResponse)
def player_detail(request: Request, player_id: int) -> HTMLResponse:
    detail = db.get_player_detail(player_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Joueur introuvable")
    return templates.TemplateResponse(request, "player_detail.html", {"page": "players", "detail": detail})


@app.get("/officials/{official_id}", response_class=HTMLResponse)
def official_detail(request: Request, official_id: int) -> HTMLResponse:
    detail = db.get_official_detail(official_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Officiel introuvable")
    return templates.TemplateResponse(request, "official_detail.html", {"page": "officials", "detail": detail})


@app.post("/notifications/state")
def notification_state(request: Request, key: str = Form(...), status: str = Form("treated"), comment: str = Form("")) -> RedirectResponse:
    require_admin(request)
    db.upsert_notification_state(key, status=status, comment=comment)
    return RedirectResponse(url=notification_redirect_url(request, "Action enregistrée"), status_code=303)


@app.post("/notifications/bulk")
async def notification_bulk_state(request: Request) -> RedirectResponse:
    require_admin(request)
    form = await request.form()
    keys = [str(key) for key in form.getlist("keys") if str(key).strip()]
    status = str(form.get("status") or "review")
    if status not in {"new", "review", "treated", "ignored"}:
        status = "review"
    comment = str(form.get("comment") or "").strip()
    if not keys:
        return RedirectResponse(url=notification_redirect_url(request, "Aucune alerte sélectionnée"), status_code=303)
    for key in keys:
        db.upsert_notification_state(key, status=status, comment=comment)
    return RedirectResponse(url=notification_redirect_url(request, f"{len(keys)} alerte(s) mise(s) à jour"), status_code=303)


@app.get("/export/risk-players.csv")
def export_risk_players(request: Request) -> Response:
    require_admin(request)
    items = db.list_notifications(period_matches=10, yellow_threshold=3, include_watch=True)
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["type", "severity", "player", "club", "match_id", "message"])
    for n in items:
        writer.writerow([n.get("kind"), n.get("severity"), n.get("player"), n.get("club"), n.get("match_id"), n.get("message")])
    return Response(content=output.getvalue(), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=risk-players.csv"})


@app.get("/discipline", response_class=HTMLResponse)
def discipline_analysis_page(request: Request, competition: str = "", season: str = "", club: str = "") -> HTMLResponse:
    all_matches = db.list_matches()
    return templates.TemplateResponse(request, "discipline_analysis.html", {
        "page": "discipline",
        "analysis": db.discipline_analysis(competition=competition, season=season, club=club),
        "filter_options": list_filter_options(all_matches),
        "selected_competition": competition.strip(),
        "selected_season": season.strip(),
        "selected_club": club.strip(),
    })

@app.post("/matches/{match_id}/status")
def update_match_status_route(request: Request, match_id: int, status: str = Form("to_review")) -> RedirectResponse:
    require_admin(request)
    db.update_match_status(match_id, status)
    return RedirectResponse(url=f"/matches/{match_id}?toast=Statut mis à jour", status_code=303)




app.include_router(auth_router)
app.include_router(public_pages_router)
app.include_router(api_export_router)
