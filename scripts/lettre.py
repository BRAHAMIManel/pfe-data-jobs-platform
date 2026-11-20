"""
Modele de lettre de motivation, rempli a partir d'une offre.

Pas d'intelligence artificielle : la lettre est construite avec des
phrases fixes, completees par les informations de l'offre (intitule,
entreprise, ville, contrat) et du profil (competences en commun,
annees d'experience). Rien n'est envoye a un service exterieur.

Les passages entre crochets [ ... ] sont a personnaliser par le candidat :
une lettre utile parle de SON parcours, ce qu'un modele ne peut pas inventer.
"""

from datetime import date

MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet",
        "août", "septembre", "octobre", "novembre", "décembre"]

# Codes de type de contrat de France Travail -> formulation dans la lettre.
CONTRATS = {
    "CDI": "un CDI",
    "CDD": "un CDD",
    "MIS": "une mission d'intérim",
    "SAI": "un contrat saisonnier",
    "LIB": "une mission en indépendant",
    "FRA": "une franchise",
}

# Au-dela, la phrase devient une liste illisible : on cite les premieres.
MAX_COMPETENCES = 4


def date_en_toutes_lettres(jour):
    return f"{jour.day} {MOIS[jour.month - 1]} {jour.year}"


def liste_francaise(elements):
    """['a'] -> 'a' ; ['a', 'b', 'c'] -> 'a, b et c'."""
    elements = [e for e in elements if e]
    if len(elements) <= 1:
        return "".join(elements)
    return ", ".join(elements[:-1]) + " et " + elements[-1]


def _vide(valeur):
    """Vrai pour None, '' et NaN (les colonnes pandas manquantes)."""
    return valeur is None or valeur != valeur or str(valeur).strip() == ""


def phrase_contrat(type_contrat, alternance=False):
    if alternance:
        return "un contrat en alternance"
    if _vide(type_contrat):
        return ""
    return CONTRATS.get(str(type_contrat).strip().upper(), "")


def phrase_experience(annees):
    if _vide(annees):
        return "[Présentez en une phrase votre parcours.]"
    annees = int(round(float(annees)))
    if annees <= 0:
        return ("En début de carrière, je souhaite mettre mes compétences au service "
                "d'une équipe et continuer à progresser à vos côtés.")
    duree = "un an" if annees == 1 else f"{annees} ans"
    return (f"Avec {duree} d'expérience, je souhaite aujourd'hui mettre mes compétences "
            "au service de votre équipe.")


def phrase_competences(communes):
    communes = [c for c in (communes or []) if c]
    if not communes:
        return ("[Citez deux ou trois compétences demandées dans l'offre, avec pour "
                "chacune un exemple concret tiré de votre parcours.]")
    citees = liste_francaise(list(communes)[:MAX_COMPETENCES])
    return (f"Votre offre demande notamment {citees}. Ce sont des compétences que "
            "j'utilise déjà : [donnez un exemple concret de projet ou de mission où "
            "vous les avez mises en pratique, avec un résultat].")


def rediger(offre, annees=None, jour=None):
    """
    Texte complet de la lettre.

    offre : dict avec les cles intitule, entreprise, ville, type_contrat,
            alternance, communes (competences en commun), id_offre.
    """
    jour = jour or date.today()
    intitule = offre.get("intitule") or "[intitulé du poste]"
    entreprise = None if _vide(offre.get("entreprise")) else str(offre["entreprise"]).strip()
    ville = None if _vide(offre.get("ville")) else str(offre["ville"]).strip()
    contrat = phrase_contrat(offre.get("type_contrat"), bool(offre.get("alternance")))
    reference = "" if _vide(offre.get("id_offre")) else f" (offre France Travail n° {offre['id_offre']})"

    ou = f" à {ville}" if ville else ""
    chez = entreprise or "votre entreprise"
    accroche = f"Votre offre de {intitule}{ou} a retenu toute mon attention."
    if contrat:
        accroche += f" Je recherche justement {contrat} dans ce domaine."

    blocs = [
        "[Prénom Nom]\n[Adresse]\n[Téléphone] · [Email]",
        (entreprise or "Service recrutement") + (f"\n{ville}" if ville else ""),
        f"[Votre ville], le {date_en_toutes_lettres(jour)}",
        f"Objet : candidature au poste de {intitule}{reference}",
        "Madame, Monsieur,",
        accroche + " " + phrase_experience(annees),
        phrase_competences(offre.get("communes")),
        (f"Je souhaite rejoindre {chez} parce que [expliquez ce qui vous attire : "
         "son activité, ses projets, ses valeurs ou ses clients]."),
        ("Je me tiens à votre disposition pour un entretien, afin de vous présenter "
         "plus en détail ma motivation et mon parcours."),
        "Je vous prie d'agréer, Madame, Monsieur, l'expression de mes salutations distinguées.",
        "[Prénom Nom]",
    ]
    return "\n\n".join(blocs)


def en_docx(texte):
    """Le texte de la lettre en fichier Word (octets), un paragraphe par bloc."""
    from io import BytesIO

    from docx import Document
    from docx.shared import Pt

    document = Document()
    style = document.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(11)
    for bloc in texte.split("\n\n"):
        paragraphe = document.add_paragraph()
        lignes = bloc.split("\n")
        for i, ligne in enumerate(lignes):
            run = paragraphe.add_run(ligne)
            if i < len(lignes) - 1:
                run.add_break()
    tampon = BytesIO()
    document.save(tampon)
    return tampon.getvalue()