"""
DAG du detecteur de niches.

Recalcule l'agregat de tension par metier et departement a partir du
schema en etoile. S'execute apres le chargement gold.
"""

import logging
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator

from tension import calculer_tension, top_niches

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


with DAG(
    dag_id="detecteur_niches",
    description="Calcul du score de tension par metier et departement",
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
