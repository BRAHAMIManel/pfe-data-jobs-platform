"""
Chargement dans l'entrepot PostgreSQL.

Toutes les ecritures sont idempotentes : rejouer un run ne cree pas de
doublon. C'est ce qui permet le suivi de duree de presence des offres.
"""

import logging
import os

import psycopg2
from psycopg2.extras import execute_values

logger = logging.getLogger(__name__)

CHEMIN_SCHEMA = "/opt/airflow/scripts/schema_etoile.sql"


def connexion():
    return psycopg2.connect(
        host=os.getenv("DWH_HOST", "postgres-dwh"),
        port=os.getenv("DWH_PORT", "5432"),
        dbname=os.getenv("DWH_DB"),
        user=os.getenv("DWH_USER"),
        password=os.getenv("DWH_PASSWORD"),
    )


def creer_schema():
    """Rejoue le DDL. Sans effet si les tables existent deja."""
    with open(CHEMIN_SCHEMA, encoding="utf-8") as fichier:
        ddl = fichier.read()

    with connexion() as conn, conn.cursor() as cur:
        cur.execute(ddl)
    logger.info("Schema en etoile verifie.")


def charger_dimensions(metiers, lieux, entreprises, contrats, dates, competences):
    """Insere les dimensions et renvoie les cles de substitution.

    Renvoie un dict avec les correspondances necessaires aux faits :
    {"entreprises": {(nom, secteur): id}, "contrats": {cle: id},
     "competences": {libelle: id}}
    """
    with connexion() as conn, conn.cursor() as cur:

        execute_values(cur, """
            INSERT INTO dim_metier (code_rome, libelle) VALUES %s
            ON CONFLICT (code_rome) DO UPDATE SET libelle = EXCLUDED.libelle
        """, metiers)

        execute_values(cur, """
            INSERT INTO dim_lieu
                (code_insee, ville, ville_normalisee, code_postal,
                 departement, latitude, longitude)
            VALUES %s
            ON CONFLICT (code_insee) DO UPDATE SET
                ville_normalisee = EXCLUDED.ville_normalisee
        """, lieux)

        execute_values(cur, """
            INSERT INTO dim_date (id_date, annee, mois, semaine, jour_semaine)
            VALUES %s ON CONFLICT (id_date) DO NOTHING
        """, dates)

        execute_values(cur, """
            INSERT INTO dim_entreprise (nom, secteur_libelle, tranche_effectif)
            VALUES %s ON CONFLICT (nom, secteur_libelle) DO NOTHING
        """, entreprises)

        execute_values(cur, """
            INSERT INTO dim_contrat
                (type_contrat, type_libelle, experience_exige, qualification, alternance)
            VALUES %s
            ON CONFLICT (type_contrat, experience_exige, qualification, alternance)
            DO NOTHING
        """, contrats)

        execute_values(cur, """
            INSERT INTO dim_competence (libelle, categorie) VALUES %s
            ON CONFLICT (libelle) DO NOTHING
        """, competences)

        cur.execute(
            "SELECT nom, secteur_libelle, id_entreprise FROM dim_entreprise"
        )
        cles_entreprises = {(n, s): i for n, s, i in cur.fetchall()}

        cur.execute("""
            SELECT type_contrat, experience_exige, qualification, alternance,
                   id_contrat FROM dim_contrat
        """)
        cles_contrats = {tuple(l[:4]): l[4] for l in cur.fetchall()}

        cur.execute("SELECT libelle, id_competence FROM dim_competence")
        cles_competences = dict(cur.fetchall())

    return {
        "entreprises": cles_entreprises,
        "contrats": cles_contrats,
        "competences": cles_competences,
    }


def charger_faits(faits):
    """Insere ou met a jour les offres.

    Offre nouvelle    -> premiere_collecte = derniere_collecte = aujourd'hui
    Offre deja connue -> derniere_collecte avance, jours_en_ligne recalcule

    C'est cette mesure de duree de presence qui alimentera le score de
    tension du detecteur de niches.
    """
    if not faits:
        return 0, 0

    with connexion() as conn, conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM fait_offre")
        avant = cur.fetchone()[0]

        execute_values(cur, """
            INSERT INTO fait_offre (
                id_offre, code_rome, code_insee, id_entreprise, id_contrat,
                date_creation, premiere_collecte, derniere_collecte,
                jours_en_ligne, nombre_postes, manque_candidats,
                salaire_min, salaire_max, salaire_periode, intitule, source
            ) VALUES %s
            ON CONFLICT (id_offre) DO UPDATE SET
                derniere_collecte = EXCLUDED.derniere_collecte,
                jours_en_ligne = EXCLUDED.derniere_collecte
                                 - COALESCE(fait_offre.date_creation,
                                            fait_offre.premiere_collecte),
                nombre_postes = EXCLUDED.nombre_postes,
                manque_candidats = EXCLUDED.manque_candidats
        """, faits)

        cur.execute("SELECT COUNT(*) FROM fait_offre")
        apres = cur.fetchone()[0]

    nouvelles = apres - avant
    return nouvelles, len(faits) - nouvelles


def charger_pont_competences(liens):
    """Associe offres et competences. (id_offre, id_competence)."""
    if not liens:
        return 0

    with connexion() as conn, conn.cursor() as cur:
        execute_values(cur, """
            INSERT INTO pont_offre_competence (id_offre, id_competence)
            VALUES %s ON CONFLICT DO NOTHING
        """, liens)
    return len(liens)