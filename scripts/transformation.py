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

CHEMIN_DICTIONNAIRE = os.getenv(
    "CHEMIN_COMPETENCES", "/opt/airflow/scripts/competences_it.json"
)


def _normaliser(texte):
    """Minuscules sans accents, pour une recherche insensible a la casse."""
    texte = unicodedata.normalize("NFD", texte)
    texte = "".join(c for c in texte if unicodedata.category(c) != "Mn")
    return texte.lower()


@lru_cache(maxsize=1)
def charger_dictionnaire(chemin=CHEMIN_DICTIONNAIRE):
    """Renvoie [(libelle_affiche, categorie, motif_regex_compile), ...]."""
    with open(chemin, encoding="utf-8") as fichier:
        contenu = json.load(fichier)

    entrees = []
    for categorie, libelles in contenu["competences"].items():
        for libelle in libelles:
            # \b evite que "R" matche "Ruby" ou que "Go" matche "Google".
            motif = re.compile(
                r"\b" + re.escape(_normaliser(libelle)) + r"\b"
            )
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


MOTIF_ARRONDISSEMENT = re.compile(
    r"\s+\d+\s*(?:er|e|eme|ème)?\s*arrondissement\s*$", re.IGNORECASE
)


def normaliser_ville(ville):
    """Ramene les variantes d'une meme ville a une seule forme.

    'Paris 9e Arrondissement', 'PARIS' et 'Paris' donnent tous 'PARIS'.
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