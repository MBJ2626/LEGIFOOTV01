# LEGIFOOT

Plateforme FastAPI + Jinja2 + SQLite pour ingestion, saisie manuelle et suivi disciplinaire des feuilles de match du football tunisien.

## Setup rapide

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
```

Lancer l’application :

```bash
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

## Variables d’environnement

- `LEGIFOOT_ENV` : `development` (défaut) ou `production`.
- `LEGIFOOT_ADMIN_PASSWORD` : mot de passe admin.
- `LEGIFOOT_SECRET_KEY` : clé de signature de session.
- `LEGIFOOT_HTTPS_ONLY` : `1` pour forcer cookie secure en dev HTTPS.
- `LEGIFOOT_DB_PATH` : chemin SQLite.
- `LEGIFOOT_UPLOAD_DIR` : répertoire d’upload.
- `LEGIFOOT_EXPORT_DIR` : répertoire d’exports.
- `LEGIFOOT_MAX_UPLOAD_MB` : taille max d’upload en Mo (défaut 20).

### Notes sécurité production

En production (`LEGIFOOT_ENV=production`) :
- `LEGIFOOT_SECRET_KEY` est obligatoire (pas la valeur par défaut).
- `LEGIFOOT_ADMIN_PASSWORD` est obligatoire (pas la valeur par défaut).
- Les cookies de session passent en `Secure` + `SameSite=Strict`.

## Tests

```bash
python -m pytest
python -m pytest tests/test_app_flows.py
python -m pytest tests/test_e2e_playwright.py
```

Pour Playwright :

```bash
python -m playwright install chromium
```

## Version Python

Le déploiement Render est épinglé sur Python `3.12.13` via `.python-version` et `PYTHON_VERSION` dans `render.yaml` afin d’éviter les changements de runtime par défaut.

Le blueprint Render à la racine du dépôt définit `rootDir: LEGIFOOT01-main` pour que Render exécute les commandes depuis le dossier applicatif où se trouvent `requirements.txt` et `app/main.py`.

Le fichier `railway.json` à la racine applique la même règle pour Railway : les commandes `build` et `start` commencent par `cd LEGIFOOT01-main` afin que `uvicorn app.main:app` trouve le package `app`.

## Déploiement (résumé)

1. Définir toutes les variables d’environnement ci-dessus.
2. Activer HTTPS côté reverse proxy.
3. Monter un volume persistant pour SQLite + uploads + exports.
4. Exclure les données runtime des commits (`.gitignore` inclus).

## Admin / sécurité

- Routes admin protégées via session signée.
- Uploads validés par extension + limite de taille.
- Noms de fichiers uploadés normalisés.
- Exports CSV nettoyés pour limiter l’injection de formules.

## Arborescence

```text
app/
  main.py
  database.py
  extractor.py
  parser.py
  ftf_parser.py
  templates/
  static/
tests/
examples/
```
