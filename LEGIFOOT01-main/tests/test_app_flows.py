from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("itsdangerous")

from fastapi.testclient import TestClient

from app import database as db
from app import main


def test_admin_manual_entry_feeds_notifications_api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEGIFOOT_ADMIN_PASSWORD", "admin123")
    monkeypatch.setenv("LEGIFOOT_SECRET_KEY", "test-secret")

    db.DB_PATH = tmp_path / "data" / "matchsheets.sqlite3"
    db.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    main.UPLOAD_DIR = tmp_path / "uploads"
    main.EXPORT_DIR = tmp_path / "exports"
    main.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    main.EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    db.init_db()

    with TestClient(main.app) as client:
        login_response = client.post(
            "/login",
            data={"password": "admin123", "next": "/manual"},
            follow_redirects=False,
        )
        assert login_response.status_code == 303
        assert login_response.headers["location"] == "/manual"

        manual_response = client.post(
            "/manual",
            data={
                "competition": "Ligue 1 Professionnelle",
                "season": "2025-2026",
                "round_label": "J1",
                "status": "played",
                "home_team": "Club Discipline A",
                "away_team": "Club Discipline B",
                "score_home": "0",
                "score_away": "0",
                "home_players": "8; Joueur Sous Surveillance; LIC08; titulaire; non; non; Milieu; TN;",
                "cards": "\n".join(
                    [
                        "10; home; Joueur Sous Surveillance; jaune; faute",
                        "35; home; Joueur Sous Surveillance; jaune; contestation",
                        "70; home; Joueur Sous Surveillance; jaune; antijeu",
                    ]
                ),
            },
            follow_redirects=False,
        )
        assert manual_response.status_code == 303
        assert manual_response.headers["location"].startswith("/matches/")

        matches_response = client.get("/api/matches")
        assert matches_response.status_code == 200
        matches = matches_response.json()
        assert len(matches) == 1
        assert matches[0]["home_team"] == "Club Discipline A"
        assert matches[0]["away_team"] == "Club Discipline B"

        notifications_response = client.get("/api/notifications?threshold=3&include_watch=1")
        assert notifications_response.status_code == 200
        notifications = notifications_response.json()
        assert len(notifications) == 1
        assert notifications[0]["severity"] == "critical"
        assert notifications[0]["player"] == "Joueur Sous Surveillance"
        assert notifications[0]["count"] == 3
