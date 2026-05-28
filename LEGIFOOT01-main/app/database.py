from __future__ import annotations

import csv
import json
import os
import sqlite3
import unicodedata
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("LEGIFOOT_DATA_DIR", BASE_DIR / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = Path(os.getenv("LEGIFOOT_DB_PATH", DATA_DIR / "matchsheets.sqlite3"))
DB_PATH.parent.mkdir(parents=True, exist_ok=True)


def now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def normalize_key(value: str | None) -> str:
    if not value:
        return ""
    value = unicodedata.normalize("NFKD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return " ".join(value.lower().strip().replace("'", " ").replace("-", " ").split())


@contextmanager
def get_conn() -> Iterable[sqlite3.Connection]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                original_filename TEXT NOT NULL,
                stored_filename TEXT NOT NULL,
                stored_path TEXT NOT NULL,
                file_type TEXT,
                sha256 TEXT,
                raw_text TEXT,
                extracted_json TEXT,
                status TEXT NOT NULL DEFAULT 'draft',
                confidence REAL DEFAULT 0,
                match_id INTEGER,
                error_message TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS clubs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                normalized_name TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS stadiums (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                city TEXT,
                normalized_name TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS players (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                full_name TEXT NOT NULL,
                normalized_name TEXT NOT NULL,
                license_number TEXT,
                birth_date TEXT,
                position TEXT,
                nationality TEXT,
                notes TEXT,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_players_norm ON players(normalized_name);
            CREATE INDEX IF NOT EXISTS idx_players_license ON players(license_number);

            CREATE TABLE IF NOT EXISTS staff (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                club_id INTEGER,
                full_name TEXT NOT NULL,
                normalized_name TEXT NOT NULL,
                role TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(club_id) REFERENCES clubs(id)
            );

            CREATE TABLE IF NOT EXISTS officials (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                full_name TEXT NOT NULL,
                normalized_name TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS matches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                competition TEXT,
                season TEXT,
                round_label TEXT,
                match_date TEXT,
                match_time TEXT,
                stadium_id INTEGER,
                home_club_id INTEGER,
                away_club_id INTEGER,
                score_home INTEGER,
                score_away INTEGER,
                halftime_home INTEGER,
                halftime_away INTEGER,
                status TEXT DEFAULT 'played',
                observations TEXT,
                notes TEXT,
                document_id INTEGER,
                created_at TEXT NOT NULL,
                FOREIGN KEY(stadium_id) REFERENCES stadiums(id),
                FOREIGN KEY(home_club_id) REFERENCES clubs(id),
                FOREIGN KEY(away_club_id) REFERENCES clubs(id),
                FOREIGN KEY(document_id) REFERENCES documents(id)
            );

            CREATE TABLE IF NOT EXISTS match_players (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                match_id INTEGER NOT NULL,
                club_id INTEGER NOT NULL,
                player_id INTEGER NOT NULL,
                number INTEGER,
                sheet_role TEXT,
                starter INTEGER DEFAULT 0,
                substitute INTEGER DEFAULT 0,
                captain INTEGER DEFAULT 0,
                goalkeeper INTEGER DEFAULT 0,
                minute_in INTEGER,
                minute_out INTEGER,
                notes TEXT,
                FOREIGN KEY(match_id) REFERENCES matches(id) ON DELETE CASCADE,
                FOREIGN KEY(club_id) REFERENCES clubs(id),
                FOREIGN KEY(player_id) REFERENCES players(id)
            );

            CREATE TABLE IF NOT EXISTS match_staff (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                match_id INTEGER NOT NULL,
                club_id INTEGER NOT NULL,
                staff_id INTEGER NOT NULL,
                role TEXT,
                FOREIGN KEY(match_id) REFERENCES matches(id) ON DELETE CASCADE,
                FOREIGN KEY(club_id) REFERENCES clubs(id),
                FOREIGN KEY(staff_id) REFERENCES staff(id)
            );

            CREATE TABLE IF NOT EXISTS match_officials (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                match_id INTEGER NOT NULL,
                official_id INTEGER NOT NULL,
                role TEXT,
                FOREIGN KEY(match_id) REFERENCES matches(id) ON DELETE CASCADE,
                FOREIGN KEY(official_id) REFERENCES officials(id)
            );

            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                match_id INTEGER NOT NULL,
                club_id INTEGER,
                player_id INTEGER,
                related_player_id INTEGER,
                minute INTEGER,
                stoppage INTEGER,
                event_type TEXT NOT NULL,
                card_color TEXT,
                detail TEXT,
                FOREIGN KEY(match_id) REFERENCES matches(id) ON DELETE CASCADE,
                FOREIGN KEY(club_id) REFERENCES clubs(id),
                FOREIGN KEY(player_id) REFERENCES players(id),
                FOREIGN KEY(related_player_id) REFERENCES players(id)
            );

            CREATE TABLE IF NOT EXISTS observations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                match_id INTEGER NOT NULL,
                minute INTEGER,
                author TEXT,
                note TEXT NOT NULL,
                severity TEXT DEFAULT 'note',
                created_at TEXT NOT NULL,
                FOREIGN KEY(match_id) REFERENCES matches(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS notification_states (
                key TEXT PRIMARY KEY,
                status TEXT NOT NULL DEFAULT 'new',
                admin_comment TEXT,
                updated_at TEXT NOT NULL
            );
            """
        )


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {k: row[k] for k in row.keys()}


def rows_to_dicts(rows: Iterable[sqlite3.Row]) -> list[dict[str, Any]]:
    return [row_to_dict(row) for row in rows]  # type: ignore[arg-type]


def create_document(
    *,
    original_filename: str,
    stored_filename: str,
    stored_path: str,
    file_type: str,
    sha256: str,
    raw_text: str,
    extracted_json: dict[str, Any],
    confidence: float,
    status: str = "draft",
    error_message: str | None = None,
) -> int:
    init_db()
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO documents (
                original_filename, stored_filename, stored_path, file_type, sha256,
                raw_text, extracted_json, status, confidence, error_message, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                original_filename,
                stored_filename,
                stored_path,
                file_type,
                sha256,
                raw_text,
                json.dumps(extracted_json, ensure_ascii=False, indent=2),
                status,
                confidence,
                error_message,
                now_iso(),
            ),
        )
        return int(cur.lastrowid)


def update_document_payload(document_id: int, payload: dict[str, Any], status: str | None = None) -> None:
    init_db()
    with get_conn() as conn:
        if status:
            conn.execute(
                "UPDATE documents SET extracted_json = ?, status = ? WHERE id = ?",
                (json.dumps(payload, ensure_ascii=False, indent=2), status, document_id),
            )
        else:
            conn.execute(
                "UPDATE documents SET extracted_json = ? WHERE id = ?",
                (json.dumps(payload, ensure_ascii=False, indent=2), document_id),
            )


def get_document(document_id: int) -> dict[str, Any] | None:
    init_db()
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()
        return row_to_dict(row)


def list_documents(limit: int = 50) -> list[dict[str, Any]]:
    init_db()
    with get_conn() as conn:
        return rows_to_dicts(
            conn.execute(
                """
                SELECT d.*, m.id AS finalized_match_id
                FROM documents d
                LEFT JOIN matches m ON m.id = d.match_id
                ORDER BY d.id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        )


def upsert_club(conn: sqlite3.Connection, name: str | None) -> int | None:
    if not name or not name.strip():
        return None
    normalized = normalize_key(name)
    row = conn.execute("SELECT id, name FROM clubs WHERE normalized_name = ?", (normalized,)).fetchone()
    if row:
        return int(row["id"])
    cur = conn.execute(
        "INSERT INTO clubs (name, normalized_name, created_at) VALUES (?, ?, ?)",
        (name.strip(), normalized, now_iso()),
    )
    return int(cur.lastrowid)


def upsert_stadium(conn: sqlite3.Connection, name: str | None, city: str | None = None) -> int | None:
    if not name or not name.strip():
        return None
    normalized = normalize_key(name)
    row = conn.execute("SELECT id FROM stadiums WHERE normalized_name = ?", (normalized,)).fetchone()
    if row:
        if city:
            conn.execute("UPDATE stadiums SET city = COALESCE(NULLIF(city, ''), ?) WHERE id = ?", (city, row["id"]))
        return int(row["id"])
    cur = conn.execute(
        "INSERT INTO stadiums (name, city, normalized_name, created_at) VALUES (?, ?, ?, ?)",
        (name.strip(), city, normalized, now_iso()),
    )
    return int(cur.lastrowid)


def upsert_player(conn: sqlite3.Connection, player: dict[str, Any]) -> int | None:
    name = (player.get("name") or player.get("full_name") or "").strip()
    if not name:
        return None
    license_number = str(player.get("license_number") or "").strip() or None
    normalized = normalize_key(name)
    row = None
    if license_number:
        row = conn.execute("SELECT id FROM players WHERE license_number = ?", (license_number,)).fetchone()
    if row is None:
        row = conn.execute("SELECT id FROM players WHERE normalized_name = ? AND COALESCE(license_number, '') = COALESCE(?, '')", (normalized, license_number)).fetchone()
    if row:
        player_id = int(row["id"])
        conn.execute(
            """
            UPDATE players
            SET birth_date = COALESCE(NULLIF(birth_date, ''), ?),
                position = COALESCE(NULLIF(position, ''), ?),
                nationality = COALESCE(NULLIF(nationality, ''), ?),
                notes = COALESCE(NULLIF(notes, ''), ?)
            WHERE id = ?
            """,
            (
                player.get("birth_date"),
                player.get("position"),
                player.get("nationality"),
                player.get("notes"),
                player_id,
            ),
        )
        return player_id
    cur = conn.execute(
        """
        INSERT INTO players (full_name, normalized_name, license_number, birth_date, position, nationality, notes, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            name,
            normalized,
            license_number,
            player.get("birth_date"),
            player.get("position"),
            player.get("nationality"),
            player.get("notes"),
            now_iso(),
        ),
    )
    return int(cur.lastrowid)


def upsert_official(conn: sqlite3.Connection, name: str | None) -> int | None:
    if not name or not name.strip():
        return None
    normalized = normalize_key(name)
    row = conn.execute("SELECT id FROM officials WHERE normalized_name = ?", (normalized,)).fetchone()
    if row:
        return int(row["id"])
    cur = conn.execute(
        "INSERT INTO officials (full_name, normalized_name, created_at) VALUES (?, ?, ?)",
        (name.strip(), normalized, now_iso()),
    )
    return int(cur.lastrowid)


def upsert_staff(conn: sqlite3.Connection, club_id: int | None, name: str | None, role: str | None) -> int | None:
    if not name or not name.strip():
        return None
    normalized = normalize_key(name)
    row = conn.execute(
        "SELECT id FROM staff WHERE normalized_name = ? AND COALESCE(club_id, 0) = COALESCE(?, 0)",
        (normalized, club_id),
    ).fetchone()
    if row:
        return int(row["id"])
    cur = conn.execute(
        "INSERT INTO staff (club_id, full_name, normalized_name, role, created_at) VALUES (?, ?, ?, ?, ?)",
        (club_id, name.strip(), normalized, role, now_iso()),
    )
    return int(cur.lastrowid)


def _to_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(str(value).strip().replace("'", ""))
    except (ValueError, TypeError):
        return None


def _truthy(value: Any) -> int:
    if isinstance(value, bool):
        return int(value)
    if value is None:
        return 0
    return 1 if str(value).strip().lower() in {"1", "true", "vrai", "yes", "oui", "x", "c", "capitaine", "g", "gardien"} else 0


def insert_match_from_payload(payload: dict[str, Any], document_id: int | None = None, update_document: bool = True) -> int:
    init_db()
    with get_conn() as conn:
        match = payload.get("match", {}) or {}
        teams = payload.get("teams", []) or []
        home_team = next((t for t in teams if str(t.get("side", "")).lower() in {"home", "domicile"}), teams[0] if teams else {})
        away_team = next((t for t in teams if str(t.get("side", "")).lower() in {"away", "extérieur", "exterieur"}), teams[1] if len(teams) > 1 else {})

        home_id = upsert_club(conn, home_team.get("name") or match.get("home_team"))
        away_id = upsert_club(conn, away_team.get("name") or match.get("away_team"))
        stadium_id = upsert_stadium(conn, match.get("stadium"), match.get("city"))

        cur = conn.execute(
            """
            INSERT INTO matches (
                competition, season, round_label, match_date, match_time, stadium_id,
                home_club_id, away_club_id, score_home, score_away,
                halftime_home, halftime_away, status, observations, notes, document_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                match.get("competition"),
                match.get("season"),
                match.get("round"),
                match.get("date"),
                match.get("time"),
                stadium_id,
                home_id,
                away_id,
                _to_int(match.get("score_home")),
                _to_int(match.get("score_away")),
                _to_int(match.get("halftime_home")),
                _to_int(match.get("halftime_away")),
                match.get("status") or "played",
                match.get("observations"),
                match.get("notes"),
                document_id,
                now_iso(),
            ),
        )
        match_id = int(cur.lastrowid)

        team_id_by_name: dict[str, int] = {}
        player_id_by_name_and_team: dict[tuple[str, int | None], int] = {}
        club_id_by_side = {"home": home_id, "away": away_id, "domicile": home_id, "exterieur": away_id, "extérieur": away_id}

        for team in teams:
            side = normalize_key(team.get("side"))
            club_id = club_id_by_side.get(side) or upsert_club(conn, team.get("name"))
            if team.get("name") and club_id:
                team_id_by_name[normalize_key(team.get("name"))] = club_id
            for player in team.get("players", []) or []:
                player_id = upsert_player(conn, player)
                if not player_id or not club_id:
                    continue
                role = player.get("role") or player.get("sheet_role") or ("titulaire" if player.get("starter") else "remplaçant")
                starter = _truthy(player.get("starter")) or (1 if normalize_key(role) in {"titulaire", "starter"} else 0)
                substitute = _truthy(player.get("substitute")) or (1 if normalize_key(role) in {"remplacant", "remplacant", "substitute", "bench"} else 0)
                conn.execute(
                    """
                    INSERT INTO match_players (
                        match_id, club_id, player_id, number, sheet_role, starter, substitute,
                        captain, goalkeeper, minute_in, minute_out, notes
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        match_id,
                        club_id,
                        player_id,
                        _to_int(player.get("number")),
                        role,
                        starter,
                        substitute,
                        _truthy(player.get("captain")),
                        _truthy(player.get("goalkeeper")),
                        _to_int(player.get("minute_in")),
                        _to_int(player.get("minute_out")),
                        player.get("notes"),
                    ),
                )
                player_id_by_name_and_team[(normalize_key(player.get("name") or player.get("full_name")), club_id)] = player_id

            for staff_member in team.get("staff", []) or []:
                staff_id = upsert_staff(conn, club_id, staff_member.get("name"), staff_member.get("role"))
                if staff_id and club_id:
                    conn.execute(
                        "INSERT INTO match_staff (match_id, club_id, staff_id, role) VALUES (?, ?, ?, ?)",
                        (match_id, club_id, staff_id, staff_member.get("role")),
                    )

        for official in payload.get("officials", []) or []:
            official_id = upsert_official(conn, official.get("name") or official.get("full_name"))
            if official_id:
                conn.execute(
                    "INSERT INTO match_officials (match_id, official_id, role) VALUES (?, ?, ?)",
                    (match_id, official_id, official.get("role")),
                )

        def resolve_club_id(team_value: Any) -> int | None:
            if not team_value:
                return None
            key = normalize_key(team_value)
            if key in {"home", "domicile"}:
                return home_id
            if key in {"away", "extérieur", "exterieur"}:
                return away_id
            return team_id_by_name.get(key) or upsert_club(conn, str(team_value))

        for event in payload.get("events", []) or []:
            club_id = resolve_club_id(event.get("team"))
            player_id = None
            related_player_id = None
            if event.get("player"):
                player_key = normalize_key(event.get("player"))
                player_id = player_id_by_name_and_team.get((player_key, club_id))
                if player_id is None:
                    player_id = upsert_player(conn, {"name": event.get("player")})
            if event.get("related_player"):
                related_key = normalize_key(event.get("related_player"))
                related_player_id = player_id_by_name_and_team.get((related_key, club_id))
                if related_player_id is None:
                    related_player_id = upsert_player(conn, {"name": event.get("related_player")})
            conn.execute(
                """
                INSERT INTO events (
                    match_id, club_id, player_id, related_player_id, minute, stoppage,
                    event_type, card_color, detail
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    match_id,
                    club_id,
                    player_id,
                    related_player_id,
                    _to_int(event.get("minute")),
                    _to_int(event.get("stoppage")),
                    event.get("event_type") or event.get("type") or "note",
                    event.get("card_color"),
                    event.get("detail"),
                ),
            )

        for observation in payload.get("observations", []) or []:
            note = observation.get("note") or observation.get("text")
            if not note:
                continue
            conn.execute(
                "INSERT INTO observations (match_id, minute, author, note, severity, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (match_id, _to_int(observation.get("minute")), observation.get("author"), note, observation.get("severity") or "note", now_iso()),
            )

        if document_id and update_document:
            conn.execute("UPDATE documents SET status = 'finalized', match_id = ? WHERE id = ?", (match_id, document_id))
        return match_id


def insert_matches_from_payload(payload: dict[str, Any], document_id: int | None = None) -> list[int]:
    """Insert either a single-match payload or a batch payload produced from a multi-match PDF."""
    if payload.get("matches") and isinstance(payload.get("matches"), list):
        match_ids: list[int] = []
        for child_payload in payload.get("matches", []) or []:
            if not isinstance(child_payload, dict):
                continue
            match_ids.append(insert_match_from_payload(child_payload, document_id=document_id, update_document=False))
        if document_id and match_ids:
            init_db()
            with get_conn() as conn:
                conn.execute("UPDATE documents SET status = 'finalized', match_id = ? WHERE id = ?", (match_ids[0], document_id))
        return match_ids
    return [insert_match_from_payload(payload, document_id=document_id, update_document=True)]


def dashboard_stats() -> dict[str, Any]:
    init_db()
    with get_conn() as conn:
        stats = {
            "matches": conn.execute("SELECT COUNT(*) AS c FROM matches").fetchone()["c"],
            "clubs": conn.execute("SELECT COUNT(*) AS c FROM clubs").fetchone()["c"],
            "players": conn.execute("SELECT COUNT(*) AS c FROM players").fetchone()["c"],
            "events": conn.execute("SELECT COUNT(*) AS c FROM events").fetchone()["c"],
            "yellow_cards": conn.execute("SELECT COUNT(*) AS c FROM events WHERE event_type = 'card' AND card_color = 'yellow'").fetchone()["c"],
            "red_cards": conn.execute("SELECT COUNT(*) AS c FROM events WHERE event_type = 'card' AND card_color = 'red'").fetchone()["c"],
        }
        notification_overview = notification_stats(period_matches=10, yellow_threshold=3)
        stats.update(notification_overview)
        recent = conn.execute(
            """
            SELECT m.*, hc.name AS home_team, ac.name AS away_team, s.name AS stadium
            FROM matches m
            LEFT JOIN clubs hc ON hc.id = m.home_club_id
            LEFT JOIN clubs ac ON ac.id = m.away_club_id
            LEFT JOIN stadiums s ON s.id = m.stadium_id
            ORDER BY COALESCE(m.match_date, '' ) DESC, m.id DESC
            LIMIT 8
            """
        ).fetchall()
        cards_by_team = conn.execute(
            """
            SELECT c.name AS club, SUM(CASE WHEN e.card_color = 'yellow' THEN 1 ELSE 0 END) AS yellow,
                   SUM(CASE WHEN e.card_color = 'red' THEN 1 ELSE 0 END) AS red
            FROM events e
            LEFT JOIN clubs c ON c.id = e.club_id
            WHERE e.event_type = 'card'
            GROUP BY c.name
            ORDER BY yellow + red DESC
            LIMIT 10
            """
        ).fetchall()
        goals_by_team = conn.execute(
            """
            SELECT c.name AS club, COUNT(*) AS goals
            FROM events e
            LEFT JOIN clubs c ON c.id = e.club_id
            WHERE e.event_type = 'goal'
            GROUP BY c.name
            ORDER BY goals DESC
            LIMIT 10
            """
        ).fetchall()
        return {**stats, "recent_matches": rows_to_dicts(recent), "cards_by_team": rows_to_dicts(cards_by_team), "goals_by_team": rows_to_dicts(goals_by_team), "competition_overview": list_competition_overview()}



def list_competition_overview() -> list[dict[str, Any]]:
    init_db()
    with get_conn() as conn:
        rows = rows_to_dicts(
            conn.execute(
                """
                SELECT COALESCE(NULLIF(TRIM(competition), ''), 'Non classée') AS competition,
                       COUNT(*) AS matches,
                       SUM(CASE WHEN status = 'played' THEN 1 ELSE 0 END) AS played_matches
                FROM matches
                GROUP BY COALESCE(NULLIF(TRIM(competition), ''), 'Non classée')
                ORDER BY competition
                """
            ).fetchall()
        )
        for row in rows:
            comp = row["competition"]
            event_counts = row_to_dict(
                conn.execute(
                    """
                    SELECT
                        SUM(CASE WHEN e.event_type = 'goal' THEN 1 ELSE 0 END) AS goals,
                        SUM(CASE WHEN e.event_type = 'card' AND e.card_color = 'yellow' THEN 1 ELSE 0 END) AS yellow_cards,
                        SUM(CASE WHEN e.event_type = 'card' AND e.card_color = 'red' THEN 1 ELSE 0 END) AS red_cards
                    FROM matches m
                    LEFT JOIN events e ON e.match_id = m.id
                    WHERE COALESCE(NULLIF(TRIM(m.competition), ''), 'Non classée') = ?
                    """,
                    (comp,),
                ).fetchone()
            ) or {}
            player_counts = row_to_dict(
                conn.execute(
                    """
                    SELECT COUNT(DISTINCT mp.player_id) AS players
                    FROM matches m
                    LEFT JOIN match_players mp ON mp.match_id = m.id
                    WHERE COALESCE(NULLIF(TRIM(m.competition), ''), 'Non classée') = ?
                    """,
                    (comp,),
                ).fetchone()
            ) or {}
            row.update(event_counts)
            row.update(player_counts)
        return rows


def list_matches() -> list[dict[str, Any]]:
    init_db()
    with get_conn() as conn:
        return rows_to_dicts(
            conn.execute(
                """
                SELECT m.*, hc.name AS home_team, ac.name AS away_team, s.name AS stadium, s.city AS city
                FROM matches m
                LEFT JOIN clubs hc ON hc.id = m.home_club_id
                LEFT JOIN clubs ac ON ac.id = m.away_club_id
                LEFT JOIN stadiums s ON s.id = m.stadium_id
                ORDER BY COALESCE(m.match_date, '') DESC, COALESCE(m.match_time, '') DESC, m.id DESC
                """
            ).fetchall()
        )


def get_match_detail(match_id: int) -> dict[str, Any] | None:
    init_db()
    with get_conn() as conn:
        match = row_to_dict(
            conn.execute(
                """
                SELECT m.*, hc.name AS home_team, ac.name AS away_team, s.name AS stadium, s.city AS city, d.original_filename
                FROM matches m
                LEFT JOIN clubs hc ON hc.id = m.home_club_id
                LEFT JOIN clubs ac ON ac.id = m.away_club_id
                LEFT JOIN stadiums s ON s.id = m.stadium_id
                LEFT JOIN documents d ON d.id = m.document_id
                WHERE m.id = ?
                """,
                (match_id,),
            ).fetchone()
        )
        if not match:
            return None
        players = rows_to_dicts(
            conn.execute(
                """
                SELECT mp.*, p.full_name, p.license_number, p.birth_date, p.position, p.nationality, c.name AS club
                FROM match_players mp
                JOIN players p ON p.id = mp.player_id
                JOIN clubs c ON c.id = mp.club_id
                WHERE mp.match_id = ?
                ORDER BY c.name, mp.starter DESC, COALESCE(mp.number, 999), p.full_name
                """,
                (match_id,),
            ).fetchall()
        )
        events = rows_to_dicts(
            conn.execute(
                """
                SELECT e.*, c.name AS club, p.full_name AS player, rp.full_name AS related_player
                FROM events e
                LEFT JOIN clubs c ON c.id = e.club_id
                LEFT JOIN players p ON p.id = e.player_id
                LEFT JOIN players rp ON rp.id = e.related_player_id
                WHERE e.match_id = ?
                ORDER BY COALESCE(e.minute, 999), e.id
                """,
                (match_id,),
            ).fetchall()
        )
        officials = rows_to_dicts(
            conn.execute(
                """
                SELECT mo.role, o.full_name
                FROM match_officials mo
                JOIN officials o ON o.id = mo.official_id
                WHERE mo.match_id = ?
                ORDER BY mo.id
                """,
                (match_id,),
            ).fetchall()
        )
        staff = rows_to_dicts(
            conn.execute(
                """
                SELECT ms.role, st.full_name, c.name AS club
                FROM match_staff ms
                JOIN staff st ON st.id = ms.staff_id
                JOIN clubs c ON c.id = ms.club_id
                WHERE ms.match_id = ?
                ORDER BY c.name, ms.role
                """,
                (match_id,),
            ).fetchall()
        )
        observations = rows_to_dicts(conn.execute("SELECT * FROM observations WHERE match_id = ? ORDER BY id DESC", (match_id,)).fetchall())
        return {"match": match, "players": players, "events": events, "officials": officials, "staff": staff, "observations": observations}


def add_observation(match_id: int, minute: int | None, author: str | None, note: str, severity: str = "note") -> None:
    init_db()
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO observations (match_id, minute, author, note, severity, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (match_id, minute, author, note, severity, now_iso()),
        )


def list_players() -> list[dict[str, Any]]:
    init_db()
    with get_conn() as conn:
        return rows_to_dicts(
            conn.execute(
                """
                SELECT p.*, COUNT(DISTINCT mp.match_id) AS matches_played,
                       SUM(CASE WHEN mp.starter = 1 THEN 1 ELSE 0 END) AS starts,
                       SUM(CASE WHEN e.event_type = 'goal' THEN 1 ELSE 0 END) AS goals,
                       SUM(CASE WHEN e.event_type = 'card' AND e.card_color = 'yellow' THEN 1 ELSE 0 END) AS yellow_cards,
                       SUM(CASE WHEN e.event_type = 'card' AND e.card_color = 'red' THEN 1 ELSE 0 END) AS red_cards
                FROM players p
                LEFT JOIN match_players mp ON mp.player_id = p.id
                LEFT JOIN events e ON e.player_id = p.id
                GROUP BY p.id
                ORDER BY p.full_name
                """
            ).fetchall()
        )


def list_events() -> list[dict[str, Any]]:
    init_db()
    with get_conn() as conn:
        return rows_to_dicts(
            conn.execute(
                """
                SELECT e.*, m.match_date, hc.name AS home_team, ac.name AS away_team,
                       c.name AS club, p.full_name AS player, rp.full_name AS related_player
                FROM events e
                JOIN matches m ON m.id = e.match_id
                LEFT JOIN clubs hc ON hc.id = m.home_club_id
                LEFT JOIN clubs ac ON ac.id = m.away_club_id
                LEFT JOIN clubs c ON c.id = e.club_id
                LEFT JOIN players p ON p.id = e.player_id
                LEFT JOIN players rp ON rp.id = e.related_player_id
                ORDER BY COALESCE(m.match_date, '') DESC, e.match_id DESC, COALESCE(e.minute, 999), e.id
                """
            ).fetchall()
        )


def list_officials() -> list[dict[str, Any]]:
    init_db()
    with get_conn() as conn:
        return rows_to_dicts(
            conn.execute(
                """
                SELECT o.*, COUNT(DISTINCT mo.match_id) AS matches_count,
                       SUM(CASE WHEN e.event_type = 'card' AND e.card_color = 'yellow' THEN 1 ELSE 0 END) AS yellow_cards,
                       SUM(CASE WHEN e.event_type = 'card' AND e.card_color = 'red' THEN 1 ELSE 0 END) AS red_cards
                FROM officials o
                LEFT JOIN match_officials mo ON mo.official_id = o.id
                LEFT JOIN events e ON e.match_id = mo.match_id
                GROUP BY o.id
                ORDER BY o.full_name
                """
            ).fetchall()
        )



def _safe_match_sort_key(row: dict[str, Any]) -> tuple[str, str, int]:
    return (str(row.get("match_date") or ""), str(row.get("match_time") or ""), int(row.get("match_id") or 0))


def list_notifications(period_matches: int = 10, yellow_threshold: int = 3, include_watch: bool = True) -> list[dict[str, Any]]:
    """Return discipline notifications generated from cards in the database.

    Rules implemented for the MVP:
    - red card: always creates an immediate notification.
    - yellow accumulation: if a player reaches `yellow_threshold` yellow cards in the
      latest rolling `period_matches` club matches, create a suspension-risk notification.
    - watch list: if enabled, players at threshold-1 yellows are shown as warning.

    The query is dynamic so the notification page updates as soon as new match sheets are inserted.
    """
    init_db()
    period_matches = max(1, int(period_matches or 10))
    yellow_threshold = max(1, int(yellow_threshold or 3))
    with get_conn() as conn:
        match_rows = rows_to_dicts(
            conn.execute(
                """
                SELECT m.id AS match_id, m.match_date, m.match_time, m.round_label,
                       m.home_club_id, hc.name AS home_team, m.away_club_id, ac.name AS away_team
                FROM matches m
                LEFT JOIN clubs hc ON hc.id = m.home_club_id
                LEFT JOIN clubs ac ON ac.id = m.away_club_id
                ORDER BY COALESCE(m.match_date, ''), COALESCE(m.match_time, ''), m.id
                """
            ).fetchall()
        )
        club_match_ids: dict[int, list[int]] = {}
        match_context: dict[int, dict[str, Any]] = {}
        for m in match_rows:
            match_id = int(m["match_id"])
            match_context[match_id] = m
            for club_key in ("home_club_id", "away_club_id"):
                club_id = m.get(club_key)
                if club_id is not None:
                    club_match_ids.setdefault(int(club_id), []).append(match_id)

        card_rows = rows_to_dicts(
            conn.execute(
                """
                SELECT e.id AS event_id, e.match_id, e.club_id, e.player_id, e.minute, e.card_color, e.detail,
                       m.match_date, m.match_time, m.round_label,
                       hc.name AS home_team, ac.name AS away_team,
                       c.name AS club, p.full_name AS player, p.license_number
                FROM events e
                JOIN matches m ON m.id = e.match_id
                LEFT JOIN clubs hc ON hc.id = m.home_club_id
                LEFT JOIN clubs ac ON ac.id = m.away_club_id
                LEFT JOIN clubs c ON c.id = e.club_id
                LEFT JOIN players p ON p.id = e.player_id
                WHERE e.event_type = 'card'
                ORDER BY COALESCE(m.match_date, ''), COALESCE(m.match_time, ''), e.match_id, COALESCE(e.minute, 999), e.id
                """
            ).fetchall()
        )

    notifications: list[dict[str, Any]] = []

    # Red cards: every red card is important enough to notify immediately.
    for row in card_rows:
        if row.get("card_color") == "red":
            notifications.append(
                {
                    "severity": "critical",
                    "kind": "red_card",
                    "title": "Carton rouge à traiter",
                    "player": row.get("player"),
                    "license_number": row.get("license_number"),
                    "club": row.get("club"),
                    "match_id": row.get("match_id"),
                    "match_label": f"{row.get('home_team') or '—'} vs {row.get('away_team') or '—'}",
                    "match_date": row.get("match_date"),
                    "match_time": row.get("match_time"),
                    "minute": row.get("minute"),
                    "count": 1,
                    "threshold": 1,
                    "period_matches": period_matches,
                    "message": "Le joueur a reçu un carton rouge. Vérifier la suspension et éviter son inscription au match suivant si la sanction est confirmée.",
                }
            )

    yellow_rows = [r for r in card_rows if r.get("card_color") == "yellow" and r.get("player_id") is not None and r.get("club_id") is not None]
    latest_by_player_club: dict[tuple[int, int], dict[str, Any]] = {}
    for row in yellow_rows:
        latest_by_player_club[(int(row["player_id"]), int(row["club_id"]))] = row

    for (player_id, club_id), latest in latest_by_player_club.items():
        club_matches = club_match_ids.get(club_id, [])
        if not club_matches:
            continue
        latest_match_id = int(latest["match_id"])
        try:
            latest_index = club_matches.index(latest_match_id)
        except ValueError:
            latest_index = len(club_matches) - 1
        window_ids = set(club_matches[max(0, latest_index - period_matches + 1): latest_index + 1])
        window_cards = [r for r in yellow_rows if int(r["player_id"]) == player_id and int(r["club_id"]) == club_id and int(r["match_id"]) in window_ids]
        count = len(window_cards)
        if count >= yellow_threshold:
            severity = "critical"
            kind = "yellow_suspension_risk"
            title = f"Seuil de {yellow_threshold} cartons jaunes atteint"
            message = (
                f"Le joueur totalise {count} cartons jaunes sur les {period_matches} derniers matchs de son club. "
                "Vérifier la suspension automatique pour le match suivant avant de l'inscrire sur une feuille de match."
            )
        elif include_watch and count == yellow_threshold - 1:
            severity = "warning"
            kind = "yellow_watch"
            title = f"À un carton jaune de la suspension"
            message = (
                f"Le joueur compte {count} cartons jaunes sur les {period_matches} derniers matchs de son club. "
                "Un nouveau carton jaune pourrait déclencher une suspension."
            )
        else:
            continue
        notifications.append(
            {
                "severity": severity,
                "kind": kind,
                "title": title,
                "player": latest.get("player"),
                "license_number": latest.get("license_number"),
                "club": latest.get("club"),
                "match_id": latest.get("match_id"),
                "match_label": f"{latest.get('home_team') or '—'} vs {latest.get('away_team') or '—'}",
                "match_date": latest.get("match_date"),
                "match_time": latest.get("match_time"),
                "minute": latest.get("minute"),
                "count": count,
                "threshold": yellow_threshold,
                "period_matches": period_matches,
                "message": message,
            }
        )

    severity_rank = {"critical": 0, "warning": 1, "info": 2}
    notifications.sort(key=lambda n: (severity_rank.get(str(n.get("severity")), 9), str(n.get("match_date") or ""), str(n.get("match_time") or ""), str(n.get("player") or "")))
    return notifications


def notification_stats(period_matches: int = 10, yellow_threshold: int = 3) -> dict[str, Any]:
    notifications = list_notifications(period_matches=period_matches, yellow_threshold=yellow_threshold, include_watch=True)
    return {
        "notifications_total": len(notifications),
        "notifications_critical": sum(1 for n in notifications if n.get("severity") == "critical"),
        "yellow_suspension_alerts": sum(1 for n in notifications if n.get("kind") == "yellow_suspension_risk"),
        "yellow_watch_alerts": sum(1 for n in notifications if n.get("kind") == "yellow_watch"),
        "red_card_alerts": sum(1 for n in notifications if n.get("kind") == "red_card"),
    }

def export_table(table_name: str, output_path: Path) -> Path:
    allowed = {"matches", "players", "clubs", "events", "officials", "documents", "match_players", "observations"}
    if table_name not in allowed:
        raise ValueError("Table non exportable")
    init_db()
    with get_conn() as conn:
        rows = conn.execute(f"SELECT * FROM {table_name}").fetchall()
    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = None
        for row in rows:
            row_dict = row_to_dict(row)
            if writer is None:
                writer = csv.DictWriter(f, fieldnames=list(row_dict.keys()))
                writer.writeheader()
            writer.writerow(row_dict)
        if writer is None:
            f.write("")
    return output_path


# --- LEGIFOOT premium filters (added) ---
def _match_filter_sql(prefix: str = "m", *, competition: str = "", season: str = "", club: str = "") -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if competition:
        clauses.append(f"COALESCE({prefix}.competition, '') = ?")
        params.append(competition)
    if season:
        clauses.append(f"COALESCE({prefix}.season, '') = ?")
        params.append(season)
    if club:
        clauses.append("(hc.name = ? OR ac.name = ?)")
        params.extend([club, club])
    return (" AND " + " AND ".join(clauses) if clauses else "", params)


def list_players_filtered(competition: str = "", season: str = "", club: str = "") -> list[dict[str, Any]]:
    init_db()
    where, params = _match_filter_sql("m", competition=competition, season=season, club=club)
    if club:
        where += " AND pc.name = ?"
        params.append(club)
    with get_conn() as conn:
        return rows_to_dicts(conn.execute(
            f"""
            WITH filtered_appearances AS (
                SELECT mp.player_id, mp.match_id, mp.starter, pc.name AS club
                FROM match_players mp
                JOIN matches m ON m.id = mp.match_id
                LEFT JOIN clubs hc ON hc.id = m.home_club_id
                LEFT JOIN clubs ac ON ac.id = m.away_club_id
                LEFT JOIN clubs pc ON pc.id = mp.club_id
                WHERE 1=1 {where}
            ), appearance_counts AS (
                SELECT player_id,
                       COUNT(DISTINCT match_id) AS matches_played,
                       SUM(CASE WHEN starter = 1 THEN 1 ELSE 0 END) AS starts,
                       GROUP_CONCAT(DISTINCT club) AS clubs
                FROM filtered_appearances
                GROUP BY player_id
            ), event_counts AS (
                SELECT e.player_id,
                       SUM(CASE WHEN e.event_type = 'goal' THEN 1 ELSE 0 END) AS goals,
                       SUM(CASE WHEN e.event_type = 'card' AND e.card_color = 'yellow' THEN 1 ELSE 0 END) AS yellow_cards,
                       SUM(CASE WHEN e.event_type = 'card' AND e.card_color = 'red' THEN 1 ELSE 0 END) AS red_cards
                FROM events e
                JOIN matches m ON m.id = e.match_id
                LEFT JOIN clubs hc ON hc.id = m.home_club_id
                LEFT JOIN clubs ac ON ac.id = m.away_club_id
                LEFT JOIN clubs ec ON ec.id = e.club_id
                WHERE 1=1 {where.replace('pc.name = ?', 'ec.name = ?')}
                GROUP BY e.player_id
            )
            SELECT p.*, COALESCE(a.matches_played, 0) AS matches_played,
                   COALESCE(a.starts, 0) AS starts,
                   COALESCE(ev.goals, 0) AS goals,
                   COALESCE(ev.yellow_cards, 0) AS yellow_cards,
                   COALESCE(ev.red_cards, 0) AS red_cards,
                   a.clubs AS clubs
            FROM players p
            JOIN appearance_counts a ON a.player_id = p.id
            LEFT JOIN event_counts ev ON ev.player_id = p.id
            ORDER BY p.full_name
            """,
            params + params,
        ).fetchall())


def list_events_filtered(competition: str = "", season: str = "", club: str = "", event_type: str = "") -> list[dict[str, Any]]:
    init_db()
    clauses, params = _match_filter_sql("m", competition=competition, season=season, club=club)
    extra = ""
    if club:
        extra += " AND (c.name = ? OR c.name IS NULL)"
        params.append(club)
    if event_type:
        extra += " AND e.event_type = ?"
        params.append(event_type)
    with get_conn() as conn:
        return rows_to_dicts(conn.execute(
            f"""
            SELECT e.*, m.competition, m.season, m.round_label, m.match_date, m.match_time,
                   hc.name AS home_team, ac.name AS away_team,
                   c.name AS club, p.full_name AS player, rp.full_name AS related_player
            FROM events e
            JOIN matches m ON m.id = e.match_id
            LEFT JOIN clubs hc ON hc.id = m.home_club_id
            LEFT JOIN clubs ac ON ac.id = m.away_club_id
            LEFT JOIN clubs c ON c.id = e.club_id
            LEFT JOIN players p ON p.id = e.player_id
            LEFT JOIN players rp ON rp.id = e.related_player_id
            WHERE 1=1 {clauses} {extra}
            ORDER BY COALESCE(m.match_date, '') DESC, e.match_id DESC, COALESCE(e.minute, 999), e.id
            """, params
        ).fetchall())


def list_officials_filtered(competition: str = "", season: str = "", club: str = "") -> list[dict[str, Any]]:
    init_db()
    clauses, params = _match_filter_sql("m", competition=competition, season=season, club=club)
    with get_conn() as conn:
        return rows_to_dicts(conn.execute(
            f"""
            SELECT o.*, COUNT(DISTINCT mo.match_id) AS matches_count,
                   SUM(CASE WHEN e.event_type = 'card' AND e.card_color = 'yellow' THEN 1 ELSE 0 END) AS yellow_cards,
                   SUM(CASE WHEN e.event_type = 'card' AND e.card_color = 'red' THEN 1 ELSE 0 END) AS red_cards,
                   GROUP_CONCAT(DISTINCT COALESCE(m.competition, '')) AS competitions
            FROM officials o
            JOIN match_officials mo ON mo.official_id = o.id
            JOIN matches m ON m.id = mo.match_id
            LEFT JOIN clubs hc ON hc.id = m.home_club_id
            LEFT JOIN clubs ac ON ac.id = m.away_club_id
            LEFT JOIN events e ON e.match_id = mo.match_id
            WHERE 1=1 {clauses}
            GROUP BY o.id
            ORDER BY o.full_name
            """, params
        ).fetchall())


def dashboard_chart_data(competition: str = "", season: str = "", club: str = "") -> dict[str, Any]:
    events = list_events_filtered(competition=competition, season=season, club=club)
    cards_by_club: dict[str, dict[str, int]] = {}
    goals_by_club: dict[str, int] = {}
    events_by_type: dict[str, int] = {}
    for e in events:
        club_name = e.get('club') or 'Non attribué'
        kind = e.get('event_type') or 'note'
        events_by_type[kind] = events_by_type.get(kind, 0) + 1
        if kind == 'goal':
            goals_by_club[club_name] = goals_by_club.get(club_name, 0) + 1
        if kind == 'card':
            cards_by_club.setdefault(club_name, {'yellow': 0, 'red': 0})
            if e.get('card_color') == 'red':
                cards_by_club[club_name]['red'] += 1
            else:
                cards_by_club[club_name]['yellow'] += 1
    return {
        'goals_by_club': [{'club': k, 'goals': v} for k, v in sorted(goals_by_club.items(), key=lambda x: x[1], reverse=True)[:8]],
        'cards_by_club': [{'club': k, **v, 'total': v['yellow'] + v['red']} for k, v in sorted(cards_by_club.items(), key=lambda x: x[1]['yellow'] + x[1]['red'], reverse=True)[:8]],
        'events_by_type': [{'type': k, 'count': v} for k, v in sorted(events_by_type.items(), key=lambda x: x[1], reverse=True)],
    }


# --- LEGIFOOT premium UX helpers ---

def list_clubs() -> list[dict[str, Any]]:
    init_db()
    with get_conn() as conn:
        return rows_to_dicts(conn.execute("""
            SELECT c.id, c.name,
                   COUNT(DISTINCT m.id) AS matches,
                   SUM(CASE WHEN e.event_type='goal' THEN 1 ELSE 0 END) AS goals,
                   SUM(CASE WHEN e.event_type='card' AND e.card_color='yellow' THEN 1 ELSE 0 END) AS yellow_cards,
                   SUM(CASE WHEN e.event_type='card' AND e.card_color='red' THEN 1 ELSE 0 END) AS red_cards
            FROM clubs c
            LEFT JOIN matches m ON c.id IN (m.home_club_id, m.away_club_id)
            LEFT JOIN events e ON e.club_id = c.id
            GROUP BY c.id
            ORDER BY c.name
        """).fetchall())


def get_club_detail(club_id: int) -> dict[str, Any] | None:
    init_db()
    with get_conn() as conn:
        club = row_to_dict(conn.execute("SELECT * FROM clubs WHERE id=?", (club_id,)).fetchone())
        if not club:
            return None
        matches = rows_to_dicts(conn.execute("""
            SELECT m.*, hc.name AS home_team, ac.name AS away_team, s.name AS stadium, s.city
            FROM matches m
            LEFT JOIN clubs hc ON hc.id=m.home_club_id
            LEFT JOIN clubs ac ON ac.id=m.away_club_id
            LEFT JOIN stadiums s ON s.id=m.stadium_id
            WHERE m.home_club_id=? OR m.away_club_id=?
            ORDER BY COALESCE(m.match_date,'9999-99-99') DESC, m.id DESC
        """, (club_id, club_id)).fetchall())
        players = rows_to_dicts(conn.execute("""
            SELECT DISTINCT p.*, COUNT(DISTINCT mp.match_id) AS matches_played
            FROM players p
            JOIN match_players mp ON mp.player_id=p.id
            WHERE mp.club_id=?
            GROUP BY p.id
            ORDER BY p.full_name
        """, (club_id,)).fetchall())
        events = rows_to_dicts(conn.execute("""
            SELECT e.*, p.full_name AS player, m.match_date, hc.name AS home_team, ac.name AS away_team
            FROM events e
            LEFT JOIN players p ON p.id=e.player_id
            JOIN matches m ON m.id=e.match_id
            LEFT JOIN clubs hc ON hc.id=m.home_club_id
            LEFT JOIN clubs ac ON ac.id=m.away_club_id
            WHERE e.club_id=?
            ORDER BY COALESCE(m.match_date,'9999-99-99') DESC, e.minute
        """, (club_id,)).fetchall())
        return {"club": club, "matches": matches, "players": players, "events": events}


def get_player_detail(player_id: int) -> dict[str, Any] | None:
    init_db()
    with get_conn() as conn:
        player = row_to_dict(conn.execute("SELECT * FROM players WHERE id=?", (player_id,)).fetchone())
        if not player:
            return None
        matches = rows_to_dicts(conn.execute("""
            SELECT mp.*, c.name AS club, m.id AS match_id, m.competition, m.season, m.round_label, m.match_date,
                   hc.name AS home_team, ac.name AS away_team, m.score_home, m.score_away
            FROM match_players mp
            JOIN matches m ON m.id=mp.match_id
            LEFT JOIN clubs c ON c.id=mp.club_id
            LEFT JOIN clubs hc ON hc.id=m.home_club_id
            LEFT JOIN clubs ac ON ac.id=m.away_club_id
            WHERE mp.player_id=?
            ORDER BY COALESCE(m.match_date,'9999-99-99') DESC, m.id DESC
        """, (player_id,)).fetchall())
        events = rows_to_dicts(conn.execute("""
            SELECT e.*, c.name AS club, rp.full_name AS related_player, m.match_date, m.id AS match_id,
                   hc.name AS home_team, ac.name AS away_team
            FROM events e
            LEFT JOIN clubs c ON c.id=e.club_id
            LEFT JOIN players rp ON rp.id=e.related_player_id
            JOIN matches m ON m.id=e.match_id
            LEFT JOIN clubs hc ON hc.id=m.home_club_id
            LEFT JOIN clubs ac ON ac.id=m.away_club_id
            WHERE e.player_id=? OR e.related_player_id=?
            ORDER BY COALESCE(m.match_date,'9999-99-99') DESC, e.minute
        """, (player_id, player_id)).fetchall())
        return {"player": player, "matches": matches, "events": events}


def get_official_detail(official_id: int) -> dict[str, Any] | None:
    init_db()
    with get_conn() as conn:
        official = row_to_dict(conn.execute("SELECT * FROM officials WHERE id=?", (official_id,)).fetchone())
        if not official:
            return None
        matches = rows_to_dicts(conn.execute("""
            SELECT mo.role, m.*, hc.name AS home_team, ac.name AS away_team, s.name AS stadium,
                   SUM(CASE WHEN e.event_type='card' AND e.card_color='yellow' THEN 1 ELSE 0 END) AS yellow_cards,
                   SUM(CASE WHEN e.event_type='card' AND e.card_color='red' THEN 1 ELSE 0 END) AS red_cards
            FROM match_officials mo
            JOIN matches m ON m.id=mo.match_id
            LEFT JOIN clubs hc ON hc.id=m.home_club_id
            LEFT JOIN clubs ac ON ac.id=m.away_club_id
            LEFT JOIN stadiums s ON s.id=m.stadium_id
            LEFT JOIN events e ON e.match_id=m.id
            WHERE mo.official_id=?
            GROUP BY mo.id
            ORDER BY COALESCE(m.match_date,'9999-99-99') DESC
        """, (official_id,)).fetchall())
        return {"official": official, "matches": matches}


def global_search(query: str, limit: int = 40) -> dict[str, list[dict[str, Any]]]:
    init_db()
    q = f"%{query.strip()}%"
    if not query.strip():
        return {"matches": [], "players": [], "clubs": [], "officials": [], "events": [], "documents": []}
    with get_conn() as conn:
        return {
            "matches": rows_to_dicts(conn.execute("""
                SELECT m.id, m.competition, m.season, m.round_label, m.match_date, hc.name AS home_team, ac.name AS away_team, s.name AS stadium
                FROM matches m LEFT JOIN clubs hc ON hc.id=m.home_club_id LEFT JOIN clubs ac ON ac.id=m.away_club_id LEFT JOIN stadiums s ON s.id=m.stadium_id
                WHERE hc.name LIKE ? OR ac.name LIKE ? OR s.name LIKE ? OR m.competition LIKE ? OR m.round_label LIKE ?
                ORDER BY m.id DESC LIMIT ?
            """, (q,q,q,q,q,limit)).fetchall()),
            "players": rows_to_dicts(conn.execute("SELECT id, full_name, license_number, position, nationality FROM players WHERE full_name LIKE ? OR license_number LIKE ? ORDER BY full_name LIMIT ?", (q,q,limit)).fetchall()),
            "clubs": rows_to_dicts(conn.execute("SELECT id, name FROM clubs WHERE name LIKE ? ORDER BY name LIMIT ?", (q,limit)).fetchall()),
            "officials": rows_to_dicts(conn.execute("SELECT id, full_name FROM officials WHERE full_name LIKE ? ORDER BY full_name LIMIT ?", (q,limit)).fetchall()),
            "events": rows_to_dicts(conn.execute("""
                SELECT e.id, e.event_type, e.card_color, e.minute, p.full_name AS player, c.name AS club, m.id AS match_id
                FROM events e LEFT JOIN players p ON p.id=e.player_id LEFT JOIN clubs c ON c.id=e.club_id LEFT JOIN matches m ON m.id=e.match_id
                WHERE p.full_name LIKE ? OR c.name LIKE ? OR e.detail LIKE ? OR e.event_type LIKE ? LIMIT ?
            """, (q,q,q,q,limit)).fetchall()),
            "documents": rows_to_dicts(conn.execute("SELECT id, original_filename, status, confidence, created_at FROM documents WHERE original_filename LIKE ? OR raw_text LIKE ? ORDER BY id DESC LIMIT ?", (q,q,limit)).fetchall()),
        }


def upsert_notification_state(key: str, status: str = "treated", comment: str | None = None) -> None:
    init_db()
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO notification_states (key, status, admin_comment, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET status=excluded.status, admin_comment=excluded.admin_comment, updated_at=excluded.updated_at
        """, (key, status, comment, now_iso()))


def get_notification_states() -> dict[str, dict[str, Any]]:
    init_db()
    with get_conn() as conn:
        rows = rows_to_dicts(conn.execute("SELECT * FROM notification_states").fetchall())
        return {row["key"]: row for row in rows}


def admin_todo_board() -> dict[str, Any]:
    init_db()
    docs = [d for d in list_documents(200) if d.get("status") in {"draft", "error"}]
    matches = [m for m in list_matches() if not m.get("score_home") and not m.get("score_away")]
    alerts = list_notifications(period_matches=10, yellow_threshold=3, include_watch=True)
    return {
        "documents_pending": docs[:8],
        "matches_incomplete": matches[:8],
        "critical_notifications": [n for n in alerts if n.get("severity") == "critical"][:8],
        "watch_notifications": [n for n in alerts if n.get("severity") != "critical"][:8],
    }


# --- LEGIFOOT UX optimization helpers v25 ---

def _is_present(value: Any) -> bool:
    return value is not None and str(value).strip() not in {"", "None", "—"}


def match_completeness(match_id: int) -> dict[str, Any]:
    detail = get_match_detail(match_id)
    if not detail:
        return {"score": 0, "label": "Introuvable", "missing": ["match"], "class": "red"}
    m = detail.get("match") or {}
    checks = {
        "date": _is_present(m.get("match_date")),
        "heure": _is_present(m.get("match_time")),
        "compétition": _is_present(m.get("competition")),
        "saison": _is_present(m.get("season")),
        "journée/tour": _is_present(m.get("round_label")),
        "stade": _is_present(m.get("stadium")),
        "équipe domicile": _is_present(m.get("home_team")),
        "équipe extérieur": _is_present(m.get("away_team")),
        "score": m.get("score_home") is not None and m.get("score_away") is not None,
        "joueurs": len(detail.get("players") or []) >= 22,
        "arbitres": len(detail.get("officials") or []) >= 1,
        "événements": len(detail.get("events") or []) >= 1,
        "source": _is_present(m.get("document_id")),
    }
    total = len(checks)
    ok = sum(1 for v in checks.values() if v)
    score = int(round((ok / total) * 100)) if total else 0
    missing = [k for k, v in checks.items() if not v]
    if score >= 90:
        label, cls = "Complet", "green"
    elif score >= 70:
        label, cls = "Bon", "blue"
    elif score >= 45:
        label, cls = "À vérifier", "yellow"
    else:
        label, cls = "Incomplet", "red"
    return {"score": score, "label": label, "missing": missing, "class": cls}


def list_missing_data(limit: int = 20) -> dict[str, list[dict[str, Any]]]:
    matches = list_matches()
    no_referee = []
    no_stadium = []
    no_score = []
    incomplete = []
    for m in matches:
        comp = match_completeness(int(m["id"]))
        row = {**m, "completeness": comp}
        if not _is_present(m.get("stadium")):
            no_stadium.append(row)
        if m.get("score_home") is None or m.get("score_away") is None:
            no_score.append(row)
        if comp["score"] < 70:
            incomplete.append(row)
        detail = get_match_detail(int(m["id"]))
        if detail and not detail.get("officials"):
            no_referee.append(row)
    documents = [d for d in list_documents(100) if d.get("status") in {"draft", "error", "to_review"}]
    events_no_minute = [e for e in list_events() if e.get("minute") is None][:limit]
    players_no_club = []
    with get_conn() as conn:
        players_no_club = rows_to_dicts(conn.execute("""
            SELECT p.* FROM players p
            LEFT JOIN match_players mp ON mp.player_id=p.id
            WHERE mp.id IS NULL
            ORDER BY p.full_name LIMIT ?
        """, (limit,)).fetchall())
    return {
        "matches_without_referee": no_referee[:limit],
        "matches_without_stadium": no_stadium[:limit],
        "matches_without_score": no_score[:limit],
        "matches_incomplete": incomplete[:limit],
        "documents_to_review": documents[:limit],
        "events_without_minute": events_no_minute,
        "players_without_club": players_no_club,
    }


def recent_activity(limit: int = 12) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for m in list_matches()[:limit]:
        out.append({"type": "match", "label": f"{m.get('home_team') or '—'} vs {m.get('away_team') or '—'}", "meta": m.get("match_date") or m.get("created_at") or "", "url": f"/matches/{m.get('id')}"})
    for d in list_documents(limit):
        out.append({"type": "document", "label": d.get("original_filename") or "Document", "meta": d.get("status") or "", "url": f"/review/{d.get('id')}"})
    for n in list_notifications(period_matches=10, yellow_threshold=3, include_watch=True)[:limit]:
        out.append({"type": "discipline", "label": n.get("message") or n.get("player") or "Notification", "meta": n.get("severity") or "", "url": "/notifications"})
    return out[:limit]


def discipline_analysis(competition: str = "", season: str = "", club: str = "") -> dict[str, Any]:
    events = list_events_filtered(competition=competition, season=season, club=club) if (competition or season or club) else list_events()
    by_club: dict[str, dict[str, int]] = {}
    by_player: dict[str, dict[str, Any]] = {}
    by_official: dict[str, dict[str, Any]] = {}
    for e in events:
        if e.get("event_type") != "card":
            continue
        color = e.get("card_color") or "yellow"
        club_name = e.get("club") or "Non attribué"
        by_club.setdefault(club_name, {"yellow": 0, "red": 0, "total": 0})
        by_club[club_name]["red" if color == "red" else "yellow"] += 1
        by_club[club_name]["total"] += 1
        player = e.get("player") or "Non attribué"
        by_player.setdefault(player, {"player": player, "club": club_name, "yellow": 0, "red": 0, "total": 0})
        by_player[player]["red" if color == "red" else "yellow"] += 1
        by_player[player]["total"] += 1
    with get_conn() as conn:
        rows = rows_to_dicts(conn.execute("""
            SELECT o.full_name AS official, COUNT(e.id) AS total_cards,
                   SUM(CASE WHEN e.card_color='yellow' THEN 1 ELSE 0 END) AS yellow,
                   SUM(CASE WHEN e.card_color='red' THEN 1 ELSE 0 END) AS red,
                   COUNT(DISTINCT m.id) AS matches
            FROM officials o
            JOIN match_officials mo ON mo.official_id=o.id
            JOIN matches m ON m.id=mo.match_id
            LEFT JOIN events e ON e.match_id=m.id AND e.event_type='card'
            GROUP BY o.id
            HAVING total_cards > 0
            ORDER BY total_cards DESC LIMIT 10
        """).fetchall())
    notifications = list_notifications(period_matches=10, yellow_threshold=3, include_watch=True)
    return {
        "cards_by_club": sorted(({"club": k, **v} for k, v in by_club.items()), key=lambda r: r["total"], reverse=True)[:12],
        "players_most_carded": sorted(by_player.values(), key=lambda r: r["total"], reverse=True)[:12],
        "cards_by_official": rows,
        "red_cards": [e for e in events if e.get("event_type") == "card" and e.get("card_color") == "red"][:20],
        "risk_notifications": notifications,
    }


def update_match_status(match_id: int, status: str) -> None:
    allowed = {"draft", "to_review", "validated", "published", "played", "archived", "incomplete"}
    if status not in allowed:
        status = "to_review"
    with get_conn() as conn:
        conn.execute("UPDATE matches SET status=? WHERE id=?", (status, match_id))


def public_status(status: str | None) -> bool:
    return (status or "played") in {"played", "validated", "published"}
