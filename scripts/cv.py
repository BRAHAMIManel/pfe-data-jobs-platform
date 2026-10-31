"""
Lecture d'un CV : texte, competences, postes proposes, annees d'experience.

Tout se fait en local, sans service exterieur : le CV ne quitte pas la
machine et n'est jamais enregistre. Les competences sont reconnues avec
le MEME dictionnaire que les offres (transformation.extraire_competences),
pour que la comparaison CV / offres soit juste.
"""

import io
import re
from datetime import date

from transformation import (
    _normaliser,
    charger_postes,
    extraire_competences,
)


class CVIlisible(Exception):
    """Le fichier ne contient pas de texte exploitable (CV scanne, image)."""


# ------------------------------------------------------------------ texte

def extraire_texte(contenu, nom_fichier):
    """Texte brut d'un CV PDF ou Word. `contenu` : les octets du fichier."""
    extension = nom_fichier.lower().rsplit(".", 1)[-1]

    if extension == "pdf":
        import pdfplumber

        with pdfplumber.open(io.BytesIO(contenu)) as pdf:
            texte = "\n".join(page.extract_text() or "" for page in pdf.pages)

    elif extension == "docx":
        import docx

        document = docx.Document(io.BytesIO(contenu))
        lignes = [p.text for p in document.paragraphs]
        # Beaucoup de CV Word sont mis en page dans des tableaux.
        for tableau in document.tables:
            for ligne in tableau.rows:
                for cellule in ligne.cells:
                    lignes.append(cellule.text)
        texte = "\n".join(lignes)

    else:
        raise ValueError("Format non pris en charge : PDF ou Word (.docx).")

    if len(texte.strip()) < 80:
        raise CVIlisible(
            "Ce fichier ne contient presque pas de texte. C'est sans doute un "
            "CV scanne : exporte-le en PDF depuis Word ou Canva."
        )
    return texte


# ----------------------------------------------------------- experience

MOIS = {
    "janv": 1, "jan": 1, "fev": 2, "fevr": 2, "mars": 3, "mar": 3, "avr": 4,
    "avril": 4, "mai": 5, "juin": 6, "juil": 7, "aout": 8, "sept": 9,
    "sep": 9, "oct": 10, "nov": 11, "dec": 12, "janvier": 1, "fevrier": 2,
    "juillet": 7, "septembre": 9, "octobre": 10, "novembre": 11,
    "decembre": 12,
}
_MOIS = "|".join(sorted(MOIS, key=len, reverse=True))


def _date(p):
    """Motif d'une date de CV : '2021', 'sept. 2021' ou '09/2021'."""
    return (
        rf"(?:(?P<{p}m>{_MOIS})\.?\s*|(?P<{p}n>\d{{1,2}})\s*/\s*)?"
        rf"(?P<{p}a>(?:19|20)\d{{2}})"
    )


MOTIF_PERIODE = re.compile(
    _date("d")
    + r"\s*(?:-|–|—|a|au|à|>)\s*"
    + rf"(?:{_date('f')}|(?P<encours>aujourd['’]?hui|ce jour|present|actuel|en cours|maintenant))"
)
MOTIF_DEPUIS = re.compile(r"depuis\s+" + _date("d"))

TITRES_EXPERIENCE = re.compile(
    r"^\s*(experiences?( professionnelles?)?|parcours professionnel|"
    r"emplois?|work experience|experience)\s*:?\s*$"
)
# Fin de la rubrique experience : uniquement les rubriques de formation.
# Dans un CV sur deux colonnes, le texte des colonnes est entremele : les
# titres "Competences", "Langues" ou "Certifications" de la colonne de
# gauche tombent au milieu des experiences et ne marquent pas leur fin.
TITRES_FIN = re.compile(
    r"^\s*(formations?|diplomes?|etudes|education|parcours (academique|scolaire)|"
    r"cursus)\b.{0,25}$"
)


def _section_experience(texte_normalise):
    """Le texte de la rubrique experience si on la trouve, sinon tout."""
    lignes = texte_normalise.splitlines()
    debut = next(
        (i for i, l in enumerate(lignes) if TITRES_EXPERIENCE.match(l)), None
    )
    if debut is None:
        return texte_normalise, False

    fin = next(
        (i for i in range(debut + 1, len(lignes)) if TITRES_FIN.match(lignes[i])),
        len(lignes),
    )
    return "\n".join(lignes[debut:fin]), True


def _mois_index(groupes, prefixe, defaut_mois):
    annee = int(groupes[f"{prefixe}a"])
    if groupes.get(f"{prefixe}m"):
        mois = MOIS[groupes[f"{prefixe}m"]]
    elif groupes.get(f"{prefixe}n"):
        mois = min(max(int(groupes[f"{prefixe}n"]), 1), 12)
    else:
        mois = defaut_mois
    return annee * 12 + mois - 1


