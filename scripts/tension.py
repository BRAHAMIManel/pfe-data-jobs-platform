"""
Detecteur de niches — calcul du score de tension.

Principe : une offre encore diffusee longtemps apres sa publication
signale un poste que l'employeur ne parvient pas a pourvoir. Le taux de
persistance (part des offres en ligne depuis plus de SEUIL_JOURS) sert
donc d'estimateur de la rarete des candidats.

Correction necessaire : un couple metier x departement comptant 3 offres
dont 2 persistantes afficherait 67 %, chiffre denue de sens. Le score est
donc lisse vers le taux de reference du marche, d'autant plus fortement
que l'effectif est faible :

    score = (persistantes + K x taux_reference) / (nb_offres + K)

Avec K = 20, un couple de 5 offres reste proche de la moyenne generale,
un couple de 200 offres exprime sa valeur propre. C'est un lissage
bayesien classique, equivalent a partir d'un a priori de K observations
au taux moyen.
"""

import logging

from dwh import connexion

logger = logging.getLogger(__name__)

SEUIL_JOURS = 30   # au-dela, une offre est consideree comme persistante
LISSAGE = 20       # poids de l'a priori, en nombre d'offres fictives

REQUETE_TENSION = """
WITH reference AS (
    SELECT COUNT(*) FILTER (WHERE jours_en_ligne > %(seuil)s)::numeric
           / NULLIF(COUNT(*), 0) AS taux
    FROM fait_offre
),
base AS (
    SELECT f.code_rome,
           l.departement,
           COUNT(*) AS nb_offres,
           COUNT(*) FILTER (WHERE f.jours_en_ligne > %(seuil)s) AS nb_persistantes,
           PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY f.jours_en_ligne)
               AS mediane_jours
    FROM fait_offre f
    JOIN dim_lieu l ON l.code_insee = f.code_insee
    WHERE l.departement IS NOT NULL
      AND f.code_rome IS NOT NULL
    GROUP BY 1, 2
)
INSERT INTO agg_tension (
    date_calcul, code_rome, departement, nb_offres, nb_persistantes,
    taux_brut, taux_reference, score, mediane_jours
)
SELECT
    %(date_calcul)s,
    b.code_rome,
    b.departement,
    b.nb_offres,
    b.nb_persistantes,
    ROUND(b.nb_persistantes::numeric / b.nb_offres, 4),
    ROUND(r.taux, 4),
    ROUND((b.nb_persistantes + %(lissage)s * r.taux)
          / (b.nb_offres + %(lissage)s), 4),
    ROUND(b.mediane_jours::numeric, 1)
FROM base b CROSS JOIN reference r
ON CONFLICT (date_calcul, code_rome, departement) DO UPDATE SET
    nb_offres = EXCLUDED.nb_offres,
    nb_persistantes = EXCLUDED.nb_persistantes,
    taux_brut = EXCLUDED.taux_brut,
    taux_reference = EXCLUDED.taux_reference,
    score = EXCLUDED.score,
    mediane_jours = EXCLUDED.mediane_jours
"""


def calculer_tension(date_calcul):
    """Recalcule l'agregat de tension pour la date donnee."""
    parametres = {
        "seuil": SEUIL_JOURS,
        "lissage": LISSAGE,
        "date_calcul": date_calcul,
    }

    with connexion() as conn, conn.cursor() as cur:
        cur.execute(REQUETE_TENSION, parametres)
        lignes = cur.rowcount

        cur.execute(
            """
            SELECT COUNT(*),
                   COUNT(*) FILTER (WHERE nb_offres >= 5),
                   MAX(taux_reference)
            FROM agg_tension WHERE date_calcul = %s
            """,
            (date_calcul,),
        )
        total, exploitables, reference = cur.fetchone()

    stats = {
        "couples_calcules": total,
        "couples_exploitables": exploitables,  # au moins 5 offres
        "taux_reference": float(reference) if reference else None,
        "lignes_ecrites": lignes,
    }
    logger.info("Agregat de tension : %s", stats)
    return stats


def top_niches(date_calcul, minimum_offres=5, limite=15):
    """Renvoie les couples les plus tendus, pour controle dans les logs."""
    with connexion() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT m.libelle, t.departement, t.nb_offres,
                   t.nb_persistantes, t.score, t.mediane_jours
            FROM agg_tension t
            JOIN dim_metier m ON m.code_rome = t.code_rome
            WHERE t.date_calcul = %s AND t.nb_offres >= %s
            ORDER BY t.score DESC
            LIMIT %s
            """,
            (date_calcul, minimum_offres, limite),
        )
        return cur.fetchall()
