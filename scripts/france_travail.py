"""
Client API France Travail — collecte par metier ROME.

Le perimetre est le domaine M18 du referentiel ROME (systemes
d'information et telecommunications), recupere dynamiquement a chaque
execution : la liste n'est jamais codee en dur, elle suit le referentiel
officiel. Quelques metiers hors informatique du domaine sont exclus
explicitement (voir METIERS_HORS_PERIMETRE).
"""

import json
import logging
import os
import re
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


# Le jeton France Travail expire au bout d'environ 25 minutes, alors qu'une
# collecte complete peut durer davantage : on le garde en memoire et on le
# renouvelle avant son expiration, ou des qu'un appel repond HTTP 401.
_JETON = {"valeur": None, "expire_a": 0.0}
MARGE_EXPIRATION = 120  # secondes


def get_access_token(forcer=False):
    """Recupere un jeton OAuth2 (client_credentials), renouvele si besoin."""
    if (
        not forcer
        and _JETON["valeur"]
        and time.time() < _JETON["expire_a"] - MARGE_EXPIRATION
    ):
        return _JETON["valeur"]

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
    contenu = response.json()
    _JETON["valeur"] = contenu["access_token"]
    _JETON["expire_a"] = time.time() + int(contenu.get("expires_in", 1499))
    logger.info("Authentification France Travail reussie.")
    return _JETON["valeur"]


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


# L'API ne renvoie jamais plus de 3 150 offres pour une meme recherche
# (dernier indice de "range" : 3149). Les metiers les plus demandes
# (developpement, support...) en comptent bien plus : sans decoupage, la
# collecte s'arreterait aux 3 150 premieres et ignorerait le reste.
# Quand un metier depasse la limite, on le collecte region par region,
# puis departement par departement si une region depasse encore.
LIMITE_API = 3150
MOTIF_TOTAL = re.compile(r"/(\d+)")

with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "regions.json"),
          encoding="utf-8") as _f:
    _GEO = json.load(_f)
REGIONS = sorted(_GEO["regions"])
DEPARTEMENTS_PAR_REGION = {
    code: sorted(d for d, r in _GEO["departements"].items() if r == code)
    for code in REGIONS
}


def _collecter(code_rome, filtres, plafond, taille_page=150, max_tentatives=3):
    """Pagine une recherche. Renvoie (offres, total annonce par l'API)."""
    offres_trouvees, total, debut = [], None, 0
    interrompu = False

    while len(offres_trouvees) < plafond:
        fin = min(debut + taille_page - 1, plafond - 1)
        if fin < debut:
            break

        taille_demandee = fin - debut + 1
        params = {"codeROME": code_rome, "range": f"{debut}-{fin}", **filtres}

        page = None
        for tentative in range(1, max_tentatives + 1):
            headers = {"Authorization": f"Bearer {get_access_token()}"}
            response = requests.get(
                OFFRES_URL, headers=headers, params=params, timeout=60
            )

            if response.status_code == 204:  # aucun resultat
                return offres_trouvees, total or len(offres_trouvees)

            if response.status_code in (200, 206):
                page = response.json().get("resultats", [])
                trouve = MOTIF_TOTAL.search(response.headers.get("Content-Range", ""))
                if trouve:
                    total = int(trouve.group(1))
                break

            logger.warning(
                "ROME %s %s page %s-%s : HTTP %s (tentative %s/%s) — %s",
                code_rome, filtres or "", debut, fin, response.status_code,
                tentative, max_tentatives, response.text[:300],
            )
            if response.status_code == 401:
                get_access_token(forcer=True)  # jeton expire
                continue
            if response.status_code < 500 and response.status_code != 429:
                break
            time.sleep(2 * tentative)

        if page is None:
            interrompu = True
            break

        offres_trouvees.extend(page)
        if not page or len(page) < taille_demandee:
            break
        debut += taille_page
        time.sleep(0.3)

    if interrompu:
        logger.warning(
            "ROME %s %s : collecte interrompue apres erreurs, %s offres gardees.",
            code_rome, filtres or "", len(offres_trouvees),
        )
    return offres_trouvees, total if total is not None else len(offres_trouvees)


def get_offres_par_rome(token, code_rome, total_souhaite=None, **_):
    """Toutes les offres d'un metier ROME, decoupees si besoin.

    `token` est conserve pour compatibilite : le jeton courant est relu a
    chaque appel, ce qui permet de le renouveler en cours de collecte.
    `total_souhaite` (None = tout) borne le nombre d'offres renvoyees.
    """
    plafond = min(total_souhaite or LIMITE_API, LIMITE_API)
    offres, total = _collecter(code_rome, {}, plafond)

    if total > LIMITE_API and (total_souhaite is None or total_souhaite > LIMITE_API):
        logger.info(
            "ROME %s : %s offres annoncees, au-dela de la limite de l'API. "
            "Collecte region par region.", code_rome, total,
        )
        offres = []
        for region in REGIONS:
            partie, total_region = _collecter(code_rome, {"region": region}, LIMITE_API)
            if total_region > LIMITE_API:
                partie = []
                for departement in DEPARTEMENTS_PAR_REGION[region]:
                    p, _ = _collecter(code_rome, {"departement": departement}, LIMITE_API)
                    partie.extend(p)
            offres.extend(partie)
        offres = dedupliquer(offres)
        logger.info(
            "ROME %s : %s offres collectees sur %s annoncees.",
            code_rome, len(offres), total,
        )

    if total_souhaite:
        offres = offres[:total_souhaite]
    return offres


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