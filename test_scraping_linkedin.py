"""
Script exploratoire — test de scraping LinkedIn (pages publiques uniquement)

⚠️ AVERTISSEMENT IMPORTANT :
- Ce script scrape uniquement les pages de résultats de recherche PUBLIQUES
  (sans connexion à un compte LinkedIn).
- LinkedIn interdit explicitement le scraping dans ses conditions d'utilisation.
- Ce script est fragile : LinkedIn peut bloquer l'accès (429, redirection vers
  une page de connexion, CAPTCHA) même sans être connecté, surtout après
  plusieurs requêtes rapprochées.
- À utiliser à faible volume, uniquement à titre exploratoire pour votre PFE,
  jamais en production ni en usage intensif.

Avant de lancer :
pip install requests beautifulsoup4
"""

import requests
from bs4 import BeautifulSoup
import time
import json

# En-tête simulant un navigateur classique (nécessaire, sinon LinkedIn bloque
# immédiatement les requêtes qui n'ont pas de User-Agent de navigateur)
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}

BASE_URL = "https://www.linkedin.com/jobs/search"


def scraper_page_recherche(mots_cles="data engineer", localisation="France", page=0):
    params = {
        "keywords": mots_cles,
        "location": localisation,
        "start": page * 25,  # LinkedIn pagine par blocs de 25 sur cette page publique
    }

    response = requests.get(BASE_URL, headers=HEADERS, params=params)

    print(f"Statut HTTP : {response.status_code}")

    if response.status_code != 200:
        print("⚠️ Requête non aboutie — LinkedIn a probablement bloqué ou redirigé la requête.")
        return []

    soup = BeautifulSoup(response.text, "html.parser")

    offres = []
    # Ces sélecteurs CSS sont ceux observés sur les pages publiques de recherche.
    # Ils peuvent changer sans préavis si LinkedIn modifie sa structure HTML.
    cartes = soup.find_all("div", class_="base-card")

    for carte in cartes:
        titre_el = carte.find("h3", class_="base-search-card__title")
        entreprise_el = carte.find("h4", class_="base-search-card__subtitle")
        lieu_el = carte.find("span", class_="job-search-card__location")
        lien_el = carte.find("a", class_="base-card__full-link")
        date_el = carte.find("time", class_="job-search-card__listdate") or carte.find("time")

        offres.append({
            "titre": titre_el.get_text(strip=True) if titre_el else None,
            "entreprise": entreprise_el.get_text(strip=True) if entreprise_el else None,
            "lieu": lieu_el.get_text(strip=True) if lieu_el else None,
            "date_publication": date_el.get("datetime") if date_el else None,
            "date_texte": date_el.get_text(strip=True) if date_el else None,
            "lien": lien_el["href"] if lien_el else None,
        })

    return offres


def scraper_details_offre(lien_offre):
    """Va chercher les détails complets sur la page individuelle d'une offre.
    ⚠️ Une requête HTTP par offre — à utiliser sur un petit volume seulement,
    pour limiter le risque de blocage par LinkedIn."""
    response = requests.get(lien_offre, headers=HEADERS)

    if response.status_code != 200:
        return {"erreur": f"Statut {response.status_code}"}

    soup = BeautifulSoup(response.text, "html.parser")

    description_el = soup.find("div", class_="show-more-less-html__markup")

    # Les "criteria" (type de contrat, niveau d'expérience, secteur, fonction)
    # sont listés dans des <li> avec cette classe sur la page publique.
    criteres = {}
    for li in soup.find_all("li", class_="description__job-criteria-item"):
        cle_el = li.find("h3", class_="description__job-criteria-subheader")
        val_el = li.find("span", class_="description__job-criteria-text")
        if cle_el and val_el:
            criteres[cle_el.get_text(strip=True)] = val_el.get_text(strip=True)

    return {
        "description_complete": description_el.get_text(strip=True) if description_el else None,
        "criteres": criteres,
    }


def enrichir_offres(offres, limite=5, pause_entre_requetes=2):
    """Enrichit un nombre LIMITÉ d'offres avec leurs détails complets.
    limite=5 par défaut : volontairement petit pour rester prudent."""
    offres_enrichies = []

    for i, offre in enumerate(offres[:limite]):
        print(f"  → Détail {i + 1}/{min(limite, len(offres))} : {offre['titre']}")
        if offre.get("lien"):
            details = scraper_details_offre(offre["lien"])
            offre.update(details)
        offres_enrichies.append(offre)
        time.sleep(pause_entre_requetes)  # pause plus longue, on est sur des pages individuelles

    return offres_enrichies


if __name__ == "__main__":
    print("🔎 Test de scraping LinkedIn (page publique de recherche)...\n")

    offres = scraper_page_recherche(mots_cles="data engineer", localisation="France", page=0)

    print(f"\n📦 {len(offres)} offres trouvées sur cette page.\n")
    for o in offres[:10]:
        print(f"- {o['titre']} | {o['entreprise']} | {o['lieu']}")

    if offres:
        print(f"\n🔬 Enrichissement des 5 premières offres avec leurs détails complets...")
        offres_test = enrichir_offres(offres, limite=5)

        with open("offres_linkedin_test.json", "w", encoding="utf-8") as f:
            json.dump(offres_test, f, ensure_ascii=False, indent=2)
        print("\n💾 Résultat enrichi sauvegardé dans offres_linkedin_test.json")
    else:
        print("\n❌ Aucune offre récupérée — LinkedIn a probablement bloqué la requête.")
        print("   C'est un résultat attendu et fréquent ; voir les notes de risque du projet.")