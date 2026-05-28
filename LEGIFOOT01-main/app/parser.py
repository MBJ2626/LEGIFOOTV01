from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from .database import normalize_key
from .ftf_parser import try_parse_ftf_match_sheets

PARSER_VERSION = "0.2.0-ftf"


def clean_value(value: Any) -> str:
    if value is None:
        return ""
    value = str(value).replace("\u00a0", " ").strip()
    value = re.sub(r"\s+", " ", value)
    return value.strip(" :-\t")


def split_cells(line: str) -> list[str]:
    if "|" not in line:
        return []
    return [clean_value(cell) for cell in line.split("|")]


def find_value(text: str, labels: list[str]) -> str | None:
    escaped = [re.escape(label).replace("\\ ", r"\s+") for label in labels]
    pattern = re.compile(rf"(?im)^\s*(?:{'|'.join(escaped)})\s*[:=\-]\s*(.+?)\s*$")
    match = pattern.search(text)
    if match:
        return clean_value(match.group(1))
    return None


def find_section(text: str, title_variants: list[str]) -> str | None:
    titles = [re.escape(t).replace("\\ ", r"\s+") for t in title_variants]
    title_pattern = r"|".join(titles)
    pattern = re.compile(rf"(?ims)^\s*(?:{title_pattern})\s*[:\-]?\s*(.*?)(?=^\s*[A-ZÉÈÀÂÎÔÛÇ][A-ZÉÈÀÂÎÔÛÇa-zéèàâîôûç\s]{{2,}}\s*[:\-]|\Z)")
    match = pattern.search(text)
    if match:
        content = match.group(1).strip()
        return content or None
    return None


def parse_date(value: str | None) -> str | None:
    value = clean_value(value)
    if not value:
        return None
    candidates = ["%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d.%m.%Y"]
    for fmt in candidates:
        try:
            return datetime.strptime(value[:10], fmt).date().isoformat()
        except ValueError:
            pass
    match = re.search(r"(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})", value)
    if match:
        day, month, year = match.groups()
        if len(year) == 2:
            year = "20" + year
        try:
            return datetime(int(year), int(month), int(day)).date().isoformat()
        except ValueError:
            return value
    return value


def parse_time(value: str | None) -> str | None:
    value = clean_value(value)
    if not value:
        return None
    match = re.search(r"(\d{1,2})\s*[hH:]\s*(\d{2})", value)
    if match:
        hour, minute = match.groups()
        return f"{int(hour):02d}:{int(minute):02d}"
    match = re.search(r"\b(\d{1,2})\s*[hH]\b", value)
    if match:
        return f"{int(match.group(1)):02d}:00"
    return value


def parse_score(value: str | None) -> tuple[int | None, int | None]:
    value = clean_value(value)
    if not value:
        return None, None
    match = re.search(r"(\d{1,2})\s*[-:/]\s*(\d{1,2})", value)
    if match:
        return int(match.group(1)), int(match.group(2))
    return None, None


def parse_minute(value: Any) -> tuple[int | None, int | None]:
    raw = clean_value(value)
    if not raw:
        return None, None
    match = re.search(r"(\d{1,3})(?:\s*\+\s*(\d{1,2}))?", raw)
    if not match:
        return None, None
    return int(match.group(1)), int(match.group(2)) if match.group(2) else None


