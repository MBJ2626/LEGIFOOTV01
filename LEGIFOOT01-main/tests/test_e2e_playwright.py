from __future__ import annotations

import importlib.util
import os
import re
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import urlopen

import pytest

HAS_PLAYWRIGHT = importlib.util.find_spec("playwright") is not None
pytestmark = pytest.mark.skipif(not HAS_PLAYWRIGHT, reason="playwright.sync_api is not installed")

if HAS_PLAYWRIGHT:
    from playwright.sync_api import Page, expect, sync_playwright
else:  # pragma: no cover - used only when Playwright is absent locally
    Page = object
    expect = None
    sync_playwright = None


ROOT_DIR = Path(__file__).resolve().parents[1]


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture()
def live_server(tmp_path: Path) -> str:
    port = _free_port()
    env = os.environ.copy()
    env.update(
        {
            "LEGIFOOT_ADMIN_PASSWORD": "admin123",
            "LEGIFOOT_DB_PATH": str(tmp_path / "data" / "matchsheets.sqlite3"),
            "LEGIFOOT_UPLOAD_DIR": str(tmp_path / "uploads"),
            "LEGIFOOT_EXPORT_DIR": str(tmp_path / "exports"),
            "LEGIFOOT_SECRET_KEY": "playwright-test-secret",
        }
    )
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=ROOT_DIR,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    base_url = f"http://127.0.0.1:{port}"
    deadline = time.time() + 20
    while time.time() < deadline:
        if proc.poll() is not None:
            output = proc.stdout.read() if proc.stdout else ""
            raise RuntimeError(f"LEGIFOOT server stopped during startup:\n{output}")
        try:
            with urlopen(base_url, timeout=0.5) as response:
                if response.status == 200:
                    break
        except Exception:
            time.sleep(0.2)
    else:
        proc.terminate()
        output = proc.stdout.read() if proc.stdout else ""
        raise RuntimeError(f"LEGIFOOT server did not start before timeout:\n{output}")

    try:
        yield base_url
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


@pytest.fixture()
def page():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(locale="fr-FR")
        page = context.new_page()
        yield page
        context.close()
        browser.close()


def _login_as_admin(page: Page, base_url: str) -> None:
    page.goto(f"{base_url}/login?next=/manual")
    expect(page.get_by_role("heading", name="Connexion administrateur")).to_be_visible()
    page.locator('input[name="password"]').fill("admin123")
    page.get_by_role("button", name="Se connecter").click()
    expect(page).to_have_url(f"{base_url}/manual")


def test_manual_match_creation_and_public_discovery(page: Page, live_server: str) -> None:
    page.goto(f"{live_server}/manual")
    expect(page).to_have_url(re.compile(r"/login\?next=/manual$"))

    _login_as_admin(page, live_server)
    expect(page.get_by_role("heading", name="Saisie manuelle d'une feuille de match")).to_be_visible()

    page.locator('input[name="season"]').fill("2025-2026")
    page.locator('input[name="round_label"]').fill("J1")
    page.locator('select[name="status"]').select_option("played")
    page.locator('input[name="match_date"]').fill("2026-03-10")
    page.locator('input[name="match_time"]').fill("15:30")
    page.locator('input[name="stadium"]').fill("Stade Olympique de Radès")
    page.locator('input[name="city"]').fill("Radès")
    page.locator('input[name="home_team"]').fill("Espérance Sportive de Tunis")
    page.locator('input[name="away_team"]').fill("Club Africain")
    page.locator('input[name="score_home"]').fill("2")
    page.locator('input[name="score_away"]').fill("1")
    page.locator('textarea[name="home_players"]').fill("10; Test Buteur; LIC10; titulaire; oui; non; Attaquant; TN;")
    page.locator('textarea[name="away_players"]').fill("4; Test Défenseur; LIC04; titulaire; non; non; Défenseur; TN;")
    page.locator('textarea[name="officials"]').fill("ARBITRE; Test Arbitre")
    page.locator('textarea[name="goals"]').fill("12; home; Test Buteur; frappe\n78; away; Test Défenseur; tête")
    page.locator('textarea[name="cards"]').fill(
        "20; home; Test Buteur; jaune; contestation\n"
        "55; home; Test Buteur; jaune; faute tactique\n"
        "88; away; Test Défenseur; rouge; faute grossière"
    )
    page.locator('textarea[name="observations"]').fill("90; Analyste; note; Parcours critique validé")
    page.get_by_role("button", name="Insérer le match dans la base").click()

    expect(page).to_have_url(re.compile(r"/matches/\d+$"))
    expect(page.get_by_text("Espérance Sportive de Tunis")).to_be_visible()
    expect(page.get_by_text("Club Africain")).to_be_visible()
    expect(page.get_by_text("2 - 1")).to_be_visible()
    expect(page.get_by_text("Test Buteur")).to_be_visible()

    page.goto(f"{live_server}/matches?q=Espérance")
    expect(page.get_by_role("heading", name="Matchs")).to_be_visible()
    expect(page.get_by_text("Espérance Sportive de Tunis")).to_be_visible()
    expect(page.get_by_text("Club Africain")).to_be_visible()

    page.goto(f"{live_server}/search?q=Test+Buteur")
    expect(page.get_by_role("heading", name="Recherche globale")).to_be_visible()
    expect(page.get_by_text("Test Buteur")).to_be_visible()


def test_notifications_and_api_after_seeded_match(page: Page, live_server: str) -> None:
    _login_as_admin(page, live_server)
    page.locator('input[name="season"]').fill("2025-2026")
    page.locator('input[name="home_team"]').fill("Club Discipline A")
    page.locator('input[name="away_team"]').fill("Club Discipline B")
    page.locator('input[name="score_home"]').fill("0")
    page.locator('input[name="score_away"]').fill("0")
    page.locator('textarea[name="home_players"]').fill("8; Joueur Sous Surveillance; LIC08; titulaire; non; non; Milieu; TN;")
    page.locator('textarea[name="cards"]').fill(
        "10; home; Joueur Sous Surveillance; jaune; faute\n"
        "35; home; Joueur Sous Surveillance; jaune; contestation\n"
        "70; home; Joueur Sous Surveillance; jaune; antijeu"
    )
    page.get_by_role("button", name="Insérer le match dans la base").click()
    expect(page).to_have_url(re.compile(r"/matches/\d+$"))

    page.goto(f"{live_server}/notifications?threshold=3&include_watch=1")
    expect(page.get_by_role("heading", name="Centre discipline")).to_be_visible()
    expect(page.get_by_text("Joueur Sous Surveillance")).to_be_visible()
    expect(page.get_by_text("Priorité critique")).to_be_visible()

    page.goto(f"{live_server}/api/notifications?threshold=3&include_watch=1")
    expect(page.locator("body")).to_contain_text("Joueur Sous Surveillance")
    expect(page.locator("body")).to_contain_text("critical")
