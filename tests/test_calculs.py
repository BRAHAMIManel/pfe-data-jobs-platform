"""
Tests du calcul du score d'opportunite (app/calculs.py).

Score d'un territoire, sur 100 :
    100 x ( 0,45 x tension + 0,35 x adequation au CV + 0,20 x volume )

On verifie les proprietes que le jury peut demander de prouver : le score
reste entre 0 et 100, la moyenne nationale vaut 50 de tension, plus de
signaux de tension donne un score plus haut, un petit territoire ne
s'envole pas sur une seule offre, et le croisement avec le CV est juste.
Donnees fabriquees a la main : aucune base, aucun reseau.
"""

import sys
from pathlib import Path

import pandas as pd
import pytest

# calculs.py est dans app/ (code de l'application Streamlit). Ce dossier
# n'est pas monte dans le conteneur Airflow : les tests sont alors sautes.
DOSSIER_APP = Path(__file__).resolve().parent.parent / "app"
if DOSSIER_APP.is_dir():
    sys.path.insert(0, str(DOSSIER_APP))
calculs = pytest.importorskip("calculs")


REFS = {"persistance": 0.20, "manque": 0.10, "republication": 0.05}


def territoire(offres, persistantes, manque, republications):
    """Une ligne de territoire, au format attendu par indice_penurie."""
    return pd.DataFrame({
        "offres": [offres],
        "persistantes": [persistantes],
        "manque": [manque],
        "republications": [republications],
    })


def offre(ville, competences, persistante=False, manque=False,
          republication=False, experience=0, region="11"):
    return {
        "cle_ville": ville,
        "code_region": region,
        "region": "Ile-de-France",
        "ville_affichee": ville,
        "departement": "75",
        "competences": competences,
        "nb_requises": len(competences),
        "persistante": persistante,
        "manque": manque,
        "republication": republication,
        "recente": True,
        "jours_en_ligne": 10,
        "experience_annees": experience,
    }


# ------------------------------------------------------------ poids

class TestPoids:
    def test_poids_du_score_font_100_pourcent(self):
        assert sum(calculs.POIDS.values()) == pytest.approx(1.0)

    def test_poids_des_signaux_font_100_pourcent(self):
        assert sum(calculs.POIDS_SIGNAUX.values()) == pytest.approx(1.0)

    def test_signaux_a_poids_egaux(self):
        # Choix justifie par le calibrage BMO : aucun signal plus fiable.
        assert len(set(round(p, 6) for p in calculs.POIDS_SIGNAUX.values())) == 1


# ---------------------------------------------------- tension (indice)

class TestTension:
    def test_territoire_dans_la_moyenne_vaut_indice_1(self):
        # 100 offres avec exactement les taux nationaux.
        t = territoire(100, 20, 10, 5)
        assert calculs.indice_penurie(t, REFS).iloc[0] == pytest.approx(1.0)

    def test_moyenne_nationale_donne_tension_50(self):
        tension = calculs.penurie_depuis_indice(pd.Series([1.0]))
        assert tension.iloc[0] == pytest.approx(0.5)

    def test_tension_bornee_entre_0_et_1(self):
        tension = calculs.penurie_depuis_indice(pd.Series([0.0, 0.2, 3.0, 10.0]))
        assert tension.between(0, 1).all()
        assert tension.iloc[0] == 0 and tension.iloc[-1] == 1

    def test_plus_de_signaux_donne_un_indice_plus_haut(self):
        calme = territoire(100, 10, 5, 2)
        tendu = territoire(100, 40, 20, 10)
        assert (calculs.indice_penurie(tendu, REFS).iloc[0]
                > calculs.indice_penurie(calme, REFS).iloc[0])

    def test_petit_territoire_ne_s_envole_pas(self):
        # 1 offre sur 1 en republication = 100 % au lieu de 5 % national.
        # Sans lissage, le signal vaudrait 20 fois la moyenne.
        t = territoire(1, 0, 0, 1)
        assert calculs.indice_penurie(t, REFS).iloc[0] < 2

    def test_signal_absent_au_national_ignore(self):
        # Pas de republication detectee en France : ce signal est ignore,
        # les deux autres gardent un indice de 1 pour un territoire moyen.
        refs = {"persistance": 0.20, "manque": 0.10, "republication": 0.0}
        t = territoire(100, 20, 10, 0)
        assert calculs.indice_penurie(t, refs).iloc[0] == pytest.approx(1.0)


