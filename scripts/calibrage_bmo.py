"""
Calibrage des signaux de penurie sur l'enquete BMO 2026 de France Travail.

Question : parmi nos trois signaux (offres en ligne depuis plus de 30 jours,
"manque de candidats", postes republies apres retrait), lesquels suivent la
difficulte de recrutement declaree par les employeurs dans une enquete
officielle ? Les poids de l'indice de penurie en sont deduits, au lieu
d'etre choisis a la main.

Methode :
  1. Par departement (puis par region, pour illustrer), on calcule :
       - le taux de chaque signal sur nos offres informatiques ;
       - le taux BMO = projets difficiles / projets de recrutement, pour les
         6 metiers informatiques FAP2021 (seed dbt bmo_2026_informatique).
  2. Pour chaque signal, correlation de rang de Spearman avec le taux BMO.
     Spearman compare des classements : il ne suppose pas de lien lineaire
     et resiste aux valeurs extremes.
  3. Incertitude : intervalle a 95 % par bootstrap (1 000 tirages des
     departements avec remise).
  4. Poids proposes = correlations positives, ramenees a une somme de 1.
     Un signal sans lien (ou en sens contraire) recoit un poids nul.

Lecture seule. Lancement :
    docker compose exec airflow-scheduler python /opt/airflow/scripts/calibrage_bmo.py

Prerequis : dbt a tourne (tables analytique.mart_offres_candidat et
analytique_referentiels.bmo_2026_informatique).
"""

import os
import sys
from datetime import datetime

import numpy as np
import pandas as pd
import psycopg2

DOSSIER_RAPPORTS = "/opt/airflow/logs/rapports"
SEUIL_JOURS = 30          # meme seuil que l'application
MIN_OFFRES = 30           # un departement compte s'il a au moins 30 offres...
MIN_PROJETS = 20          # ... et au moins 20 projets BMO
TIRAGES = 1000
SIGNAUX = {
    "persistance": "Offres en ligne depuis plus de 30 jours",
    "manque": "Signalees « manque de candidats »",
    "republication": "Republiees apres retrait",
}

OFFRES = f"""
    SELECT departement, code_region, region,
           (jours_en_ligne > {SEUIL_JOURS})::int  AS persistance,
           manque::int                            AS manque,
           republication::int                     AS republication
    FROM analytique.mart_offres_candidat
"""

BMO = """
    SELECT b.departement, d.code_region, r.nom AS region,
           SUM(b.projets) AS projets, SUM(b.difficiles) AS difficiles
    FROM analytique_referentiels.bmo_2026_informatique b
    LEFT JOIN public.ref_departement d ON d.departement = b.departement
    LEFT JOIN public.ref_region r      ON r.code_region = d.code_region
    GROUP BY b.departement, d.code_region, r.nom
"""


def lire(cur, requete):
    cur.execute(requete)
    return pd.DataFrame(cur.fetchall(), columns=[c.name for c in cur.description])


def spearman(x, y):
    """Correlation de rang (Pearson sur les rangs), sans scipy."""
    if len(x) < 3 or x.nunique() < 2 or y.nunique() < 2:
        return np.nan
    return float(x.rank().corr(y.rank()))


def intervalle(x, y, graine=2026):
    """Intervalle a 95 % de Spearman par bootstrap."""
    gen = np.random.default_rng(graine)
    n = len(x)
    valeurs = []
    for _ in range(TIRAGES):
        i = gen.integers(0, n, n)
        r = spearman(x.iloc[i].reset_index(drop=True), y.iloc[i].reset_index(drop=True))
        if not np.isnan(r):
            valeurs.append(r)
    if not valeurs:
        return np.nan, np.nan
    return float(np.percentile(valeurs, 2.5)), float(np.percentile(valeurs, 97.5))


def table_territoires(offres, bmo, cle):
    """Taux des signaux et taux BMO par territoire (departement ou region)."""
    g = offres.groupby(cle)
    t = pd.DataFrame({"offres": g.size()})
    for s in SIGNAUX:
        t[s] = g[s].mean()
    b = bmo.groupby(cle)[["projets", "difficiles"]].sum()
    t = t.join(b, how="inner")
    t["bmo"] = t["difficiles"] / t["projets"]
    return t[(t["offres"] >= MIN_OFFRES) & (t["projets"] >= MIN_PROJETS)]


def indice(t, poids, nationaux):
    """Indice composite : moyenne ponderee des taux rapportes au national."""
    total = sum(poids.values())
    return sum(p * t[s] / nationaux[s] for s, p in poids.items() if p > 0 and nationaux[s] > 0) / total


def tableau(lignes, entetes):
    sortie = ["| " + " | ".join(entetes) + " |", "| " + " | ".join("---" for _ in entetes) + " |"]
    sortie += ["| " + " | ".join(str(v) for v in l) + " |" for l in lignes]
    return "\n".join(sortie)