def map_header(headers: list[str]) -> dict[str, int]:
    mapping: dict[str, int] = {}
    for idx, header in enumerate(headers):
        key = normalize_key(header)
        if key in {"equipe", "club", "team"}:
            mapping["team"] = idx
        elif key in {"side", "cote", "dom ext", "domicile exterieur"}:
            mapping["side"] = idx
        elif key in {"n", "no", "num", "numero", "numero maillot", "maillot"}:
            mapping["number"] = idx
        elif key in {"joueur", "nom", "nom joueur", "prenom nom", "player", "full name"}:
            mapping["name"] = idx
        elif key in {"licence", "license", "numero licence", "n licence"}:
            mapping["license_number"] = idx
        elif key in {"date naissance", "naissance", "birth date", "birthdate"}:
            mapping["birth_date"] = idx
        elif key in {"poste", "position"}:
            mapping["position"] = idx
        elif key in {"nationalite", "nationality"}:
            mapping["nationality"] = idx
        elif key in {"statut", "role", "type", "feuille"}:
            mapping["role"] = idx
        elif key in {"titulaire", "starter"}:
            mapping["starter"] = idx
        elif key in {"remplacant", "remplacants", "substitute", "bench"}:
            mapping["substitute"] = idx
        elif key in {"capitaine", "cap", "captain"}:
            mapping["captain"] = idx
        elif key in {"gardien", "gb", "goalkeeper"}:
            mapping["goalkeeper"] = idx
        elif key in {"entree", "minute entree", "minute in"}:
            mapping["minute_in"] = idx
        elif key in {"sortie", "minute sortie", "minute out"}:
            mapping["minute_out"] = idx
        elif key in {"minute", "min"}:
            mapping["minute"] = idx
        elif key in {"evenement", "event", "type evenement", "action"}:
            mapping["event_type"] = idx
        elif key in {"carton", "card", "couleur"}:
            mapping["card_color"] = idx
        elif key in {"detail", "details", "observation", "note"}:
            mapping["detail"] = idx
        elif key in {"entrant", "joueur entrant", "in"}:
            mapping["player_in"] = idx
        elif key in {"sortant", "joueur sortant", "out"}:
            mapping["player_out"] = idx
        elif key in {"fonction", "role officiel", "officiel"}:
            mapping["official_role"] = idx
    return mapping


def get_cell(cells: list[str], mapping: dict[str, int], key: str) -> str | None:
    idx = mapping.get(key)
    if idx is None or idx >= len(cells):
        return None
    return clean_value(cells[idx])


def truthy_text(value: Any) -> bool:
    key = normalize_key(clean_value(value))
    return key in {"1", "x", "oui", "yes", "true", "vrai", "c", "cap", "capitaine", "g", "gb", "gardien", "titulaire"}


def canonical_event_type(value: str | None, detail: str | None = None) -> tuple[str, str | None]:
    key = normalize_key(value) or normalize_key(detail)
    if any(token in key for token in ["but", "goal", "penalty marque", "penalty"]):
        return "goal", None
    if any(token in key for token in ["jaune", "yellow", "cj"]):
        return "card", "yellow"
    if any(token in key for token in ["rouge", "red", "cr"]):
        return "card", "red"
    if any(token in key for token in ["remplacement", "changement", "substitution", "entrant", "sortant"]):
        return "substitution", None
    if any(token in key for token in ["observation", "note"]):
        return "note", None
    return key or "note", None


def extract_tables_from_text(text: str) -> list[list[str]]:
    return [split_cells(line) for line in text.splitlines() if "|" in line]