# --------------------------------------------------------- croisement CV

class TestEvaluerOffres:
    def offres(self):
        return pd.DataFrame([
            offre("a", ["python", "sql", "spark"]),
            offre("a", ["java", "spring"]),
            offre("a", ["python"], experience=10),
        ])

    def test_adequation_part_des_competences_couvertes(self):
        r = calculs.evaluer_offres(self.offres(), ["Python", "SQL"], 3)
        assert r["adequation"].tolist() == pytest.approx([2 / 3, 0, 1])

    def test_casse_ignoree(self):
        r = calculs.evaluer_offres(self.offres(), ["PYTHON", "sql"], 3)
        assert r["nb_communes"].iloc[0] == 2

    def test_compatible_si_deux_competences_communes(self):
        r = calculs.evaluer_offres(self.offres(), ["python", "sql"], 3)
        assert r["compatible"].tolist() == [True, False, True]

    def test_offre_trop_experimentee_ecartee(self):
        # 10 ans demandes, 3 ans au CV + 2 de tolerance : hors niveau.
        r = calculs.evaluer_offres(self.offres(), ["python"], 3)
        assert r["hors_niveau"].tolist() == [False, False, True]

    def test_sans_experience_au_cv_rien_n_est_ecarte(self):
        r = calculs.evaluer_offres(self.offres(), ["python"], None)
        assert not r["hors_niveau"].any()


# ------------------------------------------------------------ score

class TestScore:
    def noter(self, lignes, cv=("python", "sql")):
        df = calculs.evaluer_offres(pd.DataFrame(lignes), list(cv), 5)
        r = calculs.noter_territoires(df, "ville", REFS)
        return r if r.empty else r.set_index("code")

    def test_score_entre_0_et_100(self):
        lignes = (
            [offre("a", ["python", "sql"], True, True, True)] * 40
            + [offre("b", ["python", "sql", "java", "go"])] * 3
        )
        s = self.noter(lignes)["score"]
        assert s.between(0, 100).all()

    def test_score_maximal_possible_est_100(self):
        # Tout en tension, CV couvrant tout, plus gros volume : 100.
        lignes = [offre("a", ["python", "sql"], True, True, True)] * 200
        assert self.noter(lignes).loc["a", "score"] == 100

    def test_ville_plus_tendue_mieux_classee_toutes_choses_egales(self):
        lignes = (
            [offre("tendue", ["python", "sql"], persistante=True, manque=True)] * 30
            + [offre("calme", ["python", "sql"])] * 30
        )
        s = self.noter(lignes)["score"]
        assert s["tendue"] > s["calme"]

    def test_meilleure_adequation_mieux_classee(self):
        lignes = (
            [offre("adaptee", ["python", "sql"])] * 30
            + [offre("partielle", ["python", "sql", "java", "go"])] * 30
        )
        s = self.noter(lignes)["score"]
        assert s["adaptee"] > s["partielle"]

    def test_territoire_fragile_classe_apres_les_fiables(self):
        # 2 offres tres tendues ("Fragile") contre 40 offres moyennes.
        lignes = (
            [offre("petite", ["python", "sql"], True, True, True)] * 2
            + [offre("grande", ["python", "sql"])] * 40
        )
        r = calculs.noter_territoires(
            calculs.evaluer_offres(pd.DataFrame(lignes), ["python", "sql"], 5),
            "ville", REFS,
        )
        assert r["code"].tolist() == ["grande", "petite"]
        assert r.iloc[-1]["fiabilite"] == "Fragile"

    def test_aucune_offre_compatible_donne_tableau_vide(self):
        lignes = [offre("a", ["java", "spring"])] * 10
        assert self.noter(lignes).empty


# --------------------------------------------------------- libelles

class TestLibelles:
    @pytest.mark.parametrize("offres, attendu", [
        (30, "Fiable"), (29, "Indicatif"), (10, "Indicatif"), (9, "Fragile"),
    ])
    def test_seuils_de_fiabilite(self, offres, attendu):
        assert calculs.fiabilite(offres) == attendu

    def test_fragile_ne_conclut_pas_meme_avec_bon_score(self):
        assert calculs.etiquette(90, "Fragile") == "Trop peu d'offres pour conclure"

    @pytest.mark.parametrize("score, attendu", [
        (65, "Très bonne piste"), (50, "Bonne piste"), (49, "Piste possible"),
    ])
    def test_etiquettes(self, score, attendu):
        assert calculs.etiquette(score) == attendu