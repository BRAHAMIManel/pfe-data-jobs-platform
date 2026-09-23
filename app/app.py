"""
Application de restitution — detecteur de niches.

L'utilisateur declare ses competences ; l'application classe les couples
metier x departement ou son profil a le plus de chances.

Aucun calcul lourd ici : toute l'analyse est faite en amont par les DAG.
L'application interroge l'entrepot, elle ne le transforme pas.
"""

import os

import pandas as pd
import psycopg2
import streamlit as st

SEUIL_JOURS = 30
LISSAGE = 20

st.set_page_config(
    page_title="Detecteur de niches — marche de l'emploi IT",
    page_icon=":mag:",
    layout="wide",
)


@st.cache_resource
def connexion():
    return psycopg2.connect(
        host=os.getenv("DWH_HOST", "postgres-dwh"),
        port=os.getenv("DWH_PORT", "5432"),
        dbname=os.getenv("DWH_DB"),
        user=os.getenv("DWH_USER"),
        password=os.getenv("DWH_PASSWORD"),
    )


def lire(requete, parametres=None):
    with connexion().cursor() as cur:
        cur.execute(requete, parametres)
        colonnes = [d[0] for d in cur.description]
        return pd.DataFrame(cur.fetchall(), columns=colonnes)


@st.cache_data(ttl=600)
def liste_competences():
    return lire("""
        SELECT c.categorie, c.libelle, COUNT(*) AS nb
        FROM dim_competence c
        JOIN pont_offre_competence p ON p.id_competence = c.id_competence
        GROUP BY 1, 2 ORDER BY 1, 3 DESC
    """)


@st.cache_data(ttl=600)
def repere_marche():
    return lire("""
        SELECT COUNT(*) AS offres,
               ROUND(COUNT(*) FILTER (WHERE jours_en_ligne > %(s)s)::numeric
                     / NULLIF(COUNT(*), 0), 4) AS taux,
               MAX(derniere_collecte) AS maj
        FROM fait_offre
    """, {"s": SEUIL_JOURS})


REQUETE_CLASSEMENT = """
WITH selection AS (
    SELECT p.id_offre, COUNT(DISTINCT c.libelle) AS nb_correspondances
    FROM pont_offre_competence p
    JOIN dim_competence c ON c.id_competence = p.id_competence
    WHERE c.libelle = ANY(%(competences)s)
    GROUP BY 1
    HAVING COUNT(DISTINCT c.libelle) >= %(minimum_correspondances)s
),
reference AS (
    SELECT COUNT(*) FILTER (WHERE jours_en_ligne > %(seuil)s)::numeric
           / NULLIF(COUNT(*), 0) AS taux
    FROM fait_offre
),
agrege AS (
    SELECT m.libelle AS metier,
           l.departement,
           COUNT(*) AS offres,
           COUNT(*) FILTER (WHERE f.jours_en_ligne > %(seuil)s) AS persistantes,
           PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY f.jours_en_ligne)
               AS mediane_jours,
           ROUND(AVG(s.nb_correspondances), 1) AS correspondance_moyenne
    FROM fait_offre f
    JOIN selection s ON s.id_offre = f.id_offre
    JOIN dim_lieu l ON l.code_insee = f.code_insee
    JOIN dim_metier m ON m.code_rome = f.code_rome
    WHERE l.departement IS NOT NULL
    GROUP BY 1, 2
)
SELECT a.metier,
       a.departement,
       a.offres,
       a.persistantes,
       ROUND(a.mediane_jours::numeric, 0) AS mediane_jours,
       a.correspondance_moyenne,
       ROUND((a.persistantes + %(lissage)s * r.taux)
             / (a.offres + %(lissage)s), 3) AS score
FROM agrege a CROSS JOIN reference r
WHERE a.offres >= %(minimum_offres)s
ORDER BY score DESC
LIMIT 30
"""

