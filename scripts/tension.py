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
    WHERE NOT hors_perimetre
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
      AND NOT f.hors_perimetre
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


# ---------------------------------------------------------------------------
# Application finale : indice de penurie par region et par ville
# ---------------------------------------------------------------------------
#
# Deux signaux de penurie, chacun lisse vers sa moyenne nationale :
#   - persistance : offre encore en ligne apres SEUIL_JOURS ;
#   - manque      : offre signalee par France Travail comme manquant de
#                   candidats (champ offresManqueCandidats).
# indice = moyenne des deux rapports a la moyenne : 1,00 = marche moyen,
# 1,30 = 30 % de signaux de penurie de plus que la moyenne nationale.

JOURS_RECENTS = 14   # offres affichees par defaut au candidat
SEUIL_FIABLE = 30    # offres, au-dela : resultat fiable
SEUIL_INDICATIF = 10 # offres, en dessous : resultat fragile
EVENEMENTS_MINIMUM = 3

REQUETE_OPPORTUNITE = """
WITH base AS (
    SELECT f.jours_en_ligne,
           COALESCE(f.manque_candidats, FALSE) AS manque,
           f.derniere_collecte,
           f.date_creation,
           l.ville_normalisee,
           l.departement,
           d.code_region,
           r.nom AS nom_region
    FROM fait_offre f
    JOIN dim_lieu l ON l.code_insee = f.code_insee
    JOIN ref_departement d ON d.departement = l.departement
    JOIN ref_region r ON r.code_region = d.code_region
    WHERE NOT f.hors_perimetre
),
maj AS (SELECT MAX(derniere_collecte) AS jour FROM fait_offre),
taux AS (
    SELECT AVG((jours_en_ligne > %(seuil)s)::int)::numeric AS taux_persistance,
           AVG(COALESCE(manque_candidats, FALSE)::int)::numeric AS taux_manque
    FROM fait_offre
    WHERE NOT hors_perimetre
),
-- Poids de la moyenne nationale : au moins %(lissage)s offres, et assez pour
-- contenir %(evenements)s signaux attendus (un signal rare ne doit pas
-- s'envoler parce qu'une ville de 2 offres en compte un).
reference AS (
    SELECT taux_persistance, taux_manque,
           GREATEST(%(lissage)s, %(evenements)s / NULLIF(taux_persistance, 0)) AS poids_p,
           GREATEST(%(lissage)s, %(evenements)s / NULLIF(taux_manque, 0)) AS poids_m
    FROM taux
),
territoires AS (
    SELECT 'region' AS niveau, b.code_region AS code, b.nom_region AS libelle,
           b.code_region,
           COUNT(*) AS nb_offres,
           COUNT(*) FILTER (WHERE b.jours_en_ligne > %(seuil)s) AS nb_persistantes,
           COUNT(*) FILTER (WHERE b.manque) AS nb_manque,
           COUNT(*) FILTER (WHERE b.derniere_collecte = m.jour) AS nb_en_ligne,
           COUNT(*) FILTER (WHERE b.derniere_collecte = m.jour
                            AND b.date_creation >= m.jour - %(recents)s) AS nb_recentes,
           PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY b.jours_en_ligne) AS mediane
    FROM base b CROSS JOIN maj m
    GROUP BY b.code_region, b.nom_region
    UNION ALL
    SELECT 'ville', b.ville_normalisee || '|' || b.departement,
           INITCAP(b.ville_normalisee), MIN(b.code_region),
           COUNT(*),
           COUNT(*) FILTER (WHERE b.jours_en_ligne > %(seuil)s),
           COUNT(*) FILTER (WHERE b.manque),
           COUNT(*) FILTER (WHERE b.derniere_collecte = m.jour),
           COUNT(*) FILTER (WHERE b.derniere_collecte = m.jour
                            AND b.date_creation >= m.jour - %(recents)s),
           PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY b.jours_en_ligne)
    FROM base b CROSS JOIN maj m
    WHERE b.ville_normalisee IS NOT NULL
    GROUP BY b.ville_normalisee, b.departement
)
INSERT INTO agg_opportunite (
    date_calcul, niveau, code, libelle, code_region, nb_offres,
    nb_persistantes, nb_manque, nb_en_ligne, nb_recentes, mediane_jours,
    indice_penurie, fiabilite
)
SELECT %(date_calcul)s, t.niveau, t.code, t.libelle, t.code_region, t.nb_offres,
       t.nb_persistantes, t.nb_manque, t.nb_en_ligne, t.nb_recentes,
       ROUND(t.mediane::numeric, 1),
       ROUND(CASE
           -- Aucune offre signalee "manque de candidats" : un seul signal.
           WHEN r.taux_manque = 0 THEN
               (t.nb_persistantes + r.poids_p * r.taux_persistance)
               / (t.nb_offres + r.poids_p) / NULLIF(r.taux_persistance, 0)
           ELSE (
               (t.nb_persistantes + r.poids_p * r.taux_persistance)
               / (t.nb_offres + r.poids_p) / NULLIF(r.taux_persistance, 0)
             + (t.nb_manque + r.poids_m * r.taux_manque)
               / (t.nb_offres + r.poids_m) / r.taux_manque
           ) / 2
       END, 4),
       CASE WHEN t.nb_offres >= %(fiable)s THEN 'fiable'
            WHEN t.nb_offres >= %(indicatif)s THEN 'indicatif'
            ELSE 'fragile' END
FROM territoires t CROSS JOIN reference r
ON CONFLICT (date_calcul, niveau, code) DO UPDATE SET
    libelle = EXCLUDED.libelle,
    code_region = EXCLUDED.code_region,
    nb_offres = EXCLUDED.nb_offres,
    nb_persistantes = EXCLUDED.nb_persistantes,
    nb_manque = EXCLUDED.nb_manque,
    nb_en_ligne = EXCLUDED.nb_en_ligne,
    nb_recentes = EXCLUDED.nb_recentes,
    mediane_jours = EXCLUDED.mediane_jours,
    indice_penurie = EXCLUDED.indice_penurie,
    fiabilite = EXCLUDED.fiabilite
"""