def parse_pipe_tables(text: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    players: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    officials: list[dict[str, Any]] = []
    staff: list[dict[str, Any]] = []
    current_header: list[str] | None = None
    current_mapping: dict[str, int] = {}
    current_kind: str | None = None

    for raw_line in text.splitlines():
        cells = split_cells(raw_line)
        if not cells or len(cells) < 2:
            continue
        normalized_cells = [normalize_key(cell) for cell in cells]
        header_candidate = map_header(cells)
        is_header = False
        if "minute" in header_candidate and ("event_type" in header_candidate or "card_color" in header_candidate):
            is_header = True
            current_kind = "events"
        elif "name" in header_candidate and ("team" in header_candidate or "side" in header_candidate or "number" in header_candidate):
            is_header = True
            current_kind = "players"
        elif "official_role" in header_candidate and "name" in header_candidate:
            is_header = True
            current_kind = "officials"
        elif any(c in {"staff", "encadrement", "fonction"} for c in normalized_cells) and "name" in header_candidate:
            is_header = True
            current_kind = "staff"
        if is_header:
            current_header = cells
            current_mapping = header_candidate
            continue
        if not current_header or not current_kind:
            continue
        # Skip table separators or repeated title rows.
        if all(not cell or set(cell) <= {"-", "_"} for cell in cells):
            continue

        if current_kind == "players":
            name = get_cell(cells, current_mapping, "name")
            if not name or normalize_key(name) in {"joueur", "nom"}:
                continue
            role = get_cell(cells, current_mapping, "role") or ""
            starter = truthy_text(get_cell(cells, current_mapping, "starter")) or normalize_key(role) in {"titulaire", "starter", "11", "onze"}
            substitute = truthy_text(get_cell(cells, current_mapping, "substitute")) or normalize_key(role) in {"remplacant", "substitute", "banc", "bench"}
            players.append(
                {
                    "team": get_cell(cells, current_mapping, "team"),
                    "side": get_cell(cells, current_mapping, "side"),
                    "number": get_cell(cells, current_mapping, "number"),
                    "name": name,
                    "license_number": get_cell(cells, current_mapping, "license_number"),
                    "birth_date": parse_date(get_cell(cells, current_mapping, "birth_date")),
                    "position": get_cell(cells, current_mapping, "position"),
                    "nationality": get_cell(cells, current_mapping, "nationality"),
                    "role": role or ("titulaire" if starter else "remplaçant" if substitute else None),
                    "starter": starter,
                    "substitute": substitute,
                    "captain": truthy_text(get_cell(cells, current_mapping, "captain")),
                    "goalkeeper": truthy_text(get_cell(cells, current_mapping, "goalkeeper")),
                    "minute_in": get_cell(cells, current_mapping, "minute_in"),
                    "minute_out": get_cell(cells, current_mapping, "minute_out"),
                }
            )
        elif current_kind == "events":
            minute, stoppage = parse_minute(get_cell(cells, current_mapping, "minute"))
            raw_event = get_cell(cells, current_mapping, "event_type") or get_cell(cells, current_mapping, "card_color") or "note"
            detail = get_cell(cells, current_mapping, "detail")
            event_type, inferred_card = canonical_event_type(raw_event, detail)
            card_color = inferred_card or normalize_key(get_cell(cells, current_mapping, "card_color")) or None
            if card_color in {"jaune", "yellow", "cj"}:
                card_color = "yellow"
            elif card_color in {"rouge", "red", "cr"}:
                card_color = "red"
            player = get_cell(cells, current_mapping, "name")
            related_player = None
            if event_type == "substitution":
                player = get_cell(cells, current_mapping, "player_in") or player
                related_player = get_cell(cells, current_mapping, "player_out")
            events.append(
                {
                    "minute": minute,
                    "stoppage": stoppage,
                    "team": get_cell(cells, current_mapping, "team") or get_cell(cells, current_mapping, "side"),
                    "player": player,
                    "related_player": related_player,
                    "event_type": event_type,
                    "card_color": card_color,
                    "detail": detail,
                }
            )
        elif current_kind == "officials":
            name = get_cell(cells, current_mapping, "name")
            if name:
                officials.append({"role": get_cell(cells, current_mapping, "official_role") or "Officiel", "name": name})
        elif current_kind == "staff":
            name = get_cell(cells, current_mapping, "name")
            if name:
                staff.append({"team": get_cell(cells, current_mapping, "team") or get_cell(cells, current_mapping, "side"), "role": get_cell(cells, current_mapping, "official_role") or get_cell(cells, current_mapping, "role"), "name": name})
    return players, events, officials, staff


def parse_line_events(text: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    line_patterns = [
        ("goal", re.compile(r"(?im)^\s*(?:but|goal)\s*[:\-]\s*(\d{1,3}(?:\+\d{1,2})?)\s*['’]?\s*(?:-|:)?\s*(.+)$")),
        ("yellow", re.compile(r"(?im)^\s*(?:carton\s+jaune|cj|yellow\s+card)\s*[:\-]\s*(\d{1,3}(?:\+\d{1,2})?)\s*['’]?\s*(?:-|:)?\s*(.+)$")),
        ("red", re.compile(r"(?im)^\s*(?:carton\s+rouge|cr|red\s+card)\s*[:\-]\s*(\d{1,3}(?:\+\d{1,2})?)\s*['’]?\s*(?:-|:)?\s*(.+)$")),
        ("substitution", re.compile(r"(?im)^\s*(?:remplacement|changement|substitution)\s*[:\-]\s*(\d{1,3}(?:\+\d{1,2})?)\s*['’]?\s*(?:-|:)?\s*(.+)$")),
    ]
    for event_name, pattern in line_patterns:
        for match in pattern.finditer(text):
            minute, stoppage = parse_minute(match.group(1))
            tail = clean_value(match.group(2))
            team = None
            player = tail
            related_player = None
            detail = None
            # Common: Team - Player - detail
            parts = [clean_value(part) for part in re.split(r"\s+-\s+|\s+–\s+", tail) if clean_value(part)]
            if len(parts) >= 2:
                team, player = parts[0], parts[1]
                detail = " - ".join(parts[2:]) if len(parts) > 2 else None
            # Common: Player (Team)
            paren = re.search(r"(.+?)\s*\((.+?)\)\s*(.*)$", tail)
            if paren:
                player = clean_value(paren.group(1))
                team = clean_value(paren.group(2))
                detail = clean_value(paren.group(3)) or detail
            if event_name == "substitution":
                # Entrée X / Sortie Y, or X remplace Y.
                in_match = re.search(r"(?:entrée|entrant|in)\s*[:=]?\s*([^/;]+)", tail, flags=re.I)
                out_match = re.search(r"(?:sortie|sortant|out)\s*[:=]?\s*([^/;]+)", tail, flags=re.I)
                repl_match = re.search(r"(.+?)\s+remplace\s+(.+)", tail, flags=re.I)
                if in_match:
                    player = clean_value(in_match.group(1))
                if out_match:
                    related_player = clean_value(out_match.group(1))
                if repl_match:
                    player = clean_value(repl_match.group(1))
                    related_player = clean_value(repl_match.group(2))
            event_type = "card" if event_name in {"yellow", "red"} else event_name
            card_color = "yellow" if event_name == "yellow" else "red" if event_name == "red" else None
            events.append({"minute": minute, "stoppage": stoppage, "team": team, "player": player, "related_player": related_player, "event_type": event_type, "card_color": card_color, "detail": detail})
    return events


def assign_players_to_teams(players: list[dict[str, Any]], home_name: str | None, away_name: str | None) -> tuple[list[dict[str, Any]], list[str]]:
    warnings: list[str] = []
    teams = {
        "home": {"side": "home", "name": home_name or "Équipe domicile", "players": [], "staff": []},
        "away": {"side": "away", "name": away_name or "Équipe extérieure", "players": [], "staff": []},
    }
    home_key = normalize_key(home_name)
    away_key = normalize_key(away_name)
    for player in players:
        team_value = player.pop("team", None)
        side_value = player.pop("side", None)
        key = normalize_key(team_value or side_value)
        side = None
        if key in {"home", "domicile", "equipe domicile", "local", "a"} or (home_key and key == home_key):
            side = "home"
        elif key in {"away", "exterieur", "exterieur", "visiteur", "equipe exterieure", "b"} or (away_key and key == away_key):
            side = "away"
        elif home_key and home_key in key:
            side = "home"
        elif away_key and away_key in key:
            side = "away"
        if side is None:
            side = "home" if len(teams["home"]["players"]) <= len(teams["away"]["players"]) else "away"
            warnings.append(f"Équipe non reconnue pour le joueur {player.get('name')}; affectation automatique côté {side}.")
        teams[side]["players"].append(player)
    return [teams["home"], teams["away"]], warnings


def attach_staff_to_teams(teams: list[dict[str, Any]], staff: list[dict[str, Any]]) -> list[str]:
    warnings: list[str] = []
    home_key = normalize_key(teams[0].get("name")) if teams else ""
    away_key = normalize_key(teams[1].get("name")) if len(teams) > 1 else ""
    for member in staff:
        team_value = member.pop("team", None)
        key = normalize_key(team_value)
        if key in {"home", "domicile", "a"} or (home_key and (key == home_key or home_key in key)):
            teams[0]["staff"].append(member)
        elif len(teams) > 1 and (key in {"away", "exterieur", "extérieur", "visiteur", "b"} or (away_key and (key == away_key or away_key in key))):
            teams[1]["staff"].append(member)
        else:
            warnings.append(f"Staff non affecté à une équipe: {member.get('name')}")
    return warnings


def parse_officials_from_labels(text: str) -> list[dict[str, Any]]:
    label_roles = [
        ("Arbitre central", ["Arbitre central", "Arbitre", "Referee"]),
        ("Assistant 1", ["Assistant 1", "1er assistant", "Premier assistant", "Assistant arbitre 1"]),
        ("Assistant 2", ["Assistant 2", "2e assistant", "Deuxième assistant", "Assistant arbitre 2"]),
        ("Quatrième arbitre", ["4e arbitre", "Quatrième arbitre", "Fourth official"]),
        ("Commissaire", ["Commissaire", "Commissaire du match"]),
        ("Délégué", ["Délégué", "Délégué du match", "Delegue"]),
        ("VAR", ["VAR"]),
        ("AVAR", ["AVAR"]),
    ]
    officials: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for role, labels in label_roles:
        name = find_value(text, labels)
        if name and normalize_key(name) not in {"", "non", "na"}:
            item = (normalize_key(role), normalize_key(name))
            if item not in seen:
                officials.append({"role": role, "name": name})
                seen.add(item)
    return officials


def parse_staff_from_labels(text: str, side: str) -> list[dict[str, Any]]:
    side_words = ["domicile", "home"] if side == "home" else ["extérieur", "exterieur", "away", "visiteur"]
    roles = [
        ("Entraîneur", ["Entraîneur", "Entraineur", "Coach"]),
        ("Entraîneur adjoint", ["Adjoint", "Entraîneur adjoint", "Entraineur adjoint"]),
        ("Médecin", ["Médecin", "Medecin", "Docteur"]),
        ("Kiné", ["Kiné", "Kine", "Kinésithérapeute"]),
    ]
    results: list[dict[str, Any]] = []
    for role, labels in roles:
        variants = []
        for label in labels:
            for side_word in side_words:
                variants.append(f"{label} {side_word}")
                variants.append(f"{side_word} {label}")
        value = find_value(text, variants)
        if value:
            results.append({"role": role, "name": value})
    return results


def parse_match_sheet(text: str, tables: list[dict[str, Any]] | None = None, source_name: str | None = None, extractor_warnings: list[str] | None = None, extractor_confidence: float = 0.0) -> dict[str, Any]:
    text = text or ""
    warnings = list(extractor_warnings or [])

    ftf_payload = try_parse_ftf_match_sheets(
        text,
        tables or [],
        source_name=source_name,
        extractor_warnings=warnings,
        extractor_confidence=extractor_confidence,
    )
    if ftf_payload is not None:
        return ftf_payload

    competition = find_value(text, ["Compétition", "Competition", "Épreuve", "Epreuve", "Championnat"])
    season = find_value(text, ["Saison", "Season"])
    round_label = find_value(text, ["Journée", "Journee", "Round", "Phase", "Tour"])
    date = parse_date(find_value(text, ["Date du match", "Date match", "Date"]))
    time = parse_time(find_value(text, ["Heure du match", "Heure", "Horaire", "Kick off", "Coup d'envoi", "Coup d’envoi"]))
    stadium = find_value(text, ["Stade", "Terrain", "Lieu"])
    city = find_value(text, ["Ville", "City"])
    home_team = find_value(text, ["Équipe domicile", "Equipe domicile", "Domicile", "Club domicile", "Equipe A", "Équipe A", "Home team"])
    away_team = find_value(text, ["Équipe extérieure", "Equipe extérieure", "Equipe exterieure", "Extérieur", "Exterieur", "Club extérieur", "Club exterieur", "Equipe B", "Équipe B", "Away team", "Visiteur"])
    score_home, score_away = parse_score(find_value(text, ["Score final", "Résultat", "Resultat", "Score"]))
    halftime_home, halftime_away = parse_score(find_value(text, ["Score mi-temps", "Mi-temps", "MT", "Half time", "Halftime"]))

    players, events, table_officials, staff = parse_pipe_tables(text)
    events.extend(parse_line_events(text))

    officials = parse_officials_from_labels(text)
    # Merge officials extracted from tables.
    existing_officials = {(normalize_key(o.get("role")), normalize_key(o.get("name"))) for o in officials}
    for official in table_officials:
        item = (normalize_key(official.get("role")), normalize_key(official.get("name")))
        if item not in existing_officials:
            officials.append(official)
            existing_officials.add(item)

    teams, assignment_warnings = assign_players_to_teams(players, home_team, away_team)
    warnings.extend(assignment_warnings)
    teams[0]["staff"].extend(parse_staff_from_labels(text, "home"))
    teams[1]["staff"].extend(parse_staff_from_labels(text, "away"))
    warnings.extend(attach_staff_to_teams(teams, staff))

    observations: list[dict[str, Any]] = []
    obs_value = find_value(text, ["Observations", "Observation", "Notes", "Réserves", "Reserves"])
    obs_section = find_section(text, ["Observations", "Observation", "Notes", "Réserves", "Reserves"])
    note = obs_value or obs_section
    if note:
        observations.append({"minute": None, "author": "document", "note": note, "severity": "note"})

    field_score = 0
    for item in [competition, season, round_label, date, time, stadium, home_team, away_team]:
        if item:
            field_score += 1
    field_score += min(len(players), 22) / 22 * 5
    field_score += min(len(events), 8) / 8 * 2
    parser_confidence = min(0.98, 0.20 + field_score / 15)
    confidence = round(max(parser_confidence, extractor_confidence * 0.7), 2)

    if not home_team:
        warnings.append("Équipe domicile non détectée automatiquement.")
    if not away_team:
        warnings.append("Équipe extérieure non détectée automatiquement.")
    if not players:
        warnings.append("Aucun joueur détecté. Adapter le modèle de feuille ou corriger le JSON dans l'écran de revue.")
    if score_home is None and score_away is None:
        warnings.append("Score final non détecté automatiquement.")

    return {
        "_meta": {
            "parser_version": PARSER_VERSION,
            "source_name": source_name,
            "confidence": confidence,
            "warnings": warnings,
            "raw_text_length": len(text),
            "tables_count": len(tables or []),
        },
        "match": {
            "competition": competition or "Ligue 1 Professionnelle",
            "season": season,
            "round": round_label,
            "date": date,
            "time": time,
            "stadium": stadium,
            "city": city,
            "home_team": home_team,
            "away_team": away_team,
            "score_home": score_home,
            "score_away": score_away,
            "halftime_home": halftime_home,
            "halftime_away": halftime_away,
            "status": "played",
            "observations": note,
            "notes": None,
        },
        "teams": teams,
        "officials": officials,
        "events": events,
        "observations": observations,
    }
