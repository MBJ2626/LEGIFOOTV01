#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.extractor import extract_document  # noqa: E402
from app.parser import parse_match_sheet  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyse une feuille de match et affiche un résumé JSON.")
    parser.add_argument("file", type=Path, help="Chemin du PDF/DOCX/XLSX/CSV à analyser")
    parser.add_argument("--json-out", type=Path, default=None, help="Chemin optionnel pour écrire le JSON complet")
    args = parser.parse_args()

    if not args.file.exists():
        print(f"Fichier introuvable: {args.file}", file=sys.stderr)
        return 2

    extracted = extract_document(args.file)
    payload = parse_match_sheet(
        extracted.text,
        extracted.tables,
        source_name=args.file.name,
        extractor_warnings=extracted.warnings,
        extractor_confidence=extracted.confidence,
    )

    matches = payload.get("matches") or [payload]
    print(f"Fichier: {args.file.name}")
    print(f"Type: {extracted.file_type} | tables: {len(extracted.tables)} | confiance: {payload.get('_meta', {}).get('confidence')}")
    print(f"Matchs détectés: {len(matches)}")
    for i, item in enumerate(matches, start=1):
        match = item.get("match", {})
        teams = item.get("teams", [])
        players = sum(len(team.get("players", []) or []) for team in teams)
        events = item.get("events", []) or []
        goals = sum(1 for event in events if event.get("event_type") == "goal")
        yellows = sum(1 for event in events if event.get("event_type") == "card" and event.get("card_color") == "yellow")
        reds = sum(1 for event in events if event.get("event_type") == "card" and event.get("card_color") == "red")
        subs = sum(1 for event in events if event.get("event_type") == "substitution")
        print(
            f"{i}. {match.get('home_team')} vs {match.get('away_team')} | "
            f"{match.get('date')} {match.get('time')} | "
            f"score {match.get('score_home')}-{match.get('score_away')} | "
            f"joueurs {players} | buts {goals} | jaunes {yellows} | rouges {reds} | remplacements {subs}"
        )
        warnings = item.get("_meta", {}).get("warnings") or []
        if warnings:
            print("   À vérifier: " + " ; ".join(warnings[:4]))

    parent_warnings = payload.get("_meta", {}).get("warnings") or []
    if parent_warnings:
        print("\nWarnings globaux:")
        for warning in parent_warnings[:10]:
            print(f"- {warning}")

    if args.json_out:
        args.json_out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nJSON écrit: {args.json_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