def calculer_opportunite(date_calcul):
    """Recalcule l'indice de penurie par region et par ville."""
    parametres = {
        "seuil": SEUIL_JOURS,
        "lissage": LISSAGE,
        "recents": JOURS_RECENTS,
        "fiable": SEUIL_FIABLE,
        "indicatif": SEUIL_INDICATIF,
        "evenements": EVENEMENTS_MINIMUM,
        "date_calcul": date_calcul,
    }

    with connexion() as conn, conn.cursor() as cur:
        cur.execute(REQUETE_OPPORTUNITE, parametres)
        cur.execute(
            """
            SELECT niveau, COUNT(*), COUNT(*) FILTER (WHERE fiabilite = 'fiable')
            FROM agg_opportunite WHERE date_calcul = %s GROUP BY niveau
            """,
            (date_calcul,),
        )
        stats = {
            f"{niveau}s": {"total": total, "fiables": fiables}
            for niveau, total, fiables in cur.fetchall()
        }

    logger.info("Indice de penurie : %s", stats)
    return stats


def top_territoires(date_calcul, niveau="ville", limite=10):
    """Territoires les plus en penurie, pour controle dans les logs."""
    with connexion() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT libelle, nb_offres, nb_persistantes, nb_manque,
                   nb_recentes, indice_penurie, fiabilite
            FROM agg_opportunite
            WHERE date_calcul = %s AND niveau = %s AND fiabilite <> 'fragile'
            ORDER BY indice_penurie DESC
            LIMIT %s
            """,
            (date_calcul, niveau, limite),
        )
        return cur.fetchall()