def calibrer(offres, bmo):
    sortie = []
    ecrire = sortie.append
    nationaux = {s: float(offres[s].mean()) for s in SIGNAUX}

    ecrire("# Calibrage des signaux de penurie sur l'enquete BMO 2026\n")
    ecrire(f"Genere le {datetime.now():%d/%m/%Y a %H:%M}.\n")
    ecrire("Reference : enquete Besoins en Main-d'Oeuvre 2026 (France Travail), 6 metiers "
           "informatiques FAP2021. Taux BMO = projets de recrutement juges difficiles / projets.\n")
    ecrire(f"Offres informatiques analysees : **{len(offres)}**. Taux nationaux : "
           + ", ".join(f"{SIGNAUX[s].lower()} {nationaux[s]:.1%}" for s in SIGNAUX) + ".\n")

    dep = table_territoires(offres, bmo, "departement")
    ecrire(f"## 1. Par departement ({len(dep)} departements avec au moins {MIN_OFFRES} offres "
           f"et {MIN_PROJETS} projets BMO)\n")
    lignes, correlations, etablis = [], {}, []
    for s, libelle in SIGNAUX.items():
        r = spearman(dep[s], dep["bmo"])
        bas, haut = intervalle(dep[s], dep["bmo"])
        correlations[s] = r
        if not np.isnan(bas) and bas > 0:
            etablis.append(SIGNAUX[s])
        lignes.append([libelle, f"{r:+.2f}" if not np.isnan(r) else "—",
                       f"[{bas:+.2f} ; {haut:+.2f}]" if not np.isnan(bas) else "—"])
    ecrire(tableau(lignes, ["Signal", "Spearman avec BMO", "Intervalle 95 %"]))
    ecrire("\nLecture : +1 = meme classement des departements que BMO, 0 = aucun lien, "
           "negatif = classement oppose. Si l'intervalle contient 0, le lien n'est pas etabli.\n")

    # Poids proposes : correlations positives normalisees.
    positives = {s: max(0.0, r) if not np.isnan(r) else 0.0 for s, r in correlations.items()}
    somme = sum(positives.values())
    egaux = {s: 1 / 3 for s in SIGNAUX}
    proposes = {s: v / somme for s, v in positives.items()} if somme > 0 else egaux

    ecrire("## 2. Poids proposes pour l'indice de penurie\n")
    ecrire(tableau(
        [[SIGNAUX[s], f"{egaux[s]:.0%}", f"{proposes[s]:.0%}"] for s in SIGNAUX],
        ["Signal", "Poids actuels", "Poids calibres"],
    ))
    r_egaux = spearman(indice(dep, egaux, nationaux), dep["bmo"])
    r_proposes = spearman(indice(dep, proposes, nationaux), dep["bmo"])
    ecrire(f"\nIndice avec les poids actuels : Spearman **{r_egaux:+.2f}** avec BMO. "
           f"Avec les poids calibres : **{r_proposes:+.2f}**.\n")
    if etablis:
        ecrire("Signaux dont le lien avec BMO est etabli (intervalle entierement positif) : **"
               + ", ".join(etablis) + "**.\n")
    else:
        ecrire("**Aucun intervalle n'est entierement positif** : les poids calibres sont "
               "indicatifs. A presenter comme une tendance, a confirmer avec plus d'historique.\n")
    if somme == 0:
        ecrire("**Aucun signal n'est lie positivement a BMO** : les poids restent egaux, "
               "et la penurie doit etre presentee comme exploratoire.\n")
    ecrire("A recopier dans app/calculs.py :\n")
    ecrire("```python\nPOIDS_SIGNAUX = {"
           + ", ".join(f'"{s}": {proposes[s]:.2f}' for s in SIGNAUX) + "}\n```\n")

    reg = table_territoires(offres, bmo, "region")
    ecrire(f"## 3. Par region, pour illustrer ({len(reg)} regions)\n")
    reg = reg.assign(indice=indice(reg, proposes, nationaux)).sort_values("bmo", ascending=False)
    ecrire(tableau(
        [[i, int(l.offres), f"{l.bmo:.0%}", f"{l.persistance:.1%}", f"{l.manque:.1%}",
          f"{l.republication:.1%}", f"{l.indice:.2f}"] for i, l in reg.iterrows()],
        ["Region", "Offres", "BMO difficiles", "Persistance", "Manque", "Republication", "Indice calibre"],
    ))
    ecrire("\n## 4. Limites a garder en tete\n")
    ecrire("- BMO mesure des **intentions d'embauche declarees** pour l'annee ; nos signaux viennent "
           "d'**offres reelles** sur quelques semaines. Une correlation moderee est attendue.")
    ecrire("- Le secret statistique masque les petites cellules BMO (10 % des projets).")
    ecrire(f"- Peu de territoires : {len(dep)} departements, d'ou des intervalles larges. "
           "A refaire quand la collecte quotidienne aura plus d'historique.\n")
    return "\n".join(sortie) + "\n", proposes


def main():
    with psycopg2.connect(
        host=os.getenv("DWH_HOST", "postgres-dwh"),
        port=os.getenv("DWH_PORT", "5432"),
        dbname=os.getenv("DWH_DB"),
        user=os.getenv("DWH_USER"),
        password=os.getenv("DWH_PASSWORD"),
    ) as conn, conn.cursor() as cur:
        offres = lire(cur, OFFRES)
        bmo = lire(cur, BMO)

    texte, _ = calibrer(offres, bmo)
    print(texte)
    try:
        os.makedirs(DOSSIER_RAPPORTS, exist_ok=True)
        chemin = os.path.join(DOSSIER_RAPPORTS, f"calibrage_bmo_{datetime.now():%Y-%m-%d_%Hh%M}.md")
        with open(chemin, "w", encoding="utf-8") as fichier:
            fichier.write(texte)
        print(f"Rapport enregistre : {chemin}", file=sys.stderr)
    except OSError as erreur:
        print(f"Rapport non enregistre ({erreur}).", file=sys.stderr)


if __name__ == "__main__":
    main()