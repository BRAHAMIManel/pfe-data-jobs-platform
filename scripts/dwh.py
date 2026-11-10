"""
Chargement dans l'entrepot PostgreSQL.

Toutes les ecritures sont idempotentes : rejouer un run ne cree pas de
doublon. C'est ce qui permet le suivi de duree de presence des offres.
"""

import json
import logging
import os

import psycopg2
from psycopg2.extras import execute_values

logger = logging.getLogger(__name__)

DOSSIER_SCRIPTS = os.path.dirname(os.path.abspath(__file__))
CHEMIN_SCHEMA = os.path.join(DOSSIER_SCRIPTS, "schema_etoile.sql")
CHEMIN_REGIONS = os.path.join(DOSSIER_SCRIPTS, "regions.json")


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


def reparer_dates_collecte():
    """Remet dans l'ordre les offres dont premiere_collecte > derniere_collecte.

    Ces lignes viennent de l'ancienne regle de chargement (voir
    charger_faits). On echange les deux dates et on recalcule la duree.
    Sans effet quand tout est en ordre : peut tourner a chaque chargement.
    """
    with connexion() as conn, conn.cursor() as cur:
        cur.execute("""
            UPDATE fait_offre SET
                premiere_collecte = derniere_collecte,
                derniere_collecte = premiere_collecte,
                jours_en_ligne = premiere_collecte
                                 - COALESCE(date_creation, derniere_collecte)
            WHERE premiere_collecte > derniere_collecte
        """)
        reparees = cur.rowcount
    if reparees:
        logger.warning("%s offres avaient leurs dates de collecte inversees : reparees.", reparees)
    return reparees


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

    Offre nouvelle    -> premiere_collecte = derniere_collecte = date de collecte
    Offre deja connue -> derniere_collecte avance, jours_en_ligne recalcule

    Les dates ne peuvent qu'aller dans le bon sens : premiere_collecte ne
    fait que reculer (LEAST), derniere_collecte ne fait qu'avancer
    (GREATEST). Recharger une ancienne journee ne remonte donc jamais le
    temps, et l'etat le plus recent de l'offre (manque de candidats,
    nombre de postes) n'est pas ecrase par un etat plus ancien.
    Bug corrige le 10/11, trouve par le test dbt assert_collecte_dans_l_ordre.

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
                salaire_min, salaire_max, salaire_periode, intitule, source,
                url_offre, experience_annees, id_poste
            ) VALUES %s
            ON CONFLICT (id_offre) DO UPDATE SET
                url_offre = EXCLUDED.url_offre,
                experience_annees = EXCLUDED.experience_annees,
                id_poste = EXCLUDED.id_poste,
                premiere_collecte = LEAST(fait_offre.premiere_collecte,
                                          EXCLUDED.premiere_collecte),
                derniere_collecte = GREATEST(fait_offre.derniere_collecte,
                                             EXCLUDED.derniere_collecte),
                jours_en_ligne = GREATEST(fait_offre.derniere_collecte,
                                          EXCLUDED.derniere_collecte)
                                 - COALESCE(fait_offre.date_creation,
                                            LEAST(fait_offre.premiere_collecte,
                                                  EXCLUDED.premiere_collecte)),
                nombre_postes = CASE
                    WHEN EXCLUDED.derniere_collecte >= fait_offre.derniere_collecte
                    THEN EXCLUDED.nombre_postes ELSE fait_offre.nombre_postes END,
                manque_candidats = CASE
                    WHEN EXCLUDED.derniere_collecte >= fait_offre.derniere_collecte
                    THEN EXCLUDED.manque_candidats ELSE fait_offre.manque_candidats END
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

def charger_referentiels(familles):
    """Charge les regions et les familles de postes. Idempotent.

    familles : [(id_poste, libelle, categorie), ...] depuis scripts/postes.json.
    """
    with open(CHEMIN_REGIONS, encoding="utf-8") as fichier:
        geo = json.load(fichier)

    regions = [
        (code, r["nom"], r["abrev"],
         r["grille"][0] if r["grille"] else None,
         r["grille"][1] if r["grille"] else None)
        for code, r in geo["regions"].items()
    ]
    departements = list(geo["departements"].items())

    with connexion() as conn, conn.cursor() as cur:
        execute_values(cur, """
            INSERT INTO ref_region (code_region, nom, abrev, grille_ligne, grille_col)
            VALUES %s ON CONFLICT (code_region) DO UPDATE SET
                nom = EXCLUDED.nom, abrev = EXCLUDED.abrev,
                grille_ligne = EXCLUDED.grille_ligne, grille_col = EXCLUDED.grille_col
        """, regions)
        execute_values(cur, """
            INSERT INTO ref_departement (departement, code_region) VALUES %s
            ON CONFLICT (departement) DO UPDATE SET code_region = EXCLUDED.code_region
        """, departements)
        execute_values(cur, """
            INSERT INTO dim_poste (id_poste, libelle, categorie) VALUES %s
            ON CONFLICT (id_poste) DO UPDATE SET
                libelle = EXCLUDED.libelle, categorie = EXCLUDED.categorie
        """, familles)

    logger.info(
        "Referentiels : %s regions, %s departements, %s familles de postes.",
        len(regions), len(departements), len(familles),
    )


def completer_offres_anciennes(classer_poste, url_france_travail, est_hors_perimetre):
    """Complete et reclasse les offres deja presentes dans l'entrepot.

    Les offres encore en ligne sont mises a jour par le chargement du jour.
    Celles qui ont disparu n'y repassent jamais : on leur ajoute ici leur
    lien, et on reclasse TOUTES les offres dans les postes, pour que la
    moindre modification de postes.json s'applique aussi a l'historique.
    """
    with connexion() as conn, conn.cursor() as cur:
        cur.execute("""
            UPDATE fait_offre SET url_offre = %s || id_offre
            WHERE url_offre IS NULL AND source = 'france_travail'
        """, (url_france_travail,))
        liens = cur.rowcount

        cur.execute(
            "SELECT id_offre, intitule, id_poste, hors_perimetre FROM fait_offre"
        )
        a_classer = []
        for id_offre, intitule, poste_actuel, hors_actuel in cur.fetchall():
            poste = classer_poste(intitule)
            hors = est_hors_perimetre(intitule)
            if poste != poste_actuel or hors != hors_actuel:
                a_classer.append((poste, hors, id_offre))
        if a_classer:
            execute_values(cur, """
                UPDATE fait_offre f
                SET id_poste = v.id_poste, hors_perimetre = v.hors
                FROM (VALUES %s) AS v(id_poste, hors, id_offre)
                WHERE f.id_offre = v.id_offre
            """, a_classer)
        cur.execute("SELECT COUNT(*) FROM fait_offre WHERE hors_perimetre")
        hors_perimetre = cur.fetchone()[0]

    logger.info(
        "Offres completees : %s liens ajoutes, %s offres (re)classees, "
        "%s offres hors perimetre (exclues des analyses).",
        liens, len(a_classer), hors_perimetre,
    )
    return {
        "liens_ajoutes": liens,
        "offres_reclassees": len(a_classer),
        "offres_hors_perimetre": hors_perimetre,
    }