# Détecteur de niches IT

**Plateforme Big Data de collecte et d'analyse des offres d'emploi en informatique**

[![CI](https://github.com/BRAHAMIManel/pfe-data-jobs-platform/actions/workflows/ci.yml/badge.svg?branch=app-finale)](https://github.com/BRAHAMIManel/pfe-data-jobs-platform/actions/workflows/ci.yml)

Projet de fin d'études — Master 2 Data Engineering, Institut F2i — Manel Brahami, 2026.

---

## En une phrase

La plateforme collecte chaque jour les offres d'emploi en informatique publiées sur France Travail, repère les territoires où les employeurs ont du mal à recruter, et indique à un candidat, à partir de son CV, les régions et les villes où il a le plus de chances.

> Le score n'est pas une probabilité d'embauche : il classe des territoires selon des signaux mesurés dans les offres.

---

## Le problème

Les candidats cherchent là où il y a le plus d'offres, donc là où il y a le plus de concurrence. Les sites d'emploi montrent des offres une par une, mais ne disent jamais **où** les employeurs peinent à recruter un profil donné. Cette information n'existe dans aucune annonce : on ne la voit qu'en suivant des milliers d'offres dans le temps.

## Le parcours du candidat

| Étape | Page | Ce qu'il voit |
|---|---|---|
| 0 | Le marché | nombre d'offres, évolution, compétences demandées, régions les moins saturées |
| 1 | Le CV | dépôt PDF ou Word, compétences et expérience lues automatiquement, corrigeables |
| 2 | Les territoires | classement des régions puis des villes, score sur 100, fiabilité, repère officiel BMO |
| 3 | Les offres | offres compatibles, lien vers France Travail, compétences à apprendre |

Le CV est lu **en local** et **n'est jamais enregistré**.

---

## Architecture

```
API France Travail ──> Collecte ──> raw (MinIO, JSON brut)
                                       │  PySpark : doublons, compétences
                                       v
                                    silver (MinIO, Parquet)
                                       │  chargement sans doublon
                                       v
                                    gold (PostgreSQL, schéma en étoile)
                                       │  dbt : modèles + 72 tests
                                       v
                                    Application Streamlit (lecture seule)
```

Tout est piloté par **Apache Airflow** (3 DAG enchaînés, chaque jour à 11 h UTC) et tourne dans **Docker Compose**.

| Couche | Outil | Rôle |
|---|---|---|
| Collecte | Python, API France Travail (OAuth2) | offres du domaine ROME M18, découpage par région si la limite de 3 150 offres est atteinte |
| raw | MinIO | réponses de l'API telles quelles, jamais modifiées : permet de tout recalculer |
| silver | PySpark, Parquet | suppression des doublons, extraction des compétences (repli JSON si Spark échoue) |
| gold | PostgreSQL | schéma en étoile : `fait_offre`, 7 dimensions, table pont des compétences |
| Analyse | dbt | `stg_offres` → `int_republications` → `mart_offres_candidat`, et 72 tests de données |
| Orchestration | Apache Airflow | `ingestion_france_travail` → `chargement_gold` → `detecteur_niches` |
| Application | Streamlit | calcul du score à la demande, à partir du CV |

---

## Le calcul du score

```
Score = 100 × (0,45 × Tension + 0,35 × Adéquation + 0,20 × Volume)
```

- **Tension** : 3 signaux comparés à la moyenne nationale, avec le même poids :
  - l'offre reste en ligne plus de 30 jours ;
  - France Travail signale un manque de candidats ;
  - l'employeur a retiré puis republié l'offre (cabinets exclus, 3 au plus par employeur et par ville).

  Les petits territoires sont **lissés** vers la moyenne. Un territoire dans la moyenne vaut 50.
- **Adéquation** : part des compétences demandées que le CV couvre.
- **Volume** : nombre d'offres compatibles, sur une échelle logarithmique.

Chaque territoire a une étiquette **Fiable / Indicatif / Fragile**. Les territoires fragiles (moins de 10 offres) passent en dernier.

Le calcul a été **confronté à l'enquête BMO 2026** (`scripts/calibrage_bmo.py`) et soumis à une **analyse de sensibilité** des poids (`scripts/sensibilite_poids.py`).

---

## Qualité et sécurité

**Tests**
- `pytest` : collecte, nettoyage, PySpark, calcul du score (`tests/`).
- `dbt test` : 72 tests sur les vraies données, à chaque chargement.
- Intégration continue (GitHub Actions) à chaque push : tests, validation dbt, recherche de secrets (gitleaks), failles connues des bibliothèques (pip-audit).

**Sécurité** (détail dans `securite/analyse_menaces.md`, 12 menaces)
- Ports ouverts uniquement sur `127.0.0.1`.
- Moindre privilège : l'application lit l'entrepôt avec un compte en lecture seule ; le compte MinIO de la collecte ne peut ni supprimer, ni écrire ailleurs que dans raw et silver.
- Secrets dans `.env` (jamais envoyé sur GitHub), modèle dans `.env.example`.
- Images Docker figées par empreinte sha256, application exécutée sans droits root.
- `scripts/verifier_securite.py` vérifie 16 contrôles en essayant réellement les actions interdites.

---

## Installation

Il faut Docker Desktop et un compte développeur France Travail (https://francetravail.io).

```bash
git clone https://github.com/BRAHAMIManel/pfe-data-jobs-platform.git
cd pfe-data-jobs-platform
git checkout app-finale

# Copier le modèle puis remplir les valeurs (identifiants, mots de passe, clés)
cp .env.example .env

docker compose build
docker compose up -d
```

| Service | Adresse (depuis la machine uniquement) |
|---|---|
| Application | http://localhost:8501 |
| Airflow | http://localhost:8080 |
| Console MinIO | http://localhost:9001 |

Dans Airflow, activer le DAG `ingestion_france_travail` : il déclenche ensuite les deux autres.

### Commandes utiles

```bash
# Rapport de collecte (écrit dans logs/rapports/)
docker compose exec airflow-scheduler python /opt/airflow/scripts/rapport_ingestion.py

# Tests de données dbt
docker compose exec airflow-scheduler bash -c "cd /opt/airflow/dbt && /home/airflow/dbt-venv/bin/dbt test --profiles-dir ."

# Contrôles de sécurité
docker compose exec airflow-scheduler python /opt/airflow/scripts/verifier_securite.py

# Mesures pour le mémoire
docker compose exec airflow-scheduler python /opt/airflow/scripts/mesure_signaux.py
docker compose exec airflow-scheduler python /opt/airflow/scripts/calibrage_bmo.py
docker compose exec app python /scripts/sensibilite_poids.py
```

---

## Organisation du dépôt

```
app/          application Streamlit (pages, calcul du score, style)
dags/         les 3 DAG Airflow
scripts/      collecte, nettoyage, PySpark, entrepôt, mesures, sécurité
dbt/          modèles, seeds (cabinets intermédiaires, BMO 2026) et tests
tests/        tests pytest
securite/     analyse de menaces, politique MinIO du compte de collecte
.github/      intégration continue
```

---

## Limites connues

- Une seule source (France Travail) : une partie du marché, surtout les postes de cadres, n'y figure pas.
- Historique court, avec des jours sans collecte quand la machine est éteinte.
- Signaux indirects : on ne connaît pas les embauches réelles.
- Pas de lien établi avec l'enquête BMO : les poids des signaux restent égaux.