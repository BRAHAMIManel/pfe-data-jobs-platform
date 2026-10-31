"""
Transformation des offres silver vers les structures du schema en etoile.

Le dictionnaire de competences est charge depuis un fichier JSON externe :
changer de domaine metier = changer de fichier, pas de code.
"""

import json
import logging
import os
import re
import unicodedata
from datetime import datetime
from functools import lru_cache

logger = logging.getLogger(__name__)

DOSSIER_SCRIPTS = os.path.dirname(os.path.abspath(__file__))

CHEMIN_DICTIONNAIRE = os.getenv(
    "CHEMIN_COMPETENCES", os.path.join(DOSSIER_SCRIPTS, "competences_it.json")
)
CHEMIN_POSTES = os.getenv(
    "CHEMIN_POSTES", os.path.join(DOSSIER_SCRIPTS, "postes.json")
)
CHEMIN_HORS_PERIMETRE = os.getenv(
    "CHEMIN_HORS_PERIMETRE", os.path.join(DOSSIER_SCRIPTS, "hors_perimetre.json")
)

URL_OFFRE_FRANCE_TRAVAIL = (
    "https://candidat.francetravail.fr/offres/recherche/detail/{}"
)


def _normaliser(texte):
    """Minuscules sans accents, pour une recherche insensible a la casse."""
    texte = unicodedata.normalize("NFD", texte)
    texte = "".join(c for c in texte if unicodedata.category(c) != "Mn")
    return texte.lower()


def _motif_mot(texte):
    """Motif qui trouve `texte` comme mot entier.

    On n'utilise pas \\b : il echoue apres un caractere non alphanumerique,
    si bien que "C#", "C++" ou ".NET" n'etaient jamais reconnus. Les
    lookarounds disent simplement : pas de lettre ou chiffre juste avant
    ni juste apres. "R" ne matche donc ni "Ruby" ni "Go" "Google".
    """
    return r"(?<![\w])" + re.escape(_normaliser(texte)) + r"(?![\w])"


@lru_cache(maxsize=1)
def charger_dictionnaire(chemin=CHEMIN_DICTIONNAIRE):
    """Renvoie [(libelle_affiche, categorie, motif_regex_compile), ...].

    Chaque competence peut avoir des variantes d'ecriture ("PowerBI",
    "Postgres") : elles sont reconnues mais rangees sous le libelle principal.
    """
    with open(chemin, encoding="utf-8") as fichier:
        contenu = json.load(fichier)

    variantes = contenu.get("variantes", {})
    entrees = []
    for categorie, libelles in contenu["competences"].items():
        for libelle in libelles:
            ecritures = [libelle] + variantes.get(libelle, [])
            motif = re.compile("|".join(_motif_mot(e) for e in ecritures))
            entrees.append((libelle, categorie, motif))

    logger.info("Dictionnaire charge : %s competences.", len(entrees))
    return tuple(entrees)


def extraire_competences(description):
    """Renvoie la liste des competences trouvees dans une description."""
    if not description:
        return []

    texte = _normaliser(description)
    return [
        (libelle, categorie)
        for libelle, categorie, motif in charger_dictionnaire()
        if motif.search(texte)
    ]


# "Paris 9e Arrondissement", "PARIS 15", "Lyon 3eme" : le numero final est
# retire. Aucune commune francaise ne finit par un nombre, c'est sans risque.
MOTIF_ARRONDISSEMENT = re.compile(
    r"\s+\d+\s*(?:er|e|eme|ème)?(?:\s*arrondissement)?\s*$", re.IGNORECASE
)


def normaliser_ville(ville):
    """Ramene les variantes d'une meme ville a une seule forme.

    'Paris 9e Arrondissement', 'PARIS 15' et 'Paris' donnent tous 'PARIS'.
    Sans cela, Paris se retrouve eclate en une vingtaine de lignes dans
    les agregats et parait moins dense qu'il ne l'est.
    """
    if not ville:
        return None

    sans_arrondissement = MOTIF_ARRONDISSEMENT.sub("", ville.strip())
    normalisee = _normaliser(sans_arrondissement).upper()
    return normalisee or None


def parser_lieu(lieu):
    """Eclate lieuTravail. Le libelle a la forme '55 - Revigny-sur-Ornain'."""
    if not lieu:
        return None

    code_insee = lieu.get("commune")
    if not code_insee:
        return None

    libelle = lieu.get("libelle") or ""
    departement, ville = None, None
    if " - " in libelle:
        departement, ville = libelle.split(" - ", 1)
        departement = departement.strip()
        ville = ville.strip()
    else:
        ville = libelle.strip() or None

    return {
        "code_insee": code_insee,
        "ville": ville,
        "ville_normalisee": normaliser_ville(ville),
        "code_postal": lieu.get("codePostal"),
        "departement": departement,
        "latitude": lieu.get("latitude"),
        "longitude": lieu.get("longitude"),
    }


MOTIF_SALAIRE = re.compile(
    r"(mensuel|annuel|horaire)\s+de\s+([\d\s.,]+)"
    r"(?:\s*(?:euros?)?\s*(?:a|à)\s+([\d\s.,]+))?",
    re.IGNORECASE,
)


