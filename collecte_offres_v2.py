"""
Script de collecte — Sprint 1
Objectif : récupérer un volume plus large d'offres Data/IA depuis l'API France Travail,
avec authentification sécurisée via fichier .env et gestion de la pagination.

Avant de lancer :
1. pip install requests python-dotenv
2. Copier .env.example en .env et y coller vos vrais identifiants
   (le fichier .env ne doit JAMAIS être poussé sur Git — il est dans .gitignore)
"""

import os
import time
import json
import requests
from dotenv import load_dotenv

# --- 0. Charger les identifiants depuis .env ---
load_dotenv()
CLIENT_ID = os.getenv("FRANCE_TRAVAIL_CLIENT_ID")
CLIENT_SECRET = os.getenv("FRANCE_TRAVAIL_CLIENT_SECRET")

if not CLIENT_ID or not CLIENT_SECRET:
    raise ValueError(
        "❌ Identifiants manquants. Vérifiez que le fichier .env existe "
        "et contient FRANCE_TRAVAIL_CLIENT_ID et FRANCE_TRAVAIL_CLIENT_SECRET."
    )

TOKEN_URL = "https://entreprise.francetravail.fr/connexion/oauth2/access_token?realm=%2Fpartenaire"
OFFRES_URL = "https://api.francetravail.io/partenaire/offresdemploi/v2/offres/search"


# --- 1. Authentification OAuth2 ---
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


# --- 2. Récupération avec pagination ---
# L'API France Travail limite chaque appel à 150 offres max (range).
# Pour en récupérer plus, il faut enchaîner plusieurs appels en décalant le "range".

def get_offres_paginated(token, mots_cles="data engineer", total_souhaite=300, taille_page=150):
    headers = {"Authorization": f"Bearer {token}"}
    toutes_les_offres = []
    debut = 0

    while len(toutes_les_offres) < total_souhaite:
        fin = debut + taille_page - 1
        params = {
            "motsCles": mots_cles,
            "range": f"{debut}-{fin}",
        }

        response = requests.get(OFFRES_URL, headers=headers, params=params)

        # 206 = "Partial Content", c'est normal avec la pagination de cette API
        if response.status_code not in (200, 206):
            print(f"⚠️ Erreur {response.status_code} à la page {debut}-{fin} : {response.text}")
            break

        data = response.json()
        offres = data.get("resultats", [])

        if not offres:
            print("ℹ️ Plus d'offres disponibles, arrêt de la pagination.")
            break

        toutes_les_offres.extend(offres)
        print(f"  → {len(offres)} offres récupérées (total cumulé : {len(toutes_les_offres)})")

        debut += taille_page
        time.sleep(0.3)  # petite pause pour rester raisonnable vis-à-vis de l'API

    return toutes_les_offres[:total_souhaite]


# --- 3. Exécution ---
if __name__ == "__main__":
    token = get_access_token()

    print("\n📡 Récupération des offres...")
    offres = get_offres_paginated(token, mots_cles="data engineer", total_souhaite=300)

    print(f"\n📦 {len(offres)} offres récupérées au total.\n")
    for offre in offres[:5]:
        print(f"- {offre.get('intitule')} | {offre.get('entreprise', {}).get('nom', 'N/A')} | {offre.get('lieuTravail', {}).get('libelle', 'N/A')}")
    if len(offres) > 5:
        print(f"  ... et {len(offres) - 5} autres.")

    with open("offres_collectees.json", "w", encoding="utf-8") as f:
        json.dump(offres, f, ensure_ascii=False, indent=2)
    print("\n💾 Résultat complet sauvegardé dans offres_collectees.json")
