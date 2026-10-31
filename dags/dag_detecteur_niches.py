"""
DAG du detecteur de niches.

Recalcule l'agregat de tension par metier et departement a partir du
schema en etoile. S'execute apres le chargement gold.
"""

import logging
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator

from tension import (
    calculer_opportunite,
    calculer_tension,
    top_niches,
    top_territoires,
)

logger = logging.getLogger(__name__)

default_args = {
    "owner": "manel",
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}


def calculer(**context):
    date_calcul = datetime.strptime(context["ds"], "%Y-%m-%d").date()
    stats = calculer_tension(date_calcul)

    logger.info("--- Couples les plus tendus ---")
    for libelle, dept, nb, persist, score, mediane in top_niches(date_calcul):
        logger.info(
            "%-55s | %-3s | %4d offres | %3d persistantes | score %.3f | mediane %.0f j",
            libelle[:55], dept, nb, persist, score, mediane or 0,
        )

    return stats


def calculer_penurie_territoires(**context):
    date_calcul = datetime.strptime(context["ds"], "%Y-%m-%d").date()
    stats = calculer_opportunite(date_calcul)

    for niveau in ("region", "ville"):
        logger.info("--- %ss les plus en penurie ---", niveau.capitalize())
        for libelle, nb, persist, manque, recentes, indice, fiab in top_territoires(
            date_calcul, niveau
        ):
            logger.info(
                "%-30s | %4d offres | %3d > 30 j | %3d manque | %3d recentes | indice %.2f | %s",
                libelle[:30], nb, persist, manque, recentes, indice, fiab,
            )

    return stats


with DAG(
    dag_id="detecteur_niches",
    description="Score de tension (metier x departement) et indice de penurie (region, ville)",
    start_date=datetime(2026, 9, 1),
    schedule="30 12 * * *",  # apres chargement_gold
    catchup=False,
    default_args=default_args,
    tags=["pfe", "gold", "analyse"],
) as dag:

    tension = PythonOperator(
        task_id="calculer_tension",
        python_callable=calculer,
    )

    penurie = PythonOperator(
        task_id="calculer_penurie_territoires",
        python_callable=calculer_penurie_territoires,
    )

    tension >> penurie