REQUETE_OFFRES = """
SELECT f.intitule, l.ville, e.nom AS entreprise, f.date_creation,
       f.jours_en_ligne, ct.type_contrat
FROM fait_offre f
JOIN dim_lieu l ON l.code_insee = f.code_insee
LEFT JOIN dim_entreprise e ON e.id_entreprise = f.id_entreprise
LEFT JOIN dim_contrat ct ON ct.id_contrat = f.id_contrat
JOIN dim_metier m ON m.code_rome = f.code_rome
WHERE m.libelle = %(metier)s AND l.departement = %(departement)s
  AND f.id_offre IN (
      SELECT p.id_offre FROM pont_offre_competence p
      JOIN dim_competence c ON c.id_competence = p.id_competence
      WHERE c.libelle = ANY(%(competences)s)
  )
ORDER BY f.jours_en_ligne DESC
LIMIT 25
"""

# ---------------------------------------------------------------- interface

st.title("Ou votre profil a-t-il le plus de chances ?")
st.caption(
    "Le classement repose sur la persistance des offres : une annonce encore "
    "diffusee longtemps apres sa publication signale un poste que l'employeur "
    "peine a pourvoir."
)

repere = repere_marche().iloc[0]
c1, c2, c3 = st.columns(3)
c1.metric("Offres analysees", f"{repere['offres']:,}".replace(",", " "))
c2.metric(f"Encore en ligne apres {SEUIL_JOURS} j", f"{repere['taux']:.1%}")
c3.metric("Derniere collecte", str(repere["maj"]))

competences = liste_competences()

with st.sidebar:
    st.header("Votre profil")

    categories = sorted(competences["categorie"].unique())
    categorie = st.selectbox("Filtrer par categorie", ["Toutes"] + categories)

    disponibles = competences
    if categorie != "Toutes":
        disponibles = competences[competences["categorie"] == categorie]

    choisies = st.multiselect(
        "Vos competences",
        options=disponibles["libelle"].tolist(),
        help="Choisissez les technologies que vous maitrisez.",
    )

    st.divider()
    minimum_correspondances = st.slider(
        "Correspondances minimales par offre", 1, 5, 1,
        help="Nombre de vos competences que l'offre doit mentionner.",
    )
    minimum_offres = st.slider(
        "Offres minimales par territoire", 3, 30, 5,
        help="En dessous, l'echantillon est trop petit pour conclure.",
    )

if not choisies:
    st.info("Selectionnez au moins une competence dans le panneau de gauche.")
    st.stop()

parametres = {
    "competences": choisies,
    "minimum_correspondances": minimum_correspondances,
    "minimum_offres": minimum_offres,
    "seuil": SEUIL_JOURS,
    "lissage": LISSAGE,
}
classement = lire(REQUETE_CLASSEMENT, parametres)

if classement.empty:
    st.warning(
        "Aucun territoire ne remplit ces criteres. Baissez le nombre minimal "
        "d'offres ou de correspondances."
    )
    st.stop()

st.subheader("Territoires les plus favorables")
st.dataframe(
    classement.rename(columns={
        "metier": "Metier",
        "departement": "Dept",
        "offres": "Offres",
        "persistantes": "Non pourvues",
        "mediane_jours": "Mediane (j)",
        "correspondance_moyenne": "Corresp. moy.",
        "score": "Score",
    }),
    use_container_width=True,
    hide_index=True,
)

st.caption(
    "Le score est lisse vers la moyenne du marche : un territoire peu "
    "represente reste prudemment proche du taux de reference. La mediane "
    "complete le score — un score eleve avec une mediane faible signale "
    "quelques offres bloquees dans un flux qui se pourvoit vite."
)

st.divider()
st.subheader("Offres correspondantes")

ligne = st.selectbox(
    "Choisissez un couple metier / departement",
    options=range(len(classement)),
    format_func=lambda i: (
        f"{classement.iloc[i]['metier']} — dept {classement.iloc[i]['departement']} "
        f"(score {classement.iloc[i]['score']})"
    ),
)

offres = lire(REQUETE_OFFRES, {
    "metier": classement.iloc[ligne]["metier"],
    "departement": classement.iloc[ligne]["departement"],
    "competences": choisies,
})

st.dataframe(
    offres.rename(columns={
        "intitule": "Intitule",
        "ville": "Ville",
        "entreprise": "Entreprise",
        "date_creation": "Publiee le",
        "jours_en_ligne": "Jours en ligne",
        "type_contrat": "Contrat",
    }),
    use_container_width=True,
    hide_index=True,
)
