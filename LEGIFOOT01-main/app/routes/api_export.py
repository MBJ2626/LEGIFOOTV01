from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse

from app import database as db

router = APIRouter()

@router.get("/api/matches")
def api_matches() -> list[dict[str, Any]]:
    return db.list_matches()


@router.get("/api/players")
def api_players() -> list[dict[str, Any]]:
    return db.list_players()


@router.get("/api/events")
def api_events() -> list[dict[str, Any]]:
    return db.list_events()


@router.get("/export/{table_name}.csv")
def export_csv(request: Request, table_name: str) -> FileResponse:
    from app.main import EXPORT_DIR, require_admin

    require_admin(request)
    output = EXPORT_DIR / f"{table_name}.csv"
    try:
        db.export_table_csv(table_name, output)
    except ValueError as exc:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail=str(exc))
    return FileResponse(output, filename=output.name, media_type="text/csv")
