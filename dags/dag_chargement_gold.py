"""
DAG de chargement gold — silver vers le schema en etoile.

Lit le fichier silver du jour, eclate les offres en dimensions et faits,
puis charge dans postgres-dwh. Reexecutable sans creer de doublon.

Lance par le DAG d'ingestion (plus d'horaire fixe). La date a charger
arrive dans la configuration du run : {"date": "AAAA-MM-JJ"}. Lance a la
main sans configuration, il prend la date du jour.

Lecture : le Parquet produit par Spark en priorite, le JSON sinon.
A la fin, il lance detecteur_niches pour la meme date.
"""

import io
import logging
from datetime import date, datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.operators.trigger_dagrun import TriggerDagRunOperator

from dwh import (
    charger_dimensions,
    charger_faits,
    charger_pont_competences,
    charger_referentiels,
    completer_offres_anciennes,
    creer_schema,
)
from storage import lire_json, lire_octets, objet_existe
from transformation import (
    URL_OFFRE_FRANCE_TRAVAIL,
    charger_dictionnaire,
    charger_postes,
    classer_poste,
    est_hors_perimetre,
    extraire_competences,
    parser_date,
    parser_experience,
    parser_lieu,
    parser_salaire,
    url_offre,
)

logger = logging.getLogger(__name__)

BUCKET_SILVER = "silver"

default_args = {
    "owner": "manel",
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}


def date_a_charger(context):
    """Date transmise par le DAG d'ingestion, sinon la date du run."""
    conf = getattr(context.get("dag_run"), "conf", None) or {}
    return conf.get("date") or context["ds"]


def lire_silver(date_execution):
    """Offres silver d'une date : Parquet (Spark) si present, JSON sinon.

    Renvoie (offres, format_lu). Les offres sont des dictionnaires dans
    les deux cas, le reste du chargement ne voit pas la difference.
    """
    base = f"france_travail/date={date_execution}/offres"

    if objet_existe(BUCKET_SILVER, base + ".parquet"):
        import pyarrow.parquet as pq

        table = pq.read_table(io.BytesIO(lire_octets(BUCKET_SILVER, base + ".parquet")))
        return table.to_pylist(), "parquet"

    logger.warning("Pas de Parquet pour %s : lecture du JSON.", date_execution)
    return lire_json(BUCKET_SILVER, base + ".json"), "json"


def competences_de(offre, categories):
    """Competences d'une offre : celles trouvees par Spark si disponibles.

    Une offre lue depuis le JSON n'a pas ce champ : on fait l'extraction
    en Python, avec le meme dictionnaire. Le resultat est identique.
    """
    deja = offre.get("competences_extraites")
    if deja is not None:
        return [(libelle, categories[libelle]) for libelle in deja if libelle in categories]
    return extraire_competences(offre.get("description"))


def initialiser_schema(**_):
    creer_schema()
    charger_referentiels(
        [(f["id"], f["libelle"], f["categorie"]) for f in charger_postes()]
    )


def charger_entrepot(**context):
    date_execution = date_a_charger(context)

    offres, format_lu = lire_silver(date_execution)
    logger.info("%s offres lues depuis silver (%s, %s).",
                len(offres), format_lu, date_execution)
    categories = {libelle: cat for libelle, cat, _ in charger_dictionnaire()}

    metiers, lieux, entreprises = {}, {}, set()
    contrats, dates, competences = set(), {}, {}
    lignes_offres, liens_competences = [], []

    for offre in offres:
        identifiant = offre.get("id")
        if not identifiant:
            continue

        code_rome = offre.get("romeCode")
        if code_rome:
            metiers[code_rome] = offre.get("romeLibelle")

        lieu = parser_lieu(offre.get("lieuTravail"))
        code_insee = lieu["code_insee"] if lieu else None
        if lieu:
            lieux[code_insee] = lieu

        ent = offre.get("entreprise") or {}
        nom_ent = ent.get("nom")
        # Chaine vide plutot que None : dans PostgreSQL deux NULL ne sont
        # jamais egaux, donc ON CONFLICT ne detecterait aucun doublon et la
        # dimension grossirait a chaque execution.
        secteur = offre.get("secteurActiviteLibelle") or ""
        cle_ent = (nom_ent, secteur) if nom_ent else None
        if cle_ent:
            entreprises.add(
                (nom_ent, secteur, offre.get("trancheEffectifEtab"))
            )

        cle_contrat = (
            offre.get("typeContrat") or "",
            offre.get("experienceExige") or "",
            offre.get("qualificationLibelle") or "",
            bool(offre.get("alternance")),
        )
        contrats.add((
            cle_contrat[0], offre.get("typeContratLibelle"),
            cle_contrat[1], cle_contrat[2], cle_contrat[3],
        ))

        date_creation = parser_date(offre.get("dateCreation"))
        if date_creation:
            dates[date_creation] = (
                date_creation, date_creation.year, date_creation.month,
                date_creation.isocalendar()[1], date_creation.weekday(),
            )

        trouvees = competences_de(offre, categories)
        for libelle, categorie in trouvees:
            competences[libelle] = categorie
            liens_competences.append((identifiant, libelle))

        salaire_min, salaire_max, periode = parser_salaire(offre.get("salaire"))

        lignes_offres.append({
            "id_offre": identifiant,
            "code_rome": code_rome,
            "code_insee": code_insee,
            "cle_ent": cle_ent,
            "cle_contrat": cle_contrat,
            "date_creation": date_creation,
            "nombre_postes": offre.get("nombrePostes"),
            "manque_candidats": bool(offre.get("offresManqueCandidats")),
            "salaire_min": salaire_min,
            "salaire_max": salaire_max,
            "salaire_periode": periode,
            "intitule": offre.get("intitule"),
            "url_offre": url_offre(offre),
            "experience_annees": parser_experience(offre),
            "id_poste": classer_poste(offre.get("intitule")),
        })

    cles = charger_dimensions(
        metiers=[(c, l) for c, l in metiers.items()],
        lieux=[
            (v["code_insee"], v["ville"], v["ville_normalisee"],
             v["code_postal"], v["departement"], v["latitude"], v["longitude"])
            for v in lieux.values()
        ],
        entreprises=list(entreprises),
        contrats=list(contrats),
        dates=list(dates.values()),
        competences=[(l, c) for l, c in competences.items()],
    )

    aujourdhui = date.today()
    faits = [
        (
            o["id_offre"], o["code_rome"], o["code_insee"],
            cles["entreprises"].get(o["cle_ent"]) if o["cle_ent"] else None,
            cles["contrats"].get(o["cle_contrat"]),
            o["date_creation"], aujourdhui, aujourdhui,
            # Duree depuis la publication, pas depuis notre premiere collecte :
            # la mesure ne depend plus des jours ou le pipeline n'a pas tourne.
            (aujourdhui - o["date_creation"]).days if o["date_creation"] else 0,
            o["nombre_postes"], o["manque_candidats"],
            o["salaire_min"], o["salaire_max"], o["salaire_periode"],
            o["intitule"], "france_travail",
            o["url_offre"], o["experience_annees"], o["id_poste"],
        )
        for o in lignes_offres
    ]

    nouvelles, mises_a_jour = charger_faits(faits)

    liens = [
        (id_offre, cles["competences"][libelle])
        for id_offre, libelle in liens_competences
        if libelle in cles["competences"]
    ]
    nb_liens = charger_pont_competences(liens)

    # Toutes les offres de l'entrepot : lien, poste et hors perimetre a jour.
    anciennes = completer_offres_anciennes(
        classer_poste, URL_OFFRE_FRANCE_TRAVAIL.format(""), est_hors_perimetre
    )

    stats = {
        "date": date_execution,
        "format_silver": format_lu,
        "offres_lues": len(offres),
        "offres_nouvelles": nouvelles,
        "offres_revues": mises_a_jour,
        "metiers": len(metiers),
        "lieux": len(lieux),
        "entreprises": len(entreprises),
        "competences_distinctes": len(competences),
        "liens_competences": nb_liens,
        "offres_avec_famille_de_poste": sum(1 for o in lignes_offres if o["id_poste"]),
        "offres_avec_experience": sum(
            1 for o in lignes_offres if o["experience_annees"] is not None
        ),
        **anciennes,
    }
    logger.info("Chargement termine : %s", stats)
    return stats


with DAG(
    dag_id="chargement_gold",
    description="Chargement du schema en etoile depuis la couche silver",
    start_date=datetime(2026, 9, 1),
    schedule=None,  # lance par ingestion_france_travail
    catchup=False,
    default_args=default_args,
    tags=["pfe", "gold", "entrepot"],
) as dag:

    schema = PythonOperator(
        task_id="initialiser_schema",
        python_callable=initialiser_schema,
    )

    chargement = PythonOperator(
        task_id="charger_entrepot",
        python_callable=charger_entrepot,
    )

    declencher_detecteur = TriggerDagRunOperator(
        task_id="declencher_detecteur",
        trigger_dag_id="detecteur_niches",
        conf={"date": "{{ (dag_run.conf or {}).get('date', ds) }}"},
    )

    schema >> chargement >> declencher_detecteur