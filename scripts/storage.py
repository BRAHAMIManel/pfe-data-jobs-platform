"""
Acces au Data Lake MinIO (compatible S3).

Une seule responsabilite : lire et ecrire du JSON dans les buckets.
"""

import io
import json
import logging
import os
from urllib.parse import urlparse

from minio import Minio

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
