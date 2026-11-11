"""
Analyse de sensibilite des poids du score d'opportunite.

Question du jury : « et si vous changiez les poids 45 / 35 / 20 ? ».
On recalcule le classement des regions et des villes avec plusieurs jeux de
poids, pour trois profils types, et on mesure ce qui change :
  - correlation de rang de Spearman avec le classement de reference
    (1 = meme ordre, 0 = aucun rapport) ;
  - nombre de territoires communs dans le top 5 (regions) / top 10 (villes).
Si le classement bouge peu, les poids ne decident pas du resultat a eux
seuls : le choix 45 / 35 / 20 n'est pas determinant.

Utilise exactement le calcul de l'application (app/calculs.py). Lecture
seule. Lancement, dans le conteneur de l'application :
    docker compose exec app python /scripts/sensibilite_poids.py
"""

import os
import sys
from datetime import datetime

import pandas as pd
import psycopg2

sys.path.insert(0, os.getenv("CHEMIN_APP", "/app"))
import calculs as c  # noqa: E402

REFERENCE = "Référence 45 / 35 / 20"
VARIANTES = {
    REFERENCE: {"penurie": 0.45, "adequation": 0.35, "volume": 0.20},
    "Poids égaux 33 / 33 / 33": {"penurie": 1 / 3, "adequation": 1 / 3, "volume": 1 / 3},
    "Tension forte 60 / 25 / 15": {"penurie": 0.60, "adequation": 0.25, "volume": 0.15},
    "Adéquation forte 30 / 50 / 20": {"penurie": 0.30, "adequation": 0.50, "volume": 0.20},
    "Volume fort 35 / 30 / 35": {"penurie": 0.35, "adequation": 0.30, "volume": 0.35},
    "Sans volume 55 / 45 / 0": {"penurie": 0.55, "adequation": 0.45, "volume": 0.0},
}

# Trois profils types, avec les noms de competences du dictionnaire.
PROFILS = {
    "Data Engineer junior (1 an)": (
        ["Python", "SQL", "Spark", "Airflow", "Docker", "PostgreSQL", "Git"], 1, ["de"]),
    "Développeur web (2 ans)": (
        ["JavaScript", "TypeScript", "React", "Node.js", "HTML", "CSS", "Git", "SQL"], 2, ["web"]),
    "Technicien support (1 an)": (
        ["Active Directory", "Office 365", "ITIL", "TCP/IP", "Linux"], 1, ["support", "sys"]),
}

REQUETE = "SELECT * FROM analytique.mart_offres_candidat"


def spearman(a, b):
    return float(a.rank().corr(b.rank())) if len(a) >= 3 else float("nan")


def classements(offres, refs, poids, niveau, minimum):
    c.POIDS = poids
    t = c.noter_territoires(offres, niveau, refs)
    if t.empty:
        return pd.Series(dtype=float)
    t = t[t["offres"] >= minimum]
    return t.set_index("code")["score"]


def analyser(offres_brutes):
    offres = c.preparer_offres(offres_brutes)
    refs = c.references(offres)
    lignes = []
    for profil, (competences, annees, postes) in PROFILS.items():
        evaluees = c.evaluer_offres(offres, competences, annees)
        perim = c.perimetre(evaluees, postes, "Tous", {"mode": "france"})
        for niveau, minimum, top in (("region", c.SEUIL_INDICATIF, 5), ("ville", c.SEUIL_INDICATIF, 10)):
            ref = classements(perim, refs, VARIANTES[REFERENCE], niveau, minimum)
            if len(ref) < 3:
                continue
            top_ref = set(ref.sort_values(ascending=False).head(top).index)
            for nom, poids in VARIANTES.items():
                if nom == REFERENCE:
                    continue
                autre = classements(perim, refs, poids, niveau, minimum).reindex(ref.index)
                top_autre = set(autre.sort_values(ascending=False).head(top).index)
                lignes.append({
                    "profil": profil, "niveau": "Régions" if niveau == "region" else "Villes",
                    "territoires": len(ref), "variante": nom,
                    "spearman": spearman(ref, autre),
                    "top": f"{len(top_ref & top_autre)} / {min(top, len(ref))}",
                })
    c.POIDS = VARIANTES[REFERENCE]
    return pd.DataFrame(lignes)


def rapport(resultats):
    sortie = ["# Sensibilité des poids du score d'opportunité", "",
              f"Généré le {datetime.now():%d/%m/%Y à %H:%M}. Référence : 45 % tension, "
              "35 % adéquation, 20 % volume. Territoires d'au moins "
              f"{c.SEUIL_INDICATIF} offres compatibles.", ""]
    if resultats.empty:
        return "\n".join(sortie + ["Pas assez de territoires pour l'analyse."]) + "\n"

    synthese = resultats.groupby("variante")["spearman"].agg(["mean", "min"]).sort_values("mean")
    sortie += ["## Synthèse : la référence comparée à chaque variante", "",
               "| Variante | Spearman moyen | Spearman le plus bas |", "| --- | --- | --- |"]
    sortie += [f"| {v} | {r['mean']:.2f} | {r['min']:.2f} |" for v, r in synthese.iterrows()]
    moyenne = resultats["spearman"].mean()
    verdict = ("**Classement stable** : changer les poids modifie peu l'ordre des territoires."
               if moyenne >= 0.8 else
               "**Classement sensible** : l'ordre dépend en partie des poids ; à présenter comme "
               "un choix assumé, et laisser l'utilisateur ajuster serait une piste.")
    sortie += ["", f"Spearman moyen, toutes variantes : **{moyenne:.2f}**. {verdict}", ""]

    sortie += ["## Détail par profil", "",
               "| Profil | Niveau | Territoires | Variante | Spearman | Top communs |",
               "| --- | --- | --- | --- | --- | --- |"]
    sortie += [f"| {r.profil} | {r.niveau} | {r.territoires} | {r.variante} | {r.spearman:.2f} | {r.top} |"
               for r in resultats.itertuples()]
    sortie += ["", "Lecture : Spearman 1 = même classement que la référence. « Top communs » = "
               "territoires présents à la fois dans le top de la référence et dans celui de la variante."]
    return "\n".join(sortie) + "\n"


def main():
    with psycopg2.connect(
        host=os.getenv("DWH_HOST", "postgres-dwh"), port=os.getenv("DWH_PORT", "5432"),
        dbname=os.getenv("DWH_DB"), user=os.getenv("DWH_USER"), password=os.getenv("DWH_PASSWORD"),
    ) as conn, conn.cursor() as cur:
        cur.execute(REQUETE)
        brutes = pd.DataFrame(cur.fetchall(), columns=[d.name for d in cur.description])
    print(rapport(analyser(brutes)))


if __name__ == "__main__":
    main()