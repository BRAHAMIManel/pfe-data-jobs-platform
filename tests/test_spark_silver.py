"""
Tests du job PySpark raw -> silver.

Ils lancent un vrai Spark local sur de petits fichiers JSON : environ
20 secondes. Ils sont ignores si PySpark ou Java ne sont pas installes.

Le test le plus important : Spark et Python doivent trouver EXACTEMENT
les memes competences. Sinon le resultat changerait selon le chemin
pris (Parquet ou repli JSON).
"""

import json
import os
import shutil

import pytest

pytest.importorskip("pyspark")
if not (os.getenv("JAVA_HOME") or shutil.which("java")):
    pytest.skip("Java absent : Spark ne peut pas tourner", allow_module_level=True)

import pyarrow.parquet as pq  # noqa: E402

from spark_silver import chemin_local, construire_silver, creer_session  # noqa: E402
from transformation import extraire_competences  # noqa: E402

DESCRIPTIONS = [
    "Développeur Python / Django, PostgreSQL et Docker. Notions de C# et .NET.",
    "Data engineer : Spark, Airflow, dbt, SQL. Power BI apprécié.",
    "Technicien support : Windows, Active Directory, ITIL.",
    "Poste en C++ embarqué, Linux, Git.",
    "Aucune compétence technique citée ici.",
    "",
]


def offre(identifiant, description, **autres):
    base = {
        "id": identifiant,
        "intitule": f"Offre {identifiant}",
        "description": description,
        "romeCode": "M1805",
        "lieuTravail": {"libelle": "75 - PARIS 15", "codePostal": "75015",
                        "commune": "75115", "latitude": 48.84, "longitude": 2.29},
        "dateCreation": "2026-10-20T10:00:00.000Z",
        "offresManqueCandidats": False,
    }
    base.update(autres)
    return base


@pytest.fixture(scope="module")
def spark():
    session = creer_session("tests_spark_silver")
    yield session
    session.stop()


@pytest.fixture
def fichiers_bruts(tmp_path):
    """Deux metiers ; l'offre 1 est collectee sous les deux."""
    m1805 = [offre(str(i), d) for i, d in enumerate(DESCRIPTIONS, start=1)]
    m1810 = [
        offre("1", DESCRIPTIONS[0], romeCode="M1810"),       # doublon
        offre("99", "Administrateur réseau Cisco", salaire={"libelle": "Mensuel de 2500 Euros"}),
    ]
    chemins = []
    for code, offres in (("M1805", m1805), ("M1810", m1810)):
        dossier = tmp_path / f"code_rome={code}" / "date=2026-10-31"
        dossier.mkdir(parents=True)
        fichier = dossier / "offres_test.json"
        fichier.write_text(json.dumps(offres, ensure_ascii=False), encoding="utf-8")
        chemins.append(fichier)
    return chemins


@pytest.fixture
def resultat(spark, fichiers_bruts, tmp_path):
    parquet, stats = construire_silver(spark, fichiers_bruts, tmp_path / "sortie")
    lignes = {l["id"]: l for l in pq.read_table(parquet).to_pylist()}
    return lignes, stats


def test_doublons_supprimes(resultat):
    lignes, stats = resultat
    assert stats["offres_brutes"] == 8
    assert stats["offres_silver"] == 7
    assert stats["doublons_supprimes"] == 1
    assert len(lignes) == 7


def test_doublon_garde_le_plus_petit_code(resultat):
    lignes, _ = resultat
    assert lignes["1"]["_code_rome_collecte"] == "M1805"
    assert lignes["99"]["_code_rome_collecte"] == "M1810"


@pytest.mark.parametrize("position", range(len(DESCRIPTIONS)))
def test_memes_competences_que_python(resultat, position):
    lignes, _ = resultat
    identifiant = str(position + 1)
    attendu = sorted(l for l, _ in extraire_competences(DESCRIPTIONS[position]))
    assert sorted(lignes[identifiant]["competences_extraites"]) == attendu


def test_symboles_reconnus(resultat):
    """C#, C++ et .NET : les cas qui echouaient avec \\b."""
    lignes, _ = resultat
    assert "C#" in lignes["1"]["competences_extraites"]
    assert "C++" in lignes["4"]["competences_extraites"]


def test_champs_imbriques_conserves(resultat):
    """Le chargement gold lit lieuTravail, salaire... comme des dict."""
    lignes, _ = resultat
    assert lignes["1"]["lieuTravail"]["codePostal"] == "75015"
    assert lignes["99"]["salaire"]["libelle"] == "Mensuel de 2500 Euros"
    assert lignes["1"]["salaire"] is None


def test_un_seul_fichier_parquet(resultat):
    _, stats = resultat
    assert stats["taille_parquet_ko"] > 0


def test_chemin_local_sans_deux_points(tmp_path):
    """Bug du 9/11 : le run_id d'Airflow met des ":" dans le nom du fichier
    brut, ce que Spark refuse. Le chemin local n'en contient plus."""
    local = chemin_local(tmp_path, "M1805")
    assert ":" not in local.name
    assert local.parent.name == "code_rome=M1805"


def test_nom_airflow_reel_lisible(spark, tmp_path):
    """Le run complet avec un vrai nom de run Airflow passe dans Spark."""
    brut = (
        tmp_path / "lac" / "france_travail" / "code_rome=M1805" / "date=2026-11-08"
        / "offres_scheduled__2026-11-08T11:00:00+00:00.json"
    )
    brut.parent.mkdir(parents=True)
    brut.write_text(json.dumps([offre("1", "Python et SQL")]), encoding="utf-8")

    local = chemin_local(tmp_path / "travail", "M1805")
    local.parent.mkdir(parents=True)
    local.write_bytes(brut.read_bytes())

    parquet, stats = construire_silver(spark, [local], tmp_path / "sortie")
    assert stats["offres_silver"] == 1
    ligne = pq.read_table(parquet).to_pylist()[0]
    assert ligne["_code_rome_collecte"] == "M1805"