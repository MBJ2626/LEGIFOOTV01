# LEGIFOOT Agent Instructions

## Project overview
LEGIFOOT is a FastAPI + Jinja2 + SQLite platform for Tunisian football match-sheet ingestion, manual entry, discipline alerts, and public consultation.

## Stack
- FastAPI
- Jinja2 templates
- SQLite
- Vanilla CSS + Vanilla JavaScript
- Pytest + Playwright

## Folder structure
- `app/main.py`: app wiring + HTTP routes
- `app/database.py`: schema, repositories, export helpers
- `app/templates/`: server-rendered UI
- `app/static/css/app.css`: design system styles
- `app/static/js/app.js`: front-end interactions
- `tests/`: integration and E2E tests

## Coding conventions
- Keep routes backward compatible; do not rename existing URLs without redirects/tests.
- Prefer incremental refactors over large rewrites.
- Keep template variables explicit and stable.
- Use dependency-free JS and semantic HTML.
- Avoid duplicated logic; extract helpers where safe.

## Security rules
- In production, require `LEGIFOOT_SECRET_KEY` and `LEGIFOOT_ADMIN_PASSWORD` from environment.
- Validate upload extension and size before parsing.
- Sanitize uploaded filenames.
- Keep admin-only actions protected (`require_admin`).
- Avoid exposing raw internals in user-facing errors.

## Design system rules
- Use a premium, calm football-data visual language.
- Keep spacing, typography, and component hierarchy consistent.
- Reuse button/card/badge/table patterns.
- Ensure dark mode and reduced-motion behavior remain usable.

## Testing commands
```bash
python -m pytest
python -m pytest tests/test_app_flows.py
python -m pytest tests/test_e2e_playwright.py
```

## Do-not-break rules
- Match ingestion, review/finalize flow, and manual entry must continue to work.
- `/api/matches` and `/api/notifications` responses must stay compatible with tests.
- Notifications severity and watchlist logic must remain stable.

## Deployment notes
- Set `LEGIFOOT_ENV=production` in production.
- Set secure cookies with HTTPS (`LEGIFOOT_HTTPS_ONLY=1` or production env).
- Keep local SQLite files out of commits unless intentionally added as sample data.
