"""
Tests de l'estimation des annees d'experience a partir d'un CV
(scripts/cv.py). Textes fabriques a la main, au format que pdfplumber
produit pour un CV sur deux colonnes : les colonnes sont entremelees.
"""

from datetime import date

from cv import estimer_experience

AUJOURDHUI = date(2026, 11, 18)

# CV sur deux colonnes : le titre "Experiences professionnelles" partage sa
# ligne avec la colonne de gauche, et les diplomes viennent apres.
CV_DEUX_COLONNES = """Prenom NOM
Permis B Experiences professionnelles
Alternance - Consultante data
Depuis mars 2025 Entreprise A Paris
Competences
Stage - Developpeur web
D'avril 2023 a juin 2023 Entreprise B
Langues
Diplomes
Master informatique
De 2018 a 2023 Universite
Licence
De septembre 2018 a juin 2021 Universite
"""


def test_titre_partage_avec_l_autre_colonne_est_reconnu():
    annees, reperee = estimer_experience(CV_DEUX_COLONNES, AUJOURDHUI)
    assert reperee
    # mars 2025 -> novembre 2026 (21 mois) + avril -> juin 2023 (3 mois)
    assert annees == round(24 / 12, 1)


def test_dates_des_diplomes_non_comptees():
    # Si les diplomes (2018-2023) etaient comptes, on depasserait 6 ans.
    annees, _ = estimer_experience(CV_DEUX_COLONNES, AUJOURDHUI)
    assert annees < 3


def test_titre_seul_sur_sa_ligne():
    texte = "Experience\nDe janvier 2024 a decembre 2024 Entreprise\nFormation\nDe 2015 a 2020 Ecole\n"
    annees, reperee = estimer_experience(texte, AUJOURDHUI)
    assert reperee and annees == 1.0


def test_periodes_qui_se_chevauchent_comptees_une_fois():
    texte = (
        "Experiences professionnelles\n"
        "De janvier 2024 a juin 2024 A\n"
        "De mars 2024 a decembre 2024 B\n"
    )
    annees, _ = estimer_experience(texte, AUJOURDHUI)
    assert annees == 1.0


def test_sans_rubrique_experience_le_resultat_est_signale():
    texte = "Projets\nDe 2020 a 2022 Projet perso\n"
    annees, reperee = estimer_experience(texte, AUJOURDHUI)
    assert not reperee and annees is not None