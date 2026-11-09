"""
Job PySpark : couche raw -> couche silver.

Ce que fait le job, dans l'ordre :
  1. lit tous les fichiers JSON bruts du jour (un par metier ROME) ;
  2. ajoute le code ROME de collecte, lu dans le chemin du fichier ;
  3. supprime les doublons (une offre remonte sous plusieurs metiers) ;
  4. extrait les competences de la description avec le dictionnaire
     competences_it.json, les memes motifs que la version Python ;
  5. ecrit un seul fichier Parquet dans silver.

Pourquoi Parquet : format en colonnes, compresse, type. Le fichier est
5 a 10 fois plus petit que le JSON et se relit beaucoup plus vite.

Pourquoi passer par un dossier local plutot que lire s3a:// directement :
la lecture S3 depuis Spark demande des jars Hadoop-AWS supplementaires et
leur configuration. Au volume du projet (quelques dizaines de Mo par jour),
telecharger les fichiers puis les traiter en local est plus simple et
donne le meme resultat. Spark tourne en mode local, dans le conteneur
Airflow : pas de cluster a gerer.
"""

import logging
import os
import shutil
import tempfile
from pathlib import Path

from transformation import charger_dictionnaire

logger = logging.getLogger(__name__)

BUCKET_RAW = "raw"
BUCKET_SILVER = "silver"

# Lettres accentuees -> sans accent, comme _normaliser() en Python.
# Spark n'a pas de normalisation Unicode, on passe par translate().
ACCENTS = "àáâãäåçèéêëìíîïñòóôõöùúûüýÿ"
SANS_ACCENTS = "aaaaaaceeeeiiiinooooouuuuyy"


def chemin_parquet_silver(date_execution):
    """Chemin du fichier Parquet silver pour une date."""
    return f"france_travail/date={date_execution}/offres.parquet"


def creer_session(nom="silver_france_travail"):
    """Session Spark locale, sobre en memoire."""
    from pyspark.sql import SparkSession

    # Le conteneur tourne parfois avec un UID sans nom d'utilisateur :
    # Hadoop echoue alors en cherchant ce nom. On le fixe.
    os.environ.setdefault("HADOOP_USER_NAME", "airflow")

    return (
        SparkSession.builder
        .appName(nom)
        .master(os.getenv("SPARK_MASTER", "local[2]"))
        .config("spark.driver.memory", os.getenv("SPARK_DRIVER_MEMORY", "1g"))
        .config("spark.driver.host", "127.0.0.1")
        .config("spark.driver.bindAddress", "127.0.0.1")
        .config("spark.sql.shuffle.partitions", "4")
        .config("spark.sql.session.timeZone", "UTC")
        .config("spark.ui.enabled", "false")
        .getOrCreate()
    )


def motifs_spark():
    """[(libelle, motif)] au format des expressions regulieres Java.

    Les motifs viennent du meme dictionnaire que la version Python.
    (?U) rend \\w compatible Unicode en Java, comme en Python : sans lui,
    une lettre comme "œ" serait vue comme un separateur.
    """
    return [
        (libelle, "(?U)" + motif.pattern)
        for libelle, _categorie, motif in charger_dictionnaire()
    ]


def construire_silver(spark, fichiers_json, dossier_sortie):
    """Transforme des fichiers JSON bruts en un fichier Parquet.

    fichiers_json : chemins locaux, de la forme
        .../code_rome=M1805/date=2026-10-31/offres_xxx.json
    dossier_sortie : dossier local ou ecrire le Parquet.

    Renvoie (chemin_du_fichier_parquet, statistiques).
    """
    from pyspark.sql import Window
    from pyspark.sql import functions as F

    brut = (
        spark.read
        .option("multiLine", True)      # chaque fichier est un tableau JSON
        .option("mode", "PERMISSIVE")   # une offre mal formee ne bloque rien
        .json([str(f) for f in fichiers_json])
        .withColumn(
            "_code_rome_collecte",
            F.regexp_extract(F.input_file_name(), r"code_rome=([^/]+)", 1),
        )
    )
    brut = brut.filter(F.col("id").isNotNull()).cache()
    nb_brut = brut.count()

    # 1 offre = 1 ligne. Quand une offre remonte sous plusieurs metiers,
    # on garde celle du plus petit code ROME : le resultat ne depend pas
    # de l'ordre de lecture des fichiers.
    rang = Window.partitionBy("id").orderBy("_code_rome_collecte")
    uniques = (
        brut.withColumn("_rang", F.row_number().over(rang))
        .filter(F.col("_rang") == 1)
        .drop("_rang")
    )

    # Description en minuscules, sans accents : celle que lisent les motifs.
    texte = F.translate(
        F.lower(F.coalesce(F.col("description"), F.lit(""))),
        ACCENTS, SANS_ACCENTS,
    )
    trouvees = [
        F.when(texte.rlike(motif), F.lit(libelle))
        for libelle, motif in motifs_spark()
    ]
    avec_competences = uniques.withColumn(
        "competences_extraites",
        F.filter(F.array(*trouvees), lambda c: c.isNotNull()),
    )

    dossier_spark = Path(dossier_sortie) / "spark"
    (
        avec_competences
        .coalesce(1)                    # un seul fichier en sortie
        .write.mode("overwrite")
        .option("compression", "snappy")
        .parquet(str(dossier_spark))
    )

    fichiers = sorted(dossier_spark.glob("part-*.parquet"))
    if len(fichiers) != 1:
        raise RuntimeError(f"Parquet attendu : 1 fichier, trouve {len(fichiers)}")

    lu = spark.read.parquet(str(dossier_spark))
    nb_unique = lu.count()
    nb_avec = lu.filter(F.size("competences_extraites") > 0).count()
    brut.unpersist()

    stats = {
        "offres_brutes": nb_brut,
        "doublons_supprimes": nb_brut - nb_unique,
        "offres_silver": nb_unique,
        "offres_avec_competence": nb_avec,
        "taille_parquet_ko": round(fichiers[0].stat().st_size / 1024, 1),
    }
    return fichiers[0], stats


def executer(date_execution, chemins_raw):
    """Point d'entree appele par le DAG.

    chemins_raw : {code_rome: chemin de l'objet dans le bucket raw},
    exactement ce que renvoie la tache collecte_vers_raw.
    """
    from storage import deposer_fichier, telecharger_fichier

    dossier = Path(tempfile.mkdtemp(prefix="spark_silver_"))
    spark = None
    try:
        fichiers = []
        for chemin in chemins_raw.values():
            local = dossier / "raw" / chemin
            local.parent.mkdir(parents=True, exist_ok=True)
            telecharger_fichier(BUCKET_RAW, chemin, local)
            fichiers.append(local)
        logger.info("%s fichiers bruts telecharges.", len(fichiers))

        spark = creer_session()
        parquet, stats = construire_silver(spark, fichiers, dossier / "sortie")

        destination = chemin_parquet_silver(date_execution)
        deposer_fichier(BUCKET_SILVER, destination, parquet)
        stats["chemin"] = f"s3://{BUCKET_SILVER}/{destination}"

        logger.info("Silver Parquet : %s", stats)
        return stats
    finally:
        if spark is not None:
            spark.stop()
        shutil.rmtree(dossier, ignore_errors=True)