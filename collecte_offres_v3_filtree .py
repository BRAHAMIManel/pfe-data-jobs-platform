"""
Script de collecte — v3
Ajoute deux filtres métier :
1. Offres récentes (moins de N jours depuis dateCreation)
2. Offres peu concurrentielles (champ offresManqueCandidats de l'API,
   ou absence du champ = non garanti, donc traité comme "inconnu")

Avant de lancer :
pip install requests python-dotenv
Fichier .env requis avec FRANCE_TRAVAIL_CLIENT_ID et FRANCE_TRAVAIL_CLIENT_SECRET
"""

import os
import time
import json
from datetime import datetime, timezone, timedelta
import requests
from dotenv import load_dotenv

load_dotenv()
CLIENT_ID = os.getenv("FRANCE_TRAVAIL_CLIENT_ID")
CLIENT_SECRET = os.getenv("FRANCE_TRAVAIL_CLIENT_SECRET")

if not CLIENT_ID or not CLIENT_SECRET:
    raise ValueError("❌ Identifiants manquants dans le fichier .env")

TOKEN_URL = "https://entreprise.francetravail.fr/connexion/oauth2/access_token?realm=%2Fpartenaire"
OFFRES_URL = "https://api.francetravail.io/partenaire/offresdemploi/v2/offres/search"

# --- Paramètres de filtrage (ajustables) ---
JOURS_MAX_ANCIENNETE = 30      # offres publiées il y a moins de X jours
# Le filtre strict sur offresManqueCandidats a été retiré : ce champ est
# conservé comme information sur chaque offre, pour alimenter plus tard
# le score du détecteur de niches, plutôt que d'exclure des données ici.


def get_access_token():
    payload = {
        "grant_type": "client_credentials",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "scope": "api_offresdemploiv2 o2dsoffre",
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    response = requests.post(TOKEN_URL, data=payload, headers=headers)
    response.raise_for_status()
    print("✅ Authentification réussie.")
    return response.json()["access_token"]


def get_offres_paginated(token, mots_cles="data engineer", total_souhaite=300, taille_page=150):
    headers = {"Authorization": f"Bearer {token}"}
    toutes_les_offres = []
    debut = 0

    while len(toutes_les_offres) < total_souhaite:
        fin = debut + taille_page - 1
        params = {"motsCles": mots_cles, "range": f"{debut}-{fin}"}
        response = requests.get(OFFRES_URL, headers=headers, params=params)

        if response.status_code not in (200, 206):
            print(f"⚠️ Erreur {response.status_code} à la page {debut}-{fin}")
            print(f"   Détail de la réponse : {response.text[:500]}")
            break

        offres = response.json().get("resultats", [])
        if not offres:
            break

        toutes_les_offres.extend(offres)
        print(f"  → {len(offres)} offres récupérées (cumulé : {len(toutes_les_offres)})")
        debut += taille_page
        time.sleep(0.3)

    return toutes_les_offres[:total_souhaite]


def filtrer_offres(offres, jours_max=JOURS_MAX_ANCIENNETE):
    """Applique le filtre de fraîcheur uniquement.
    Le champ offresManqueCandidats est conservé sur chaque offre comme
    information (utile plus tard pour le score de niche), mais n'exclut
    plus aucune offre ici."""
    maintenant = datetime.now(timezone.utc)
    seuil_date = maintenant - timedelta(days=jours_max)

    gardees = []
    rejet_ancien = 0
    nb_peu_concurrentielles = 0

    for offre in offres:
        date_str = offre.get("dateCreation")
        if not date_str:
            continue
        date_offre = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        if date_offre < seuil_date:
            rejet_ancien += 1
            continue

        if offre.get("offresManqueCandidats") is True:
            nb_peu_concurrentielles += 1

        gardees.append(offre)

    stats = {
        "total_initial": len(offres),
        "rejetees_trop_anciennes": rejet_ancien,
        "dont_peu_concurrentielles": nb_peu_concurrentielles,
        "total_gardees": len(gardees),
    }
    return gardees, stats


if __name__ == "__main__":
    token = get_access_token()

    print("\n📡 Récupération des offres...")
    offres_brutes = get_offres_paginated(token, mots_cles="data engineer", total_souhaite=300)

    print(f"\n🔎 Application du filtre de fraîcheur (< {JOURS_MAX_ANCIENNETE} jours)...")
    offres_filtrees, stats = filtrer_offres(offres_brutes)

    print(f"\n📊 Statistiques de filtrage :")
    print(f"  - Total initial               : {stats['total_initial']}")
    print(f"  - Rejetées (trop vieilles)     : {stats['rejetees_trop_anciennes']}")
    print(f"  - Conservées                   : {stats['total_gardees']}")
    print(f"    dont marquées 'peu concurrentielles' : {stats['dont_peu_concurrentielles']}")

    for offre in offres_filtrees[:5]:
        print(f"- {offre.get('intitule')} | {offre.get('entreprise', {}).get('nom', 'N/A')} | {offre.get('lieuTravail', {}).get('libelle', 'N/A')}")

    with open("offres_filtrees.json", "w", encoding="utf-8") as f:
        json.dump(offres_filtrees, f, ensure_ascii=False, indent=2)
    print("\n💾 Offres filtrées sauvegardées dans offres_filtrees.json")