def estimer_experience(texte, aujourdhui=None):
    """Annees d'experience : somme des periodes, chevauchements fusionnes.

    Renvoie (annees, fiable). `fiable` est faux quand la rubrique
    experience n'a pas ete reperee : les dates de formation risquent alors
    d'etre comptees. L'utilisateur peut toujours corriger.
    """
    aujourdhui = aujourdhui or date.today()
    maintenant = aujourdhui.year * 12 + aujourdhui.month - 1
    section, reperee = _section_experience(_normaliser(texte))

    periodes = []
    for m in MOTIF_PERIODE.finditer(section):
        g = m.groupdict()
        debut = _mois_index(g, "d", 1)
        fin = maintenant if g.get("encours") else _mois_index(g, "f", 12)
        if debut <= fin <= maintenant + 1:
            periodes.append((debut, min(fin, maintenant)))
    for m in MOTIF_DEPUIS.finditer(section):
        debut = _mois_index(m.groupdict(), "d", 1)
        if debut <= maintenant:
            periodes.append((debut, maintenant))

    if not periodes:
        return None, reperee

    periodes.sort()
    total, (cour_debut, cour_fin) = 0, periodes[0]
    for debut, fin in periodes[1:]:
        if debut <= cour_fin:
            cour_fin = max(cour_fin, fin)
        else:
            total += cour_fin - cour_debut + 1
            cour_debut, cour_fin = debut, fin
    total += cour_fin - cour_debut + 1

    return round(total / 12, 1), reperee


# ---------------------------------------------------------------- postes

MAX_POSTES = 4        # au-dela, la proposition perd son interet
SEUIL_COUVERTURE = 0.45
LIGNES_TITRE = 3     # le titre d'un CV est dans ses premieres lignes

def proposer_postes(texte, competences):
    """Postes proposes, du plus probable au moins probable.

    Deux indices : le titre ecrit en tete du CV ("Ingenieure en developpement
    logiciel") et la part des competences typiques du poste presentes dans
    le CV. Le titre est cherche dans les toutes premieres lignes seulement :
    plus bas, les mots "web" ou "reseau" d'une description d'experience
    feraient proposer a tort des dizaines de postes.
    """
    lignes = [l for l in texte.splitlines() if l.strip()][:LIGNES_TITRE]
    tete = re.sub(r"\s+", " ", _normaliser(" ".join(lignes)))
    mes = {c.lower() for c in competences}

    resultats = []
    for famille in charger_postes():
        titre = any(motif.search(tete) for motif in famille["motifs"])
        typiques = famille["competences_typiques"]
        couverture = sum(c.lower() in mes for c in typiques) / len(typiques)
        if titre or couverture >= SEUIL_COUVERTURE:
            resultats.append((titre, couverture, famille["id"]))

    if not resultats:
        meilleure = max(
            charger_postes(),
            key=lambda f: sum(c.lower() in mes for c in f["competences_typiques"]),
        )
        return [meilleure["id"]]

    resultats.sort(reverse=True)
    return [identifiant for _, _, identifiant in resultats][:MAX_POSTES]


# -------------------------------------------------------------- diplome

NIVEAUX = [
    (re.compile(r"\b(doctorat|phd|these)\b"), "Bac+8"),
    (re.compile(r"\b(master|mastere|msc|mba|ingenieur diplome|diplome d'ingenieur|bac ?\+ ?5)\b"), "Bac+5"),
    (re.compile(r"\b(licence|bachelor|but|bac ?\+ ?3)\b"), "Bac+3"),
    (re.compile(r"\b(bts|dut|deust|bac ?\+ ?2)\b"), "Bac+2"),
]


def niveau_diplome(texte):
    texte = _normaliser(texte)
    for motif, niveau in NIVEAUX:
        if motif.search(texte):
            return niveau
    return None


# ---------------------------------------------------------------- entree

def analyser_cv(contenu, nom_fichier, aujourdhui=None):
    """Point d'entree unique utilise par l'application."""
    texte = extraire_texte(contenu, nom_fichier)
    competences = [libelle for libelle, _ in extraire_competences(texte)]
    annees, experience_fiable = estimer_experience(texte, aujourdhui)

    return {
        "competences": competences,
        "postes": proposer_postes(texte, competences),
        "experience_annees": annees,
        "experience_fiable": experience_fiable,
        "diplome": niveau_diplome(texte),
        "nb_caracteres": len(texte),
    }