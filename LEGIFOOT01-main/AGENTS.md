# LEGIFOOT Agent Instructions

## Project overview

LEGIFOOT is a FastAPI + Jinja2 + SQLite web platform for Tunisian football match sheets. It supports document upload, parsing, manual match entry, discipline alerts, public consultation, and admin workflows.

## Stack

- Python
- FastAPI
- Jinja2
- SQLite
- Vanilla CSS
- Vanilla JavaScript
- Pytest
- Playwright for E2E tests

## Important rules

- Do not break existing routes.
- Do not remove existing features without explanation.
- Keep public and admin modes clearly separated.
- Preserve French UI copy unless improving clarity.
- Keep the app lightweight.
- Prefer clean FastAPI/Jinja improvements before introducing frontend frameworks.
- Do not commit generated files, caches, or local SQLite databases unless explicitly intended as sample data.

## Design direction

LEGIFOOT should feel like a premium football analytics and compliance platform.

Use:
- deep navy
- Tunisian red
- soft white/gray
- restrained green/yellow/red status colors
- clean typography
- strong spacing
- clear visual hierarchy
- professional dashboard components

Avoid:
- clutter
- excessive gradients
- too many decorative elements
- inconsistent cards/buttons/badges
- generic admin template look

## Code quality

- Keep files small where possible.
- Split large modules into route, service, repository, and utility layers.
- Use clear names.
- Avoid duplicate logic.
- Keep templates readable.
- Use reusable partials/macros where useful.
- Keep JavaScript dependency-free unless necessary.

## Security

- Never rely on default production secrets.
- Admin password and session secret must come from environment variables in production.
- Sanitize uploaded filenames.
- Validate uploaded file types and sizes.
- Protect admin-only routes.
- Review POST forms for CSRF protection.
- Avoid leaking sensitive errors.

## Testing

Run before finalizing changes:

```bash
python -m pytest
python -m pytest tests/test_app_flows.py
