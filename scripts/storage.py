"""
Acces au Data Lake MinIO (compatible S3).

Une seule responsabilite : lire et ecrire des objets (JSON, Parquet)
dans les buckets.
"""

import io
import json
import logging
import os
from urllib.parse import urlparse

from minio import Minio
from minio.error import S3Error

logger = logging.getLogger(__name__)


def get_minio_client():
    """Construit un client a partir des variables d'environnement."""
    endpoint = os.getenv("MINIO_ENDPOINT", "http://minio:9000")
    parsed = urlparse(endpoint)

    return Minio(
        parsed.netloc,
        access_key=os.getenv("MINIO_ACCESS_KEY"),
        secret_key=os.getenv("MINIO_SECRET_KEY"),
        secure=(parsed.scheme == "https"),
    )


def ecrire_json(bucket, chemin_objet, donnees):
    """Ecrit un objet JSON dans un bucket. Cree le bucket s'il manque."""
    client = get_minio_client()

    if not client.bucket_exists(bucket):
        client.make_bucket(bucket)
        logger.info("Bucket %s cree.", bucket)

    contenu = json.dumps(donnees, ensure_ascii=False, indent=2).encode("utf-8")

    client.put_object(
        bucket,
        chemin_objet,
        data=io.BytesIO(contenu),
        length=len(contenu),
        content_type="application/json",
    )
    logger.info(
        "Ecrit s3://%s/%s (%.1f Ko)", bucket, chemin_objet, len(contenu) / 1024
    )
    return f"s3://{bucket}/{chemin_objet}"


def lire_json(bucket, chemin_objet):
    """Relit un objet JSON depuis un bucket."""
    client = get_minio_client()
    response = None
    try:
        response = client.get_object(bucket, chemin_objet)
        return json.loads(response.read().decode("utf-8"))
    finally:
        if response is not None:
            response.close()
            response.release_conn()


# ---------------------------------------------------------------------------
# Fichiers binaires (Parquet) : utilises par le job PySpark et par gold.
# ---------------------------------------------------------------------------

def objet_existe(bucket, chemin_objet):
    """True si l'objet existe dans le bucket."""
    client = get_minio_client()
    try:
        client.stat_object(bucket, chemin_objet)
        return True
    except S3Error as erreur:
        if erreur.code in ("NoSuchKey", "NoSuchBucket", "NoSuchObject"):
            return False
        raise


def telecharger_fichier(bucket, chemin_objet, chemin_local):
    """Copie un objet du Data Lake vers un fichier local."""
    get_minio_client().fget_object(bucket, chemin_objet, str(chemin_local))
    return chemin_local


def deposer_fichier(bucket, chemin_objet, chemin_local,
                    content_type="application/octet-stream"):
    """Envoie un fichier local dans un bucket. Cree le bucket s'il manque."""
    client = get_minio_client()
    if not client.bucket_exists(bucket):
        client.make_bucket(bucket)
        logger.info("Bucket %s cree.", bucket)

    client.fput_object(
        bucket, chemin_objet, str(chemin_local), content_type=content_type
    )
    taille = os.path.getsize(chemin_local)
    logger.info("Ecrit s3://%s/%s (%.1f Ko)", bucket, chemin_objet, taille / 1024)
    return f"s3://{bucket}/{chemin_objet}"


def lire_octets(bucket, chemin_objet):
    """Relit un objet tel quel, en octets (pour un fichier Parquet)."""
    client = get_minio_client()
    response = None
    try:
        response = client.get_object(bucket, chemin_objet)
        return response.read()
    finally:
        if response is not None:
            response.close()
            response.release_conn()

def lister_objets(bucket, prefixe=""):
    """Noms de tous les objets d'un bucket sous un prefixe."""
    client = get_minio_client()
    if not client.bucket_exists(bucket):
        return []
    return [o.object_name for o in client.list_objects(bucket, prefix=prefixe, recursive=True)]


def date_modification(bucket, chemin_objet):
    """Jour (UTC) ou l'objet a ete ecrit dans le Data Lake."""
    return get_minio_client().stat_object(bucket, chemin_objet).last_modified.date()