def parser_salaire(salaire):
    """Extrait min, max et periode du libelle libre de l'API.

    Exemple : 'Mensuel de 2500.0 Euros a 3200.0 Euros'.
    Renvoie (None, None, None) si le libelle n'est pas exploitable —
    beaucoup d'offres n'affichent aucun salaire.
    """
    if not salaire:
        return None, None, None

    libelle = salaire.get("libelle") if isinstance(salaire, dict) else salaire
    if not libelle:
        return None, None, None

    correspondance = MOTIF_SALAIRE.search(_normaliser(libelle))
    if not correspondance:
        return None, None, None

    def _nombre(texte):
        if not texte:
            return None
        try:
            return float(texte.replace(" ", "").replace(",", "."))
        except ValueError:
            return None

    minimum = _nombre(correspondance.group(2))
    maximum = _nombre(correspondance.group(3)) or minimum
    return minimum, maximum, correspondance.group(1).lower()


def parser_date(valeur):
    """ISO 8601 vers date. Renvoie None si absente ou invalide."""
    if not valeur:
        return None
    try:
        return datetime.fromisoformat(valeur.replace("Z", "+00:00")).date()
    except ValueError:
        return None

MOTIF_EXPERIENCE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(an|mois)")


def parser_experience(offre):
    """Annees d'experience demandees par une offre France Travail.

    'D' (debutant accepte) -> 0. Sinon le libelle libre, par exemple
    '3 An(s)' ou '6 Mois', est converti en annees. None si illisible :
    l'offre n'est alors jamais ecartee pour une question de niveau.
    """
    if offre.get("experienceExige") == "D":
        return 0.0

    libelle = _normaliser(offre.get("experienceLibelle") or "")
    if "debutant" in libelle:
        return 0.0

    correspondance = MOTIF_EXPERIENCE.search(libelle)
    if not correspondance:
        return None

    valeur = float(correspondance.group(1).replace(",", "."))
    if correspondance.group(2) == "mois":
        valeur = valeur / 12
    return round(valeur, 1)


@lru_cache(maxsize=1)
def charger_postes(chemin=CHEMIN_POSTES):
    """Renvoie les postes (dans l'ordre de classement) avec leurs motifs."""
    with open(chemin, encoding="utf-8") as fichier:
        familles = json.load(fichier)["familles"]

    return tuple(
        {
            "id": f["id"],
            "libelle": f["libelle"],
            "categorie": f["categorie"],
            "motifs": [re.compile(m) for m in f["motifs_intitule"]],
            "secours": [re.compile(m) for m in f.get("motifs_secours", [])],
            "competences_typiques": tuple(f["competences_typiques"]),
        }
        for f in familles
    )


@lru_cache(maxsize=1)
def charger_categories(chemin=CHEMIN_POSTES):
    """Categories, dans l'ordre d'affichage : [(id, libelle, (postes...)), ...]."""
    with open(chemin, encoding="utf-8") as fichier:
        return tuple(
            (c["id"], c["libelle"], tuple(c["postes"]))
            for c in json.load(fichier)["categories"]
        )


def classer_poste(intitule):
    """Famille de poste d'une offre d'apres son intitule, ou None.

    Le premier poste dont un motif apparait l'emporte (voir postes.json).
    Une offre sans aucun motif reconnu reste sans poste : elle compte dans
    les statistiques du marche mais n'est pas proposee aux candidats.
    """
    if not intitule or est_hors_perimetre(intitule):
        return None

    texte = _normaliser(intitule)
    for cle in ("motifs", "secours"):  # motifs principaux, puis de secours
        for famille in charger_postes():
            if any(motif.search(texte) for motif in famille[cle]):
                return famille["id"]
    return None


@lru_cache(maxsize=1)
def _regles_hors_perimetre(chemin=CHEMIN_HORS_PERIMETRE):
    with open(chemin, encoding="utf-8") as fichier:
        regles = json.load(fichier)
    return (
        re.compile("|".join(regles["motifs"])),
        re.compile("|".join(regles["sauf"])),
    )


def est_hors_perimetre(intitule):
    """Vrai pour une offre mal codee, sans rapport avec l'informatique.

    Exemple : 'Serveur (H/F)' en restauration, range par l'employeur dans
    'Administrateur de serveurs'. 'Administrateur serveurs Linux' reste.
    """
    if not intitule:
        return False
    texte = _normaliser(intitule)
    motifs, sauf = _regles_hors_perimetre()
    return bool(motifs.search(texte)) and not sauf.search(texte)


def url_offre(offre):
    """Lien vers l'annonce d'origine.

    France Travail : la page publique de l'offre, construite depuis son
    identifiant. Si l'offre vient d'un partenaire, son lien d'origine.
    """
    origine = (offre.get("origineOffre") or {}).get("urlOrigine")
    if origine:
        return origine
    identifiant = offre.get("id")
    return URL_OFFRE_FRANCE_TRAVAIL.format(identifiant) if identifiant else None