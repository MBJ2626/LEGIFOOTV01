from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from typing import Any

from .database import normalize_key

FTF_PARSER_VERSION = "0.2.0-ftf-multimatch"


def clean_value(value: Any) -> str:
    if value is None:
        return ""
    value = str(value).replace("\u00a0", " ").replace("\n", " ").strip()
    value = re.sub(r"\s+", " ", value)
    return value.strip(" :-\t")


def parse_date(value: str | None) -> str | None:
    value = clean_value(value)
    if not value:
        return None
    m = re.search(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})", value)
    if not m:
        return None
    day, month, year = m.groups()
    return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"


def parse_time(value: str | None) -> str | None:
    value = clean_value(value)
    if not value:
        return None
    m = re.search(r"(\d{1,2})\s*:\s*(\d{2})", value)
    if not m:
        return None
    hour, minute = m.groups()
    return f"{int(hour):02d}:{int(minute):02d}"


def parse_score(value: str | None) -> tuple[int | None, int | None]:
    value = clean_value(value)
    if not value:
        return None, None
    m = re.search(r"(\d{1,2})\s*[-:/]\s*(\d{1,2})", value)
    if not m:
        return None, None
    return int(m.group(1)), int(m.group(2))


def parse_minute(value: Any) -> tuple[int | None, int | None]:
    raw = clean_value(value).replace('"', "'")
    if not raw:
        return None, None
    m = re.search(r"(\d{1,3})(?:\s*\+\s*(\d{1,2}))?", raw)
    if not m:
        return None, None
    return int(m.group(1)), int(m.group(2)) if m.group(2) else None


def to_int_or_none(value: Any) -> int | None:
    value = clean_value(value)
    if not value:
        return None
    try:
        return int(value.lstrip("0") or "0")
    except ValueError:
        m = re.search(r"\d+", value)
        return int(m.group(0)) if m else None


def infer_round_from_name(source_name: str | None) -> str | None:
    if not source_name:
        return None
    ascii_name = unicodedata.normalize("NFKD", source_name)
    ascii_name = "".join(ch for ch in ascii_name if not unicodedata.combining(ch))
    ascii_name = re.sub(r"[^0-9A-Za-z]+", " ", ascii_name).lower()
    # Examples: 1ere Journee, 2eme journee, journee 3.
    m = re.search(r"\b(\d{1,2})\s*(?:ere|eme|e|er)?\s+journee\b", ascii_name)
    if not m:
        m = re.search(r"\bjournee\s+(\d{1,2})\b", ascii_name)
    if m:
        return f"Journée {int(m.group(1))}"
    return None


def infer_season_from_date(date_value: str | None) -> str | None:
    if not date_value:
        return None
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", date_value)
    if not m:
        return None
    year = int(m.group(1))
    month = int(m.group(2))
    if month >= 7:
        return f"{year}-{year + 1}"
    return f"{year - 1}-{year}"


def split_page_blocks(text: str) -> list[dict[str, Any]]:
    # The extractor appends table dumps after all page text. FTF parsing needs only the real page text here.
    page_text_only = re.split(r"\n--- TABLE", text or "", maxsplit=1)[0]
    parts = re.split(r"\n?--- PAGE (\d+) ---\n", page_text_only)
    pages: list[dict[str, Any]] = []
    for i in range(1, len(parts), 2):
        try:
            page_no = int(parts[i])
        except ValueError:
            continue
        pages.append({"page": page_no, "text": parts[i + 1] if i + 1 < len(parts) else ""})
    return pages


def clean_lines(text: str) -> list[str]:
    return [clean_value(line) for line in (text or "").splitlines() if clean_value(line)]


def table_title(rows: list[list[Any]]) -> str:
    if not rows:
        return ""
    first = [clean_value(c) for c in rows[0]]
    # Many pdfplumber tables have a merged title in the first cell and empty remaining cells.
    if first and first[0] and all(not c for c in first[1:]):
        return normalize_key(first[0])
    return normalize_key(" ".join(first))


def is_player_table(rows: list[list[Any]]) -> bool:
    for row in rows[:3]:
        cells = [normalize_key(clean_value(c)) for c in row]
        if len(cells) >= 3 and cells[0] in {"n", "n deg", "no", "numero"} and "nom et prenom" in cells[1] and "licence" in cells[2]:
            return True
        if len(cells) >= 6 and cells[3] in {"n", "n deg", "no", "numero"} and "nom et prenom" in cells[4] and "licence" in cells[5]:
            return True
    # pdfplumber usually returns "N°" as normalized "n" because the degree sign is removed.
    for row in rows[:3]:
        cells = [normalize_key(clean_value(c)) for c in row]
        if len(cells) >= 3 and cells[0].startswith("n") and "nom" in cells[1] and "licence" in cells[2]:
            return True
    return False


def is_staff_table(rows: list[list[Any]]) -> bool:
    title = table_title(rows)
    if "staff" in title:
        return True
    if not rows:
        return False
    first = [normalize_key(clean_value(c)) for c in rows[0]]
    if len(first) >= 4 and "nom et prenom" in first[0] and "licence" in first[1] and "nom et prenom" in first[2] and "licence" in first[3]:
        return True
    if len(rows) > 1:
        second = [normalize_key(clean_value(c)) for c in rows[1]]
        if len(second) >= 4 and "nom et prenom" in second[0] and "licence" in second[1] and "nom et prenom" in second[2] and "licence" in second[3]:
            return True
    return False


def is_replacements_table(rows: list[list[Any]]) -> bool:
    title = table_title(rows)
    if "remplacements" in title:
        return True
    for row in rows[:3]:
        cells = [normalize_key(clean_value(c)) for c in row]
        if len(cells) >= 4 and cells[0] == "equipe" and cells[1] == "min" and "entrant" in cells[2] and "sortant" in cells[3]:
            return True
    return False


def is_officials_table(rows: list[list[Any]]) -> bool:
    title = table_title(rows)
    if "officiels du match" in title:
        return True
    for row in rows[:3]:
        cells = [normalize_key(clean_value(c)) for c in row]
        if len(cells) >= 2 and cells[0] == "poste" and "nom et prenom" in cells[1]:
            return True
    # Tables without the title row often start directly with ARBITRE / 1ER_ASSISTANT.
    if rows and len(rows[0]) >= 2:
        first = normalize_key(rows[0][0])
        return first in {"arbitre", "1er assistant", "1er assistant"}
    return False


def is_yellow_table(rows: list[list[Any]]) -> bool:
    return "joueurs avertis" in table_title(rows)


def is_red_table(rows: list[list[Any]]) -> bool:
    return "joueurs expulses" in table_title(rows)


def is_injury_table(rows: list[list[Any]]) -> bool:
    return "joueurs blesses" in table_title(rows)


def normalized_title_contains(title: str, token: str) -> bool:
    return token in normalize_key(title)


def parse_player_triplet(number: Any, name: Any, license_number: Any, *, role: str, side: str) -> dict[str, Any] | None:
    name_s = clean_value(name)
    number_s = clean_value(number)
    license_s = clean_value(license_number)
    if not name_s and not license_s:
        return None
    if normalize_key(name_s) in {"nom et prenom", "nom", "prenom"}:
        return None
    if not name_s:
        return None
    return {
        "side": side,
        "number": number_s or None,
        "name": name_s,
        "license_number": license_s or None,
        "birth_date": None,
        "position": None,
        "nationality": None,
        "role": role,
        "starter": role == "titulaire",
        "substitute": role == "remplaçant",
        "captain": False,
        "goalkeeper": False,
        "minute_in": None,
        "minute_out": None,
    }


def parse_roster_table(rows: list[list[Any]], *, role: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    home_players: list[dict[str, Any]] = []
    away_players: list[dict[str, Any]] = []
    for row in rows:
        cells = [clean_value(c) for c in row]
        if not cells:
            continue
        row_key = normalize_key(" ".join(cells))
        if any(token in row_key for token in ["titulaires", "remplacants"]):
            continue
        if len(cells) >= 3 and normalize_key(cells[0]).startswith("n") and "nom" in normalize_key(cells[1]):
            continue
        # Ensure a minimum width for split left/right tables.
        cells = cells + [""] * (6 - len(cells))
        left = parse_player_triplet(cells[0], cells[1], cells[2], role=role, side="home")
        right = parse_player_triplet(cells[3], cells[4], cells[5], role=role, side="away")
        if left:
            home_players.append(left)
        if right:
            away_players.append(right)
    return home_players, away_players


def parse_staff_table(rows: list[list[Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    home_staff: list[dict[str, Any]] = []
    away_staff: list[dict[str, Any]] = []
    for row in rows:
        cells = [clean_value(c) for c in row]
        if not cells:
            continue
        row_key = normalize_key(" ".join(cells))
        if "staff" in row_key:
            continue
        if len(cells) >= 2 and "nom" in normalize_key(cells[0]) and "licence" in normalize_key(cells[1]):
            continue
        cells = cells + [""] * (4 - len(cells))
        if cells[0]:
            home_staff.append({"role": "Staff", "name": cells[0], "license_number": cells[1] or None})
        if cells[2]:
            away_staff.append({"role": "Staff", "name": cells[2], "license_number": cells[3] or None})
    return home_staff, away_staff


def split_number_name(value: Any) -> tuple[str | None, str | None]:
    raw = clean_value(value)
    if not raw:
        return None, None
    m = re.match(r"^([0-9]{1,3})\s*[-–]\s*(.+)$", raw)
    if m:
        return clean_value(m.group(1)), clean_value(m.group(2))
    return None, raw


def parse_replacements_table(rows: list[list[Any]]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for row in rows:
        cells = [clean_value(c) for c in row]
        row_key = normalize_key(" ".join(cells))
        if not cells or "remplacements" in row_key:
            continue
        if len(cells) >= 4 and normalize_key(cells[0]) == "equipe" and normalize_key(cells[1]) == "min":
            continue
        cells = cells + [""] * (4 - len(cells))
        code, minute_raw, player_in_raw, player_out_raw = cells[:4]
        if not code or not minute_raw or not (player_in_raw or player_out_raw):
            continue
        in_no, in_name = split_number_name(player_in_raw)
        out_no, out_name = split_number_name(player_out_raw)
        minute, stoppage = parse_minute(minute_raw)
        results.append(
            {
                "club_code": code,
                "minute": minute,
                "stoppage": stoppage,
                "player_in": in_name,
                "player_in_number": in_no,
                "player_out": out_name,
                "player_out_number": out_no,
                "raw_in": player_in_raw,
                "raw_out": player_out_raw,
            }
        )
    return results


def normalize_official_role(value: Any) -> str:
    raw = clean_value(value).replace("_", " ")
    key = normalize_key(raw)
    mapping = {
        "arbitre": "Arbitre central",
        "1er assistant": "Assistant 1",
        "2eme assistant": "Assistant 2",
        "2e assistant": "Assistant 2",
        "4eme arbitre": "Quatrième arbitre",
        "4e arbitre": "Quatrième arbitre",
        "commissaire": "Commissaire",
        "delegue": "Délégué",
    }
    return mapping.get(key, raw or "Officiel")


def parse_officials_table(rows: list[list[Any]]) -> list[dict[str, Any]]:
    officials: list[dict[str, Any]] = []
    for row in rows:
        cells = [clean_value(c) for c in row]
        if len(cells) < 2:
            continue
        row_key = normalize_key(" ".join(cells))
        if "officiels du match" in row_key:
            continue
        if normalize_key(cells[0]) == "poste" and "nom" in normalize_key(cells[1]):
            continue
        role, name = cells[0], cells[1]
        if not role or not name:
            continue
        officials.append({"role": normalize_official_role(role), "name": name})
    return officials


def parse_card_like_table(rows: list[list[Any]], *, event_type: str, card_color: str | None = None) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for row in rows:
        cells = [clean_value(c) for c in row]
        row_key = normalize_key(" ".join(cells))
        if not cells:
            continue
        if any(section in row_key for section in ["joueurs avertis", "joueurs expulses", "joueurs blesses"]):
            continue
        if len(cells) >= 4 and "nom" in normalize_key(cells[0]) and "licence" in normalize_key(cells[1]):
            continue
        cells = cells + [""] * (5 - len(cells))
        name, license_number, club_code, minute_raw, motif = cells[:5]
        if not name:
            continue
        minute, stoppage = parse_minute(minute_raw)
        events.append(
            {
                "name": name,
                "license_number": license_number or None,
                "club_code": club_code or None,
                "minute": minute,
                "stoppage": stoppage,
                "event_type": event_type,
                "card_color": card_color,
                "motif": motif or None,
            }
        )
    return events


def parse_header_event_lines(lines: list[str], away_line_index: int) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    end = len(lines)
    for i in range(away_line_index + 1, len(lines)):
        if normalize_key(lines[i]) == "titulaires":
            end = i
            break
    region = lines[away_line_index + 1 : end]
    i = 0
    while i < len(region):
        line = region[i]
        # PyMuPDF often extracts the minute and the player name on two separate lines:
        #   8"
        #   OUNALLI ZIED
        only_minute = re.fullmatch(r"(\d{1,3}(?:\s*\+\s*\d{1,2})?)\s*[\"'’″]+", line)
        if only_minute:
            minute, stoppage = parse_minute(only_minute.group(1))
            if i + 1 < len(region):
                name = clean_value(region[i + 1])
                if name and not re.fullmatch(r"\d{1,3}\s*[\"'’″]+", name):
                    events.append({"minute": minute, "stoppage": stoppage, "player": name, "raw": f"{line} {name}"})
                    i += 2
                    continue
        # Some extracted text puts multiple visual event rows on one text line.
        markers = list(re.finditer(r"(\d{1,3}(?:\s*\+\s*\d{1,2})?)\s*[\"'’″]+", line))
        for idx, m in enumerate(markers):
            name_start = m.end()
            name_end = markers[idx + 1].start() if idx + 1 < len(markers) else len(line)
            name = clean_value(line[name_start:name_end])
            if not name and idx == len(markers) - 1 and i + 1 < len(region):
                # Last marker with no inline text: consume next line as the player name.
                candidate = clean_value(region[i + 1])
                if candidate and not re.fullmatch(r"\d{1,3}\s*[\"'’″]+", candidate):
                    name = candidate
                    i += 1
            if not name:
                continue
            minute, stoppage = parse_minute(m.group(1))
            events.append({"minute": minute, "stoppage": stoppage, "player": name, "raw": line})
        i += 1
    return events


def parse_header(lines: list[str]) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    warnings: list[str] = []
    header = {
        "home_team": None,
        "away_team": None,
        "stadium": None,
        "date": None,
        "time": None,
        "score_home": None,
        "score_away": None,
    }
    header_events: list[dict[str, Any]] = []
    dt_idx = None
    for i, line in enumerate(lines):
        if re.search(r"\d{1,2}/\d{1,2}/\d{4}\s+\d{1,2}:\d{2}", line):
            dt_idx = i
            break
    if dt_idx is None:
        warnings.append("Date/heure non détectée dans l'en-tête FTF.")
        return header, header_events, warnings
    header["date"] = parse_date(lines[dt_idx])
    header["time"] = parse_time(lines[dt_idx])
    header["stadium"] = lines[dt_idx - 1] if dt_idx >= 1 else None
    header["home_team"] = lines[dt_idx - 2] if dt_idx >= 2 else None
    if dt_idx + 1 < len(lines):
        header["score_home"], header["score_away"] = parse_score(lines[dt_idx + 1])
    if dt_idx + 2 < len(lines):
        header["away_team"] = lines[dt_idx + 2]
        header_events = parse_header_event_lines(lines, dt_idx + 2)
    for key, label in [("home_team", "équipe domicile"), ("away_team", "équipe extérieure"), ("stadium", "stade")]:
        if not header.get(key):
            warnings.append(f"{label.capitalize()} non détecté dans l'en-tête FTF.")
    if header.get("score_home") is None or header.get("score_away") is None:
        warnings.append("Score final non détecté dans l'en-tête FTF.")
    return header, header_events, warnings


def build_player_lookup(teams: list[dict[str, Any]]) -> tuple[dict[str, str], dict[str, list[str]]]:
    by_license: dict[str, str] = {}
    by_name: dict[str, list[str]] = defaultdict(list)
    for team in teams:
        side = team.get("side")
        for player in team.get("players", []) or []:
            if player.get("license_number"):
                by_license[normalize_key(player.get("license_number"))] = side
            name_key = normalize_key(player.get("name"))
            if name_key and side not in by_name[name_key]:
                by_name[name_key].append(side)
    return by_license, by_name


def resolve_player_side(name: str | None, license_number: str | None, by_license: dict[str, str], by_name: dict[str, list[str]]) -> str | None:
    lic_key = normalize_key(license_number)
    if lic_key and lic_key in by_license:
        return by_license[lic_key]
    name_key = normalize_key(name)
    if name_key in by_name and len(by_name[name_key]) == 1:
        return by_name[name_key][0]
    # Sometimes event names are a shortened prefix of the roster name or vice versa.
    if name_key:
        matches: list[str] = []
        for roster_name, sides in by_name.items():
            if name_key == roster_name or name_key in roster_name or roster_name in name_key:
                for side in sides:
                    if side not in matches:
                        matches.append(side)
        if len(matches) == 1:
            return matches[0]
    return None


def resolve_team_from_code_or_player(
    club_code: str | None,
    player_name: str | None,
    license_number: str | None,
    *,
    code_map: dict[str, str],
    teams_by_side: dict[str, dict[str, Any]],
    by_license: dict[str, str],
    by_name: dict[str, list[str]],
) -> str | None:
    code_key = normalize_key(club_code)
    if code_key and code_key in code_map:
        return teams_by_side[code_map[code_key]]["name"]
    side = resolve_player_side(player_name, license_number, by_license, by_name)
    if side:
        if code_key:
            code_map[code_key] = side
        return teams_by_side[side]["name"]
    return clean_value(club_code) or None


def build_code_map(
    raw_cards: list[dict[str, Any]],
    raw_reds: list[dict[str, Any]],
    raw_injuries: list[dict[str, Any]],
    raw_replacements: list[dict[str, Any]],
    by_license: dict[str, str],
    by_name: dict[str, list[str]],
) -> dict[str, str]:
    code_map: dict[str, str] = {}
    for item in [*raw_cards, *raw_reds, *raw_injuries]:
        code_key = normalize_key(item.get("club_code"))
        side = resolve_player_side(item.get("name"), item.get("license_number"), by_license, by_name)
        if code_key and side:
            code_map[code_key] = side
    for item in raw_replacements:
        code_key = normalize_key(item.get("club_code"))
        side = resolve_player_side(item.get("player_in"), None, by_license, by_name) or resolve_player_side(item.get("player_out"), None, by_license, by_name)
        if code_key and side:
            code_map[code_key] = side
    return code_map


def event_signature(event: dict[str, Any]) -> tuple[Any, ...]:
    return (
        event.get("event_type"),
        event.get("card_color"),
        event.get("minute"),
        event.get("stoppage"),
        normalize_key(event.get("team")),
        normalize_key(event.get("player")),
        normalize_key(event.get("related_player")),
    )


def sort_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for event in events:
        sig = event_signature(event)
        if sig in seen:
            continue
        seen.add(sig)
        unique.append(event)
    return sorted(unique, key=lambda e: (999 if e.get("minute") is None else int(e.get("minute")), e.get("event_type") or "", e.get("player") or ""))


def parse_single_ftf_match(
    *,
    pages: list[dict[str, Any]],
    tables: list[dict[str, Any]],
    source_name: str | None,
    match_index: int,
) -> dict[str, Any]:
    warnings: list[str] = []
    start_page = pages[0]["page"] if pages else None
    end_page = pages[-1]["page"] if pages else None
    lines = clean_lines(pages[0].get("text", "") if pages else "")
    header, header_events, header_warnings = parse_header(lines)
    warnings.extend(header_warnings)

    home_name = header.get("home_team") or "Équipe domicile"
    away_name = header.get("away_team") or "Équipe extérieure"
    teams = [
        {"side": "home", "name": home_name, "players": [], "staff": []},
        {"side": "away", "name": away_name, "players": [], "staff": []},
    ]
    teams_by_side = {"home": teams[0], "away": teams[1]}

    raw_replacements: list[dict[str, Any]] = []
    raw_yellows: list[dict[str, Any]] = []
    raw_reds: list[dict[str, Any]] = []
    raw_injuries: list[dict[str, Any]] = []
    officials: list[dict[str, Any]] = []

    tables_sorted = sorted(tables, key=lambda t: (int(t.get("page") or 0), int(t.get("table") or 0)))
    for table in tables_sorted:
        rows = table.get("rows") or []
        if not rows:
            continue
        title = table_title(rows)
        if is_player_table(rows):
            if "titulaire" in title:
                role = "titulaire"
            elif "remplacant" in title or "remplacants" in title:
                role = "remplaçant"
            else:
                # Continuation pages begin directly with the N° header. Once starters are complete,
                # the next N°/Nom/Licence table is the substitutes list.
                home_starters = sum(1 for p in teams[0]["players"] if p.get("starter"))
                away_starters = sum(1 for p in teams[1]["players"] if p.get("starter"))
                role = "remplaçant" if home_starters >= 11 and away_starters >= 11 else "titulaire"
            home_players, away_players = parse_roster_table(rows, role=role)
            teams[0]["players"].extend(home_players)
            teams[1]["players"].extend(away_players)
        elif is_staff_table(rows):
            home_staff, away_staff = parse_staff_table(rows)
            teams[0]["staff"].extend(home_staff)
            teams[1]["staff"].extend(away_staff)
        elif is_replacements_table(rows):
            raw_replacements.extend(parse_replacements_table(rows))
        elif is_officials_table(rows):
            officials.extend(parse_officials_table(rows))
        elif is_yellow_table(rows):
            raw_yellows.extend(parse_card_like_table(rows, event_type="card", card_color="yellow"))
        elif is_red_table(rows):
            raw_reds.extend(parse_card_like_table(rows, event_type="card", card_color="red"))
        elif is_injury_table(rows):
            raw_injuries.extend(parse_card_like_table(rows, event_type="injury", card_color=None))

    by_license, by_name = build_player_lookup(teams)
    code_map = build_code_map(raw_yellows, raw_reds, raw_injuries, raw_replacements, by_license, by_name)

    events: list[dict[str, Any]] = []
    card_signatures: set[tuple[str, int | None]] = set()

    for raw in raw_yellows + raw_reds:
        team_name = resolve_team_from_code_or_player(
            raw.get("club_code"),
            raw.get("name"),
            raw.get("license_number"),
            code_map=code_map,
            teams_by_side=teams_by_side,
            by_license=by_license,
            by_name=by_name,
        )
        card_signatures.add((normalize_key(raw.get("name")), raw.get("minute")))
        detail_bits = []
        if raw.get("motif"):
            detail_bits.append(str(raw.get("motif")))
        if raw.get("club_code"):
            detail_bits.append(f"club_code={raw.get('club_code')}")
        events.append(
            {
                "minute": raw.get("minute"),
                "stoppage": raw.get("stoppage"),
                "team": team_name,
                "player": raw.get("name"),
                "related_player": None,
                "event_type": "card",
                "card_color": raw.get("card_color"),
                "detail": "; ".join(detail_bits) if detail_bits else None,
            }
        )

    for raw in raw_injuries:
        team_name = resolve_team_from_code_or_player(
            raw.get("club_code"),
            raw.get("name"),
            raw.get("license_number"),
            code_map=code_map,
            teams_by_side=teams_by_side,
            by_license=by_license,
            by_name=by_name,
        )
        events.append(
            {
                "minute": raw.get("minute"),
                "stoppage": raw.get("stoppage"),
                "team": team_name,
                "player": raw.get("name"),
                "related_player": None,
                "event_type": "injury",
                "card_color": None,
                "detail": raw.get("motif"),
            }
        )

    for raw in raw_replacements:
        team_name = resolve_team_from_code_or_player(
            raw.get("club_code"),
            raw.get("player_in") or raw.get("player_out"),
            None,
            code_map=code_map,
            teams_by_side=teams_by_side,
            by_license=by_license,
            by_name=by_name,
        )
        detail_parts = []
        if raw.get("player_in_number"):
            detail_parts.append(f"entrant_no={raw.get('player_in_number')}")
        if raw.get("player_out_number"):
            detail_parts.append(f"sortant_no={raw.get('player_out_number')}")
        if raw.get("club_code"):
            detail_parts.append(f"club_code={raw.get('club_code')}")
        events.append(
            {
                "minute": raw.get("minute"),
                "stoppage": raw.get("stoppage"),
                "team": team_name,
                "player": raw.get("player_in"),
                "related_player": raw.get("player_out"),
                "event_type": "substitution",
                "card_color": None,
                "detail": "; ".join(detail_parts) if detail_parts else None,
            }
        )

    # The top block of the official PDF lists goals and disciplinary events with icons.
    # Text extraction loses the icons, so we classify top events as goals only when they
    # are not present in the yellow/red card tables at the same minute.
    for raw in header_events:
        sig = (normalize_key(raw.get("player")), raw.get("minute"))
        if sig in card_signatures:
            continue
        side = resolve_player_side(raw.get("player"), None, by_license, by_name)
        team_name = teams_by_side[side]["name"] if side else None
        events.append(
            {
                "minute": raw.get("minute"),
                "stoppage": raw.get("stoppage"),
                "team": team_name,
                "player": raw.get("player"),
                "related_player": None,
                "event_type": "goal",
                "card_color": None,
                "detail": "Déduit du bloc supérieur FTF: événement sans carton correspondant.",
            }
        )

    events = sort_events(events)

    home_starters = sum(1 for p in teams[0]["players"] if p.get("starter"))
    away_starters = sum(1 for p in teams[1]["players"] if p.get("starter"))
    if home_starters != 11:
        warnings.append(f"Nombre de titulaires domicile détectés: {home_starters} au lieu de 11.")
    if away_starters != 11:
        warnings.append(f"Nombre de titulaires extérieur détectés: {away_starters} au lieu de 11.")
    if not officials:
        warnings.append("Aucun officiel détecté pour ce match.")

    score_total = (header.get("score_home") or 0) + (header.get("score_away") or 0)
    goals_total = sum(1 for e in events if e.get("event_type") == "goal")
    if header.get("score_home") is not None and score_total != goals_total:
        warnings.append(f"Contrôle buts/score à vérifier: score total={score_total}, buts extraits={goals_total}.")

    field_score = 0
    for item in [header.get("home_team"), header.get("away_team"), header.get("stadium"), header.get("date"), header.get("time")]:
        field_score += 1 if item else 0
    field_score += min(home_starters, 11) / 11 * 2
    field_score += min(away_starters, 11) / 11 * 2
    field_score += min(len(officials), 5) / 5
    field_score += 1 if not warnings else 0.5
    confidence = round(min(0.98, 0.35 + field_score / 11), 2)

    match = {
        "competition": "Ligue 1 Professionnelle",
        "season": infer_season_from_date(header.get("date")),
        "round": infer_round_from_name(source_name),
        "date": header.get("date"),
        "time": header.get("time"),
        "stadium": header.get("stadium"),
        "city": None,
        "home_team": home_name,
        "away_team": away_name,
        "score_home": header.get("score_home"),
        "score_away": header.get("score_away"),
        "halftime_home": None,
        "halftime_away": None,
        "status": "played",
        "observations": None,
        "notes": None,
    }
    return {
        "_meta": {
            "parser_version": FTF_PARSER_VERSION,
            "source_name": source_name,
            "source_pages": f"{start_page}-{end_page}" if start_page and end_page and start_page != end_page else str(start_page or ""),
            "match_index": match_index,
            "confidence": confidence,
            "warnings": warnings,
            "team_code_map": {code: teams_by_side[side]["name"] for code, side in sorted(code_map.items()) if side in teams_by_side},
            "top_events_count": len(header_events),
        },
        "match": match,
        "teams": teams,
        "officials": officials,
        "events": events,
        "observations": [],
    }


def try_parse_ftf_match_sheets(
    text: str,
    tables: list[dict[str, Any]] | None = None,
    *,
    source_name: str | None = None,
    extractor_warnings: list[str] | None = None,
    extractor_confidence: float = 0.0,
) -> dict[str, Any] | None:
    if "FEUILLE DE MATCH INFORMATIS" not in (text or "").upper():
        return None
    pages = split_page_blocks(text)
    if not pages:
        return None
    start_indices = [i for i, page in enumerate(pages) if "feuille de match informatisee" in normalize_key(page.get("text"))]
    if not start_indices:
        return None

    tables_by_page: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for table in tables or []:
        try:
            page_no = int(table.get("page") or 0)
        except Exception:
            continue
        tables_by_page[page_no].append(table)

    matches: list[dict[str, Any]] = []
    for match_no, start_idx in enumerate(start_indices, start=1):
        end_idx = start_indices[match_no] - 1 if match_no < len(start_indices) else len(pages) - 1
        group_pages = pages[start_idx : end_idx + 1]
        group_tables: list[dict[str, Any]] = []
        for page in group_pages:
            group_tables.extend(tables_by_page.get(int(page["page"]), []))
        matches.append(parse_single_ftf_match(pages=group_pages, tables=group_tables, source_name=source_name, match_index=match_no))

    inherited_warnings = list(extractor_warnings or [])
    for match in matches:
        for warning in match.get("_meta", {}).get("warnings", []) or []:
            # Keep the parent warning list useful without repeating every small validation detail too much.
            inherited_warnings.append(f"Match {match.get('_meta', {}).get('match_index')}: {warning}")
    avg_conf = round(sum(float(m.get("_meta", {}).get("confidence", 0)) for m in matches) / max(len(matches), 1), 2)
    confidence = round(max(avg_conf, min(0.95, extractor_confidence)), 2)

    parent: dict[str, Any] = {
        "_meta": {
            "parser_version": FTF_PARSER_VERSION,
            "source_name": source_name,
            "mode": "batch" if len(matches) > 1 else "single",
            "matches_count": len(matches),
            "confidence": confidence,
            "warnings": inherited_warnings[:80],
            "raw_text_length": len(text or ""),
            "tables_count": len(tables or []),
        },
        "matches": matches,
    }
    if len(matches) == 1:
        # Preserve the original single-match payload contract for one-sheet PDFs.
        single = dict(matches[0])
        single["_meta"] = {**single.get("_meta", {}), **parent["_meta"], "mode": "single"}
        return single
    return parent
