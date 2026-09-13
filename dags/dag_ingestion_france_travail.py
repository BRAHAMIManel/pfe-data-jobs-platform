"""
DAG d'ingestion France Travail — domaine ROME M18.

1. perimetre_rome : recupere la liste des metiers depuis le referentiel
2. collecte_vers_raw : un fichier brut par metier, sans transformation
3. normalisation_vers_silver : fusion, deduplication, filtre de fraicheur
"""

import logging
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator

from france_travail import (
    JOURS_MAX_ANCIENNETE,
    dedupliquer,
    filtrer_offres,
    get_access_token,
    get_offres_par_rome,
    lister_metiers_du_domaine,
)
from storage import ecrire_json, lire_json

logger = logging.getLogger(__name__)

TOTAL_PAR_ROME = 2000

BUCKET_RAW = "raw"
BUCKET_SILVER = "silver"

default_args = {
    "owner": "manel",
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
}


def resoudre_perimetre(**context):
    """Recupere la liste des metiers M18 et l'archive dans raw."""
    date_execution = context["ds"]

    token = get_access_token()
    metiers = lister_metiers_du_domaine(token)

    if not metiers:
        raise ValueError("Referentiel ROME vide — perimetre introuvable.")

    # Archive : le referentiel evolue, on garde la photo du jour.
    ecrire_json(
        BUCKET_RAW,
        f"referentiel_rome/date={date_execution}/metiers_m18.json",
        metiers,
    )

    logger.info("Perimetre : %s metiers.", len(metiers))
    return metiers


def collecter_vers_raw(**context):
    """Collecte chaque metier et depose un fichier brut par code."""
    date_execution = context["ds"]
    run_id = context["run_id"]
    metiers = context["ti"].xcom_pull(task_ids="perimetre_rome")

    token = get_access_token()
    chemins = {}
    vides = []
    echecs = []

    for metier in metiers:
        code = metier["code"]
        try:
            offres = get_offres_par_rome(
                token, code, total_souhaite=TOTAL_PAR_ROME
            )
        except Exception as erreur:
            # Un metier en echec ne doit pas perdre tous les autres.
            logger.error("ROME %s : echec — %s", code, erreur)
            echecs.append(code)
            continue

        if not offres:
            vides.append(code)
            continue

        chemin = (
            f"france_travail/code_rome={code}/"
            f"date={date_execution}/offres_{run_id}.json"
        )
        ecrire_json(BUCKET_RAW, chemin, offres)
        chemins[code] = chemin
        logger.info("ROME %s (%s) : %s offres.", code, metier["libelle"], len(offres))

    if not chemins:
        raise ValueError("Aucun metier n'a produit d'offres — run en echec.")

    logger.info(
        "Collecte terminee : %s metiers avec offres, %s sans offre, %s en echec.",
        len(chemins), len(vides), len(echecs),
    )
    if echecs:
        logger.warning("Metiers en echec : %s", echecs)

    return chemins


def normaliser_vers_silver(**context):
    """Fusionne les fichiers bruts, deduplique, filtre, ecrit dans silver."""
    date_execution = context["ds"]
    chemins = context["ti"].xcom_pull(task_ids="collecte_vers_raw")

    toutes_les_offres = []
    for code_rome, chemin in chemins.items():
        offres = lire_json(BUCKET_RAW, chemin)
        for offre in offres:
            # Trace de l'origine : une offre remonte sous plusieurs metiers.
            offre["_code_rome_collecte"] = code_rome
        toutes_les_offres.extend(offres)

    avant_dedup = len(toutes_les_offres)
    offres_uniques = dedupliquer(toutes_les_offres)

    offres_filtrees, stats = filtrer_offres(
        offres_uniques, jours_max=JOURS_MAX_ANCIENNETE
    )
    stats["metiers_collectes"] = len(chemins)
    stats["collectees_brutes"] = avant_dedup
    stats["doublons_supprimes"] = avant_dedup - len(offres_uniques)

    chemin = f"france_travail/date={date_execution}/offres_filtrees.json"
    ecrire_json(BUCKET_SILVER, chemin, offres_filtrees)

    logger.info("Statistiques : %s", stats)
    return stats


with DAG(
    dag_id="ingestion_france_travail",
    description="Collecte des offres France Travail (domaine ROME M18)",
    start_date=datetime(2026, 9, 1),
    schedule="0 6 * * *",
    catchup=False,
    default_args=default_args,
    tags=["pfe", "ingestion", "france_travail"],
) as dag:

    perimetre_rome = PythonOperator(
        task_id="perimetre_rome",
        python_callable=resoudre_perimetre,
    )

    collecte_vers_raw = PythonOperator(
        task_id="collecte_vers_raw",
        python_callable=collecter_vers_raw,
    )

    normalisation_vers_silver = PythonOperator(
        task_id="normalisation_vers_silver",
        python_callable=normaliser_vers_silver,
    )

    perimetre_rome >> collecte_vers_raw >> normalisation_vers_silver