# PFE — Plateforme Big Data de collecte et d'analyse des offres d'emploi

Projet de fin d'études — Master 2 Data Engineering
Auteure : Manel Brahami
Soutenance prévue : début décembre 2026

---

## 📌 En une phrase

Un outil qui collecte automatiquement les offres d'emploi Data/IA en France, les analyse, et indique à un candidat **où concentrer ses candidatures pour maximiser ses chances** — pas juste où il y a le plus d'offres, mais où il y a le meilleur rapport demande/concurrence.

---

## 👤 Côté utilisateur — à quoi ça sert

### Le problème

Un candidat qui cherche un poste Data/IA voit aujourd'hui une liste brute d'offres (LinkedIn, France Travail...), sans savoir où la concurrence est forte ou faible. Beaucoup de candidatures partent donc "au hasard", sans stratégie.

### Le parcours utilisateur

1. **L'utilisateur entre son profil** : compétences (ex. "Python, SQL, Airflow"), zone géographique souhaitée.
2. **Il obtient un classement de villes/opportunités**, calculé selon le volume d'offres disponibles et une estimation de la concurrence pour ce profil précis.
3. **Il sélectionne une ville** qui l'intéresse et consulte la liste des offres réelles correspondantes, avec lien direct vers l'offre d'origine.
4. **(Bonus, à valider avec le tuteur)** Il peut générer un brouillon de message de candidature personnalisé pour une offre choisie, qu'il relit et envoie lui-même.

### Ce que l'utilisateur reçoit

Pas une simple liste d'offres, mais une **aide à la décision** : où chercher en priorité, avec les offres concrètes à l'appui.

---

## ⚙️ Côté technique — comment ça fonctionne

### Vue d'ensemble du pipeline

```
[Ingestion] → [Normalisation] → [Orchestration] → [Data Lake] → [Traitement] → [Data Warehouse] → [Détecteur de niches] → [Restitution]
```

### 1. Ingestion (collecte des données brutes)

- **France Travail** : API REST officielle, authentification OAuth2 (client_credentials), pagination par blocs de 150 offres.
- **LinkedIn** : scraping des pages publiques de recherche (`requests` + `BeautifulSoup`), sans authentification, avec délais entre requêtes. *Usage exploratoire uniquement — fragile et à faible volume, en dehors du périmètre garanti du pipeline principal.*
- **Adzuna / APEC** : sources complémentaires envisagées (API pour Adzuna, à évaluer pour APEC).

### 2. Normalisation

Chaque source a son propre format JSON. Un adaptateur par source convertit vers un schéma commun :

```python
{
  "id_offre": str,            # hash titre + entreprise + ville
  "source": str,               # "france_travail" | "linkedin" | ...
  "titre": str,
  "entreprise": str,
  "ville": str,
  "date_publication": str,
  "lien_offre": str,
  "peu_concurrentielle": bool | None
}
```

### 3. Orchestration — Apache Airflow

Un DAG planifie et enchaîne les tâches de collecte, normalisation et écriture, avec gestion automatique des tentatives en cas d'échec (ex. erreur 500 côté API).

### 4. Data Lake — MinIO

Stockage des données brutes normalisées, organisées par date, pour garder un historique exploitable dans l'analyse de tendances.

### 5. Traitement — PySpark

Nettoyage, dédoublonnage inter-sources (basé sur `id_offre`), normalisation des champs (notamment les villes, dont le format diffère selon les sources).

### 6. Modélisation — dbt + PostgreSQL

Schéma en étoile :
- Table de faits `offres`
- Dimensions `villes`, `competences`, `temps`

Tests de qualité de données automatisés via dbt (ex. absence de doublons, absence de valeurs nulles critiques).

### 7. Détecteur de niches d'opportunités (fonctionnalité différenciante)

Calcul, pour chaque combinaison ville × compétence, d'un score croisant volume de demande et rareté estimée du profil recherché :

```sql
SELECT ville, competence,
       COUNT(*) AS volume_demande,
       COUNT(*) FILTER (WHERE peu_concurrentielle) AS volume_peu_concurrentiel
FROM offres
GROUP BY ville, competence
```

### 8. Industrialisation — Docker / Docker Compose

L'ensemble de la stack (Airflow, PostgreSQL, MinIO) est conteneurisé et lancé via `docker-compose up`, pour une exécution reproductible sur n'importe quelle machine.

### 9. Restitution (légère)

Un tableau de bord minimal (Metabase) permet une vérification visuelle rapide des indicateurs clés. Cette couche reste volontairement secondaire : l'effort du projet porte sur la robustesse du pipeline (ingestion → orchestration → transformation → stockage), cœur de métier Data Engineer.

---

## 🧱 Stack technique

| Couche | Technologie |
|---|---|
| Ingestion | Python (`requests`, `BeautifulSoup`) |
| Orchestration | Apache Airflow |
| Data Lake | MinIO |
| Traitement | PySpark |
| Modélisation | dbt |
| Data Warehouse | PostgreSQL |
| Industrialisation | Docker / Docker Compose |
| CI/CD (bonus) | GitHub Actions |
| Restitution | Metabase |

---

## 📊 État d'avancement

| Étape | Statut |
|---|---|
| Ingestion France Travail | ✅ Fonctionnel (authentification, pagination, filtre de fraîcheur) |
| Ingestion LinkedIn (scraping) | 🟡 Testé, exploratoire, non garanti dans le pipeline final |
| Normalisation multi-sources | 🟡 Conception faite, pas encore branchée sur les vraies données |
| Orchestration (Airflow) | ❌ À faire |
| Data Lake (MinIO) | ❌ À faire |
| Traitement (PySpark) | ❌ À faire |
| Modélisation (dbt / PostgreSQL) | ❌ À faire |
| Détecteur de niches | ❌ À faire (conçu) |
| Industrialisation (Docker) | ❌ À faire |
| Restitution (Metabase) | ❌ À faire |

---

## 🚀 Démarrage rapide (état actuel)

```bash
# 1. Cloner le repo
git clone https://github.com/BRAHAMIManel/pfe-data-jobs-platform.git
cd pfe-data-jobs-platform

# 2. Créer l'environnement virtuel
python -m venv venv
venv\Scripts\activate      # Windows
# source venv/bin/activate # Mac/Linux

# 3. Installer les dépendances
pip install requests python-dotenv beautifulsoup4

# 4. Configurer les identifiants
# Copier .env.example en .env et y renseigner vos identifiants France Travail
# (compte développeur sur https://francetravail.io)

# 5. Lancer la collecte
python collecte_offres_v3_filtree.py
```

---

## ⚠️ Points de vigilance

- Le scraping LinkedIn est réalisé à titre exploratoire uniquement, dans le respect d'un volume raisonnable. Il ne constitue pas une source garantie du pipeline final en raison des conditions d'utilisation de la plateforme et du risque de blocage technique.
- Aucune donnée personnelle identifiable n'est collectée : le projet porte sur les offres d'emploi, pas sur des personnes.
- Les identifiants d'API sont gérés via un fichier `.env`, exclu du dépôt Git (`.gitignore`).

---

## 🎓 Contexte académique

Ce projet est réalisé de façon autonome, sans lien avec l'activité professionnelle de l'auteure. Il s'inscrit dans le cadre du Master 2 Data Engineering, thématique "Conception d'une plateforme Big Data de collecte et d'analyse des offres d'emploi".