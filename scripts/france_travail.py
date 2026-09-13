"""
Client API France Travail — collecte par metier ROME.

Le perimetre est le domaine M18 du referentiel ROME (systemes
d'information et telecommunications), recupere dynamiquement a chaque
execution : la liste n'est jamais codee en dur, elle suit le referentiel
officiel. Quelques metiers hors informatique du domaine sont exclus
explicitement (voir METIERS_HORS_PERIMETRE).
"""

import logging
import os
import time
from datetime import datetime, timedelta, timezone

import requests

logger = logging.getLogger(__name__)

TOKEN_URL = (
    "https://entreprise.francetravail.fr/connexion/oauth2/access_token"
    "?realm=%2Fpartenaire"
)
OFFRES_URL = "https://api.francetravail.io/partenaire/offresdemploi/v2/offres/search"
REFERENTIEL_ROME_URL = (
    "https://api.francetravail.io/partenaire/offresdemploi/v2/referentiel/metiers"
)

JOURS_MAX_ANCIENNETE = 30
PREFIXE_DOMAINE = "M18"

# Metiers du domaine M18 sans rapport avec les systemes d'information.
# Les inclure fausserait les agregats metier x ville du detecteur de niches.
METIERS_HORS_PERIMETRE = {
    "M1808",  # Cartographe
    "M1809",  # Meteorologue
    "M1888",  # Specialiste en modelisation climatique
    "M1890",  # Responsable d'operations en station meteorologique
    "M1891",  # Ingenieur previsionniste meteorologue
    "M1893",  # Technicien de la meteorologie
    "M1895",  # Geomaticien
}


def get_access_token():
    """Recupere un jeton OAuth2 (client_credentials)."""
    client_id = os.getenv("FRANCE_TRAVAIL_CLIENT_ID")
    client_secret = os.getenv("FRANCE_TRAVAIL_CLIENT_SECRET")

    if not client_id or not client_secret:
        raise ValueError(
            "FRANCE_TRAVAIL_CLIENT_ID / FRANCE_TRAVAIL_CLIENT_SECRET absents "
            "de l'environnement du conteneur."
        )

    payload = {
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
        "scope": "api_offresdemploiv2 o2dsoffre",
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}

    response = requests.post(TOKEN_URL, data=payload, headers=headers, timeout=30)
    response.raise_for_status()
    logger.info("Authentification France Travail reussie.")
    return response.json()["access_token"]


def lister_metiers_du_domaine(token, prefixe=PREFIXE_DOMAINE):
    """Renvoie les metiers ROME du domaine, hors perimetre exclu.

    Format : [{"code": "M1811", "libelle": "Data engineer"}, ...]
    """
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.get(REFERENTIEL_ROME_URL, headers=headers, timeout=60)
    response.raise_for_status()

    metiers = []
    exclus = 0
    for metier in response.json():
        code = str(metier.get("code", ""))
        if not code.startswith(prefixe):
            continue
        if code in METIERS_HORS_PERIMETRE:
            exclus += 1
            continue
        metiers.append({"code": code, "libelle": metier.get("libelle")})

    metiers.sort(key=lambda m: m["code"])
    logger.info(
        "Domaine %s : %s metiers retenus, %s exclus du perimetre.",
        prefixe, len(metiers), exclus,
    )
    return metiers


def get_offres_par_rome(
    token,
    code_rome,
    total_souhaite=500,
    taille_page=150,
    max_tentatives=3,
):
    """Pagine sur un code ROME et renvoie la liste brute des offres."""
    headers = {"Authorization": f"Bearer {token}"}
    toutes_les_offres = []
    debut = 0

    while len(toutes_les_offres) < total_souhaite:
        fin = min(debut + taille_page - 1, total_souhaite - 1)

        # Garde-fou : sans cela, un metier qui renvoie moins d'offres que
        # demande produit un intervalle inverse (ex. 600-499) et un HTTP 400.
        if fin < debut:
            break

        taille_demandee = fin - debut + 1
        params = {"codeROME": code_rome, "range": f"{debut}-{fin}"}

        offres = None
        for tentative in range(1, max_tentatives + 1):
            response = requests.get(
                OFFRES_URL, headers=headers, params=params, timeout=60
            )

            if response.status_code == 204:  # aucun resultat
                return toutes_les_offres

            if response.status_code in (200, 206):
                offres = response.json().get("resultats", [])
                break

            logger.warning(
                "ROME %s page %s-%s : HTTP %s (tentative %s/%s) — %s",
                code_rome, debut, fin, response.status_code,
                tentative, max_tentatives, response.text[:300],
            )
            if response.status_code < 500:
                break
            time.sleep(2 * tentative)

        if not offres:
            break

        toutes_les_offres.extend(offres)

        # Page incomplete = fin du gisement, inutile d'en demander une autre.
        if len(offres) < taille_demandee:
            return toutes_les_offres

        debut += taille_page
        time.sleep(0.3)

    # On sort par le plafond : le metier a probablement plus d'offres.
    logger.warning(
        "ROME %s : plafond de %s atteint, resultat probablement tronque.",
        code_rome, total_souhaite,
    )
    return toutes_les_offres[:total_souhaite]


def dedupliquer(offres):
    """Supprime les doublons par identifiant d'offre.

    Une meme offre remonte souvent sous plusieurs metiers proches : sans
    cette etape elle serait comptee plusieurs fois dans les agregats.
    """
    vues = {}
    for offre in offres:
        identifiant = offre.get("id")
        if identifiant and identifiant not in vues:
            vues[identifiant] = offre
    return list(vues.values())


def filtrer_offres(offres, jours_max=JOURS_MAX_ANCIENNETE):
    """Filtre de fraicheur. Utilise en couche silver, jamais avant raw."""
    seuil_date = datetime.now(timezone.utc) - timedelta(days=jours_max)

    gardees = []
    rejet_ancien = 0
    rejet_sans_date = 0
    nb_peu_concurrentielles = 0

    for offre in offres:
        date_str = offre.get("dateCreation")
        if not date_str:
            rejet_sans_date += 1
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
        "rejetees_sans_date": rejet_sans_date,
        "dont_peu_concurrentielles": nb_peu_concurrentielles,
        "total_gardees": len(gardees),
    }
    return gardees, stats