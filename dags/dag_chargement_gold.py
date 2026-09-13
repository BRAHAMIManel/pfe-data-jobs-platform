"""
DAG de chargement gold — silver vers le schema en etoile.

Lit le fichier silver du jour, eclate les offres en dimensions et faits,
puis charge dans postgres-dwh. Reexecutable sans creer de doublon.
"""

import logging
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator

from dwh import (
    charger_dimensions,
    charger_faits,
    charger_pont_competences,
    creer_schema,
)
from storage import lire_json
from transformation import (
    extraire_competences,
    parser_date,
    parser_lieu,
    parser_salaire,
)

logger = logging.getLogger(__name__)

BUCKET_SILVER = "silver"

default_args = {
    "owner": "manel",
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}


def initialiser_schema(**_):
    creer_schema()


def charger_entrepot(**context):
    date_execution = context["ds"]

    offres = lire_json(
        BUCKET_SILVER,
        f"france_travail/date={date_execution}/offres_filtrees.json",
    )
    logger.info("%s offres lues depuis silver.", len(offres))

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

        trouvees = extraire_competences(offre.get("description"))
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

    aujourdhui = datetime.strptime(date_execution, "%Y-%m-%d").date()
    faits = [
        (
            o["id_offre"], o["code_rome"], o["code_insee"],
            cles["entreprises"].get(o["cle_ent"]) if o["cle_ent"] else None,
            cles["contrats"].get(o["cle_contrat"]),
            o["date_creation"], aujourdhui, aujourdhui, 0,
            o["nombre_postes"], o["manque_candidats"],
            o["salaire_min"], o["salaire_max"], o["salaire_periode"],
            o["intitule"], "france_travail",
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

    stats = {
        "offres_lues": len(offres),
        "offres_nouvelles": nouvelles,
        "offres_revues": mises_a_jour,
        "metiers": len(metiers),
        "lieux": len(lieux),
        "entreprises": len(entreprises),
        "competences_distinctes": len(competences),
        "liens_competences": nb_liens,
    }
    logger.info("Chargement termine : %s", stats)
    return stats


with DAG(
    dag_id="chargement_gold",
    description="Chargement du schema en etoile depuis la couche silver",
    start_date=datetime(2026, 9, 1),
    schedule="0 7 * * *",  # apres les ingestions
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

    schema >> chargement