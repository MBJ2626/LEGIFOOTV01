# LEGIFOOT

Plateforme web pour uploader, extraire, saisir manuellement et analyser les feuilles de match du football tunisien : Ligue 1, Ligue 2 et Coupe de Tunisie.

# LEGIFOOT

Prototype web local pour uploader des feuilles de match de football tunisien, extraire les données, les revoir puis les insérer dans une base SQLite exploitable.

## Fonctionnalités

- Upload de fichiers `.pdf`, `.docx`, `.xlsx`, `.xlsm`, `.xls`, `.csv`.
- Extraction de texte depuis PDF texte, Word DOCX, Excel et CSV.
- Extraction spécialisée des PDF officiels FTF `FEUILLE DE MATCH INFORMATISÉE`.
- Détection d'un PDF contenant plusieurs matchs : un seul PDF peut créer plusieurs matchs en base.
- Brouillon JSON modifiable avant insertion.
- Base SQLite avec matchs, clubs, joueurs, staff, officiels, événements, observations.
- Événements structurés : buts, cartons jaunes, cartons rouges, remplacements, blessés si présents.
- Pages web : dashboard, documents, matchs, détail match, joueurs, événements, arbitres.
- Exports CSV depuis l'interface.
- Notes et observations ajoutables après validation d'un match.

## Amélioration ajoutée pour les feuilles FTF Ligue 1

Le fichier `app/ftf_parser.py` ajoute un parser dédié au format observé dans les feuilles officielles FTF :

- segmentation automatique par page de début `FEUILLE DE MATCH INFORMATISÉE` ;
- regroupement des pages d'un même match ;
- lecture des deux colonnes titulaires/remplaçants avec association domicile/extérieur ;
- extraction des deux colonnes de staff ;
- extraction des remplacements ;
- extraction des officiels du match ;
- extraction des joueurs avertis, expulsés et blessés ;
- extraction des buts depuis le bloc supérieur du PDF lorsque l'icône de but est perdue par l'extraction texte ;
- mapping automatique des codes clubs, par exemple `EST`, `CSS`, `ASR`, vers les vrais clubs du match ;
- contrôles simples : 11 titulaires par équipe et cohérence entre score final et nombre de buts extraits.

## Installation locale

```bash
cd LEGIFOOT01
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Sur Windows PowerShell :

```powershell
cd LEGIFOOT01
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Ouvre ensuite :

```text
http://127.0.0.1:8000
```


## Framework et tests

Le site est une application **FastAPI** rendue avec **Jinja2**, servie en local par **Uvicorn** et persistée dans une base **SQLite**. Les dépendances d'exécution sont listées dans `requirements.txt`; les dépendances de test et d'E2E sont listées dans `requirements-dev.txt`.

Setup complet pour développer et tester :

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
python -m playwright install chromium
```

Commandes de test :

```bash
# Suite pytest complète. Les tests Playwright sont ignorés automatiquement si le paquet playwright n'est pas installé.
python -m pytest

# Parcours applicatif rapide via TestClient : login admin, saisie manuelle et API notifications.
python -m pytest tests/test_app_flows.py

# Parcours critiques navigateur : login admin, saisie manuelle, recherche, matchs, notifications et API.
python -m pytest tests/test_e2e_playwright.py
```

Pour isoler les données pendant les tests ou en CI, les chemins peuvent être remplacés par variables d'environnement :

```bash
LEGIFOOT_DB_PATH=/tmp/legifoot/matchsheets.sqlite3 \
LEGIFOOT_UPLOAD_DIR=/tmp/legifoot/uploads \
LEGIFOOT_EXPORT_DIR=/tmp/legifoot/exports \
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

## Test rapide

Des fichiers d'exemple sont dans le dossier `examples/` :

- `sample_match_sheet.docx`
- `sample_match_sheet.xlsx`
- `sample_match_sheet.pdf`

Va dans `Upload`, envoie un fichier, vérifie le JSON, puis clique sur `Insérer dans la base`.

Avec un PDF officiel FTF contenant plusieurs feuilles de match, la page de revue indique `PDF multi-match`, le nombre de matchs détectés et un tableau de prévisualisation. La validation insère tous les matchs détectés.


## Analyse en ligne de commande

Tu peux tester l'extraction sans lancer le serveur :

```bash
python tools/analyze_file.py /chemin/vers/feuille.pdf --json-out sortie.json
```

La commande affiche le nombre de matchs détectés, les scores, joueurs, buts, cartons et remplacements.

## Structure

```text
app/
  main.py          routes FastAPI
  database.py      schéma SQLite + requêtes + insertion single/batch
  extractor.py     lecture PDF / DOCX / Excel / CSV
  parser.py        parser générique + routage vers parser FTF
  ftf_parser.py    parser dédié aux feuilles officielles FTF
  templates/       pages HTML Jinja
  static/          CSS + JS
  uploads/         fichiers uploadés
  data/            base SQLite + exports
examples/          fichiers de test
```

## Limites connues

- Les PDF scannés nécessitent un vrai OCR. Le prototype les détecte mais ne peut pas lire automatiquement une image sans OCR.
- Les icônes de but/carton ne sont pas toujours conservées dans le texte PDF. Le parser FTF compense en croisant le bloc supérieur avec les tableaux `JOUEURS AVERTIS` et `JOUEURS EXPULSÉS`.
- Les feuilles officielles peuvent évoluer. Si la FTF change la mise en page, il faudra enrichir `app/ftf_parser.py`.
- Le format Word ancien `.doc` doit idéalement être converti en `.docx` ou PDF texte.

## Prochaine évolution recommandée

- Ajouter un moteur OCR : Tesseract, PaddleOCR, Google Vision ou Azure Document Intelligence.
- Ajouter authentification et rôles : admin, analyste, lecteur.
- Remplacer SQLite par PostgreSQL pour un déploiement multi-utilisateurs.
- Ajouter une couche LLM multimodale pour transformer les feuilles complexes en JSON avec score de confiance par champ.
- Ajouter validation avancée : joueurs sortis, rouges, suspensions, minute de but après remplacement, homonymes, licences incohérentes.

## Notifications discipline

Le site contient maintenant un onglet **Notifications** (`/notifications`). Il calcule automatiquement les alertes à partir des événements de type carton stockés en base.

Règles MVP :

- **Carton rouge** : notification critique immédiate pour vérifier la suspension du joueur.
- **3 cartons jaunes sur une période donnée** : notification critique indiquant un risque de suspension automatique au match suivant.
- **2 cartons jaunes sur la période** : pré-alerte de surveillance, activable/désactivable depuis la page.

Par défaut, la page utilise :

```text
Période : 10 matchs du club
Seuil : 3 cartons jaunes
```

Ces paramètres sont modifiables depuis l'interface :

```text
http://127.0.0.1:8000/notifications?period=10&threshold=3&include_watch=1
```

Une API JSON est aussi disponible :

```text
http://127.0.0.1:8000/api/notifications
```

Important : le système signale les risques automatiquement, mais la décision finale doit être vérifiée avec les règlements et décisions officielles de la compétition.


## Saisie manuelle sans fichier

La version avec notifications contient aussi l'onglet **Saisie manuelle** (`/manual`). Il permet de créer un match sans PDF, Word ou Excel :

- informations du match : compétition, saison, journée, date, heure, stade, score ;
- joueurs domicile et extérieur ;
- staff des deux équipes ;
- officiels/arbitres ;
- buts ;
- cartons jaunes et rouges ;
- remplacements ;
- observations et notes.

Les listes utilisent un format simple : une ligne par élément, avec les champs séparés par `;`.

Exemples :

```text
# Joueurs
1; JOUEUR NOM; 990101001; titulaire; oui; oui; Gardien; TN;
10; JOUEUR NOM; 990101002; remplaçant;;;;;

# Cartons
58; home; JOUEUR NOM; jaune; contestation
82; away; JOUEUR NOM; rouge; faute grossière

# Remplacements
65; home; JOUEUR ENTRANT; JOUEUR SORTANT;
```

Après validation, le match est inséré directement dans la base et devient visible dans les onglets Matchs, Joueurs, Événements, Arbitres et Notifications.


## Accès visiteur / administrateur

- Par défaut, la plateforme s’ouvre en **mode visiteur** : toutes les données publiques sont consultables, mais les actions d’ajout, d’upload, de correction, d’observation et d’export administrateur sont masquées ou protégées.
- Le bouton **Connexion admin** donne accès à la version complète du site.
- Définissez le mot de passe avec la variable d’environnement `LEGIFOOT_ADMIN_PASSWORD`. En développement local, la valeur par défaut est `admin123`.
- Pour sécuriser les sessions en production, définissez aussi `LEGIFOOT_SECRET_KEY` avec une valeur longue et aléatoire.


## Bloc A+B premium
Cette version ajoute une séparation visiteur/admin plus propre, masque les actions admin côté visiteur, ajoute des filtres avancés sur les pages Matchs/Joueurs/Événements/Arbitres/Notifications, enrichit la page détail match, ajoute des cartes et barres analytiques sur le dashboard et améliore l'affichage mobile des tableaux sous forme de cartes.


## Version UX Optimale 25

Cette version ajoute une couche d'expérience premium couvrant les 25 améliorations demandées :

- dashboard cockpit avec filtres avancés sticky, badges actifs et raccourcis admin ;
- recherche globale `/search` sur matchs, joueurs, clubs, arbitres, événements et documents ;
- pages clubs, fiches club, fiches joueur et fiches arbitre/officiel ;
- centre de contrôle admin `/admin` avec documents à traiter, alertes critiques et raccourcis ;
- notifications disciplinaires enrichies avec statut, commentaire admin et export des joueurs à risque ;
- pages Matchs/Joueurs/Événements/Arbitres plus filtrables et plus lisibles ;
- UX mobile optimisée avec tables transformées en cartes ;
- micro-interactions, favoris locaux, toasts, filtres actifs et aide/méthodologie ;
- upload et saisie manuelle mieux guidés, avec workflow visible et statuts élargis.

## LEGIFOOT UX optimization v25

Cette version ajoute les améliorations UX/design suivantes : page Analyse discipline, statuts de publication des matchs, score de complétude, panneau données manquantes, centre admin enrichi, onglets dans la fiche match, filtres repliables, vues cartes/tableau, états vides premium, toasts de confirmation, favoris locaux, aides contextuelles, badges uniformisés, accessibilité renforcée, workflow upload plus explicite et séparation consultation publique / administration.

Principales routes ajoutées :

- `/discipline` : analyse disciplinaire globale.
- `/mes-suivis` : favoris locaux côté navigateur.
- `POST /matches/{match_id}/status` : modification du statut d’un match côté admin.

Statuts recommandés : `draft`, `to_review`, `validated`, `published`, `played`, `incomplete`, `archived`.

## Mise à jour graphique - Sports Command Dashboard

Cette version applique la direction **Option C : Data Clubhouse** avec une couche visuelle inspirée broadcast sport :

- Match Focus Card
- Discipline Board
- Top 5 clubs sanctionnés
- Timeline récente
- Match Intensity Score
- Club Risk Cards
- Barre d’état compétition/saison
- Mini terrain événementiel
- Cartes “À la une”
- Stat Pills
- Cartes statistiques sport premium
- Identité visuelle football tunisien premium
- Structure Sports Command Dashboard

Les filtres restent placés en bas de page pour conserver une lecture directe du dashboard.
