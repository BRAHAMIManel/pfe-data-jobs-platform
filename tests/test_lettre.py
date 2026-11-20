"""Tests du modele de lettre de motivation (scripts/lettre.py)."""

from datetime import date

import lettre

OFFRE = {
    "intitule": "Data Engineer (H/F)",
    "entreprise": "ACME",
    "ville": "Lyon",
    "type_contrat": "CDI",
    "alternance": False,
    "communes": ["Python", "SQL", "Spark"],
    "id_offre": "123ABC",
}


def test_lettre_reprend_l_offre():
    texte = lettre.rediger(OFFRE, annees=3, jour=date(2026, 11, 20))
    assert "Data Engineer (H/F)" in texte
    assert "ACME" in texte
    assert "[Votre ville], le 20 novembre 2026" in texte
    assert "ACME\nLyon" in texte
    assert "un CDI" in texte
    assert "Python, SQL et Spark" in texte
    assert "3 ans d'expérience" in texte
    assert "n° 123ABC" in texte


def test_entreprise_et_ville_absentes():
    offre = dict(OFFRE, entreprise=float("nan"), ville=None)
    texte = lettre.rediger(offre, annees=0)
    assert "Service recrutement" in texte
    assert "votre entreprise" in texte
    assert "nan" not in texte
    assert "En début de carrière" in texte


def test_sans_competence_commune_on_guide_le_candidat():
    texte = lettre.rediger(dict(OFFRE, communes=[]), annees=2)
    assert "[Citez deux ou trois compétences" in texte


def test_competences_limitees_et_alternance():
    offre = dict(OFFRE, communes=list("ABCDEF"), alternance=True)
    texte = lettre.rediger(offre, annees=1)
    assert "A, B, C et D" in texte and "E" not in texte.split("notamment")[1].split(".")[0]
    assert "un contrat en alternance" in texte
    assert "un an d'expérience" in texte


def test_liste_francaise():
    assert lettre.liste_francaise([]) == ""
    assert lettre.liste_francaise(["a"]) == "a"
    assert lettre.liste_francaise(["a", "b"]) == "a et b"