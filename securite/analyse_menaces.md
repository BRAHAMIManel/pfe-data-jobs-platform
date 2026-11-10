# Analyse de menaces — Détecteur de niches IT

Version du 10/11/2026. Méthode : on liste ce qu'on protège (les actifs), qui pourrait s'y attaquer et comment (les menaces), puis les protections en place et le risque qui reste. Chaque protection marquée « vérifié » est contrôlée automatiquement par `scripts/verifier_securite.py` (16 contrôles, tous réussis le 10/11/2026).

## 1. Contexte et périmètre

- Plateforme **locale** : Docker Compose sur un PC personnel (Windows), utilisée par une seule personne pour la démonstration.
- Pas d'exposition sur Internet. Le risque principal est **le réseau local partagé** (Wi-Fi d'une bibliothèque, d'une école).
- Hors périmètre : la sécurité du PC lui-même (mot de passe de session, antivirus, chiffrement du disque) et celle de l'API France Travail.

## 2. Ce qu'on protège

| Actif | Où | Sensibilité |
| --- | --- | --- |
| Identifiants de l'API France Travail | `.env` | Élevée : usurpation de l'application auprès de France Travail |
| Mots de passe des bases et de MinIO | `.env` | Élevée : accès à toutes les données |
| CV déposé par le candidat | Mémoire de l'application | **Donnée personnelle (RGPD)** |
| Offres collectées (raw, silver) | MinIO | Moyenne : données publiques, mais leur perte casse l'historique |
| Entrepôt (étoile, agrégats) | PostgreSQL DWH | Moyenne : recalculable depuis raw |
| Métadonnées d'Airflow | PostgreSQL Airflow | Faible |

## 3. Menaces et protections

| # | Menace | Exemple concret | Protection en place | Risque restant |
| --- | --- | --- | --- | --- |
| M1 | Accès depuis le réseau local | Sur le Wi-Fi de la bibliothèque, quelqu'un se connecte à la base (port 5433) ou à MinIO (9000) | Tous les ports liés à **127.0.0.1** : invisibles depuis le réseau | Faible |
| M2 | Fuite des secrets | Le `.env` est poussé sur GitHub (dépôt **public**) | `.env` exclu par `.gitignore` ; aucun secret dans le code ; historique Git vérifié (aucun secret) ; modèle `.env.example` sans valeurs | Faible |
| M3 | Application compromise qui modifie ou détruit les données | Une faille dans Streamlit permet d'exécuter du SQL | Compte **`app_lecture`** : lecture seule. **Vérifié** : modifier, supprimer, insérer, créer ou supprimer une table sont refusés | Faible : l'attaquant pourrait lire, pas écrire |
| M4 | Pipeline compromis qui efface le Data Lake | Un bug ou un code malveillant supprime raw (l'historique) | Compte MinIO **`pipeline`** : raw et silver uniquement, **sans droit de suppression**. **Vérifié** : supprimer, écrire dans gold, créer un bucket sont refusés | Faible |
| M5 | Prise de contrôle du conteneur de l'application | Une faille donne un shell dans le conteneur | L'application tourne avec un **utilisateur sans privilèges** (`appli`), et le code est monté **en lecture seule** | Faible |
| M6 | Injection SQL | Une entrée de l'utilisateur est concaténée dans une requête | Requêtes de l'application **fixes** ; le pipeline utilise des **requêtes paramétrées** et `psycopg2.sql` pour les noms | Très faible |
| M7 | Injection de code dans la page (XSS) | Une offre contient du HTML ou du JavaScript piégé | Tout texte venant des offres est **échappé** (`html.escape`) avant affichage | Faible |
| M8 | Fichier CV malveillant ou trop gros | PDF piégé, fichier de 2 Go | Taille limitée à **5 Mo** ; seuls les **PDF et Word** sont acceptés ; lecture par des bibliothèques maintenues (pdfplumber, python-docx) | Moyen : dépend des failles éventuelles de ces bibliothèques (voir M10) |
| M9 | Fuite du CV (RGPD) | Le CV est stocké, ou envoyé à un service tiers | CV lu **en mémoire**, **jamais écrit** sur disque ni dans l'entrepôt ; **aucun envoi** à une IA ou à un tiers | Faible |
| M10 | Faille connue dans une dépendance | Une version de bibliothèque ou d'image contient une CVE | Versions **figées** (`requirements.txt`, images par empreinte) ; **scan** pip-audit et Trivy | Moyen : à refaire régulièrement |
| M11 | Secrets d'Airflow lisibles en clair | Une connexion enregistrée dans Airflow est lue dans sa base | **Clé Fernet** : chiffrement des connexions et variables ; clé de session pour l'interface web | Faible |
| M12 | Données fausses qui faussent les scores (intégrité) | Une offre mal chargée, des dates incohérentes | **Tests dbt** : un test grave en échec bloque le calcul des scores | Faible |

## 4. Risques acceptés (et pourquoi)

- **Pas de HTTPS** : tout reste sur le PC (127.0.0.1), rien ne transite sur le réseau.
- **Mot de passe par défaut de la base d'Airflow** (`airflow`) : cette base n'a aucun port ouvert, elle n'est joignable que par les conteneurs. À changer en production.
- **Un seul compte administrateur Airflow** : une seule utilisatrice.
- **Pas de journal d'accès centralisé** : les journaux d'Airflow et de Docker suffisent pour une démonstration locale.

## 5. En production, il faudrait en plus

1. Un **coffre de secrets** (Vault, AWS Secrets Manager) au lieu du `.env`.
2. **HTTPS** et une **authentification** devant l'application.
3. Des **sauvegardes chiffrées** de MinIO et de l'entrepôt.
4. Le **scan des dépendances dans la CI** à chaque push, et une veille sur les CVE.
5. Une **durée de conservation** des données et un **registre de traitement RGPD**.