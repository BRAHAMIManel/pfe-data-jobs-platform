"""
Mesure des signaux de penurie : a lancer AVANT de changer le calcul.

Questions auxquelles il repond (lecture seule, rien n'est modifie) :
  1. Combien d'offres ont un nom d'entreprise ? Sans nom, impossible de
     reperer une republication.
  2. Combien de temps vivent les offres qui ont disparu ? Un pic autour de
     21 jours trahirait les offres publiees 3 semaines pour une demande
     d'autorisation de travail (article R5221-20 du Code du travail).
  3. Combien de postes sont republies (meme entreprise, meme intitule,
     meme ville, nouvelle offre au moins 14 jours apres) ?
  4. Qui republie le plus ? (reperer les ESN et cabinets qui republient
     des annonces modeles en continu)
  5. Republications et persistance racontent-elles la meme histoire par
     region ?
  6. Quels types de contrat ? (part des offres freelance / liberales)

Lancement, depuis le dossier du projet :
    docker compose exec airflow-scheduler python /opt/airflow/scripts/mesure_signaux.py

Le resultat s'affiche et est enregistre dans logs/rapports/.
"""

import os
import sys
from datetime import datetime

import pandas as pd
import psycopg2

DOSSIER_RAPPORTS = "/opt/airflow/logs/rapports"
ECART_REPUBLICATION = 14   # jours minimum entre deux publications du meme poste
SEUIL_PERSISTANCE = 30     # jours : le seuil actuel du calcul

# Intitule comparable : minuscules, sans accents, sans "(H/F)", espaces reduits.
INTITULE_NORMALISE = r"""
    trim(regexp_replace(
        regexp_replace(
            translate(lower(f.intitule),
                      'àâäéèêëîïôöùûüç', 'aaaeeeeiioouuuc'),
            '\(?\s*(h\s*/\s*f|f\s*/\s*h)\s*\)?', '', 'g'),
        '\s+', ' ', 'g'))
"""

# Offres du perimetre informatique, une ligne par offre, avec leur cle de
# republication : entreprise + intitule normalise + commune.
OFFRES = f"""
    SELECT
        f.id_offre,
        f.id_entreprise,
        e.nom                     AS entreprise,
        {INTITULE_NORMALISE}      AS intitule,
        f.code_insee,
        d.code_region,
        r.nom                     AS region,
        f.date_creation,
        f.premiere_collecte,
        f.derniere_collecte,
        f.jours_en_ligne,
        COALESCE(f.manque_candidats, FALSE) AS manque,
        c.type_contrat,
        c.type_libelle
    FROM fait_offre f
    LEFT JOIN dim_entreprise e  ON e.id_entreprise = f.id_entreprise
    LEFT JOIN dim_lieu l        ON l.code_insee = f.code_insee
    LEFT JOIN ref_departement d ON d.departement = l.departement
    LEFT JOIN ref_region r      ON r.code_region = d.code_region
    LEFT JOIN dim_contrat c     ON c.id_contrat = f.id_contrat
    WHERE NOT f.hors_perimetre
"""


def pct(part, total):
    return f"{100 * part / total:.1f} %" if total else "—"


def tableau(df):
    """DataFrame -> tableau Markdown."""
    if df.empty:
        return "_Aucune donnee._"
    lignes = ["| " + " | ".join(map(str, df.columns)) + " |",
              "| " + " | ".join("---" for _ in df.columns) + " |"]
    for valeurs in df.itertuples(index=False):
        lignes.append("| " + " | ".join(str(v) for v in valeurs) + " |")
    return "\n".join(lignes)


def republications(offres):
    """Offres qui republient un poste deja vu.

    Une offre B republie l'offre A si elles ont la meme entreprise, le meme
    intitule normalise et la meme commune, et si B a ete publiee au moins
    14 jours apres A. Les publications le meme jour (plusieurs postes
    identiques) ne comptent pas. "Apres retrait" : A avait disparu des
    collectes quand B est apparue, le cas le plus net.
    """
    avec_cle = offres.dropna(subset=["id_entreprise", "intitule", "code_insee", "date_creation"])
    avec_cle = avec_cle[avec_cle["intitule"] != ""]
    cle = ["id_entreprise", "intitule", "code_insee"]

    groupes = avec_cle.groupby(cle)
    lignes = []
    for _, g in groupes:
        if len(g) < 2:
            continue
        g = g.sort_values("date_creation")
        premiere = g.iloc[0]
        for _, b in g.iloc[1:].iterrows():
            ecart = (b["date_creation"] - premiere["date_creation"]).days
            if ecart >= ECART_REPUBLICATION:
                lignes.append({
                    "id_offre": b["id_offre"],
                    "entreprise": b["entreprise"],
                    "region": b["region"],
                    "ecart_jours": ecart,
                    "apres_retrait": b["premiere_collecte"] > premiere["derniere_collecte"],
                })
    return avec_cle, pd.DataFrame(
        lignes, columns=["id_offre", "entreprise", "region", "ecart_jours", "apres_retrait"]
    )


def mesurer(offres):
    """Construit le rapport Markdown a partir des offres."""
    for col in ("date_creation", "premiere_collecte", "derniere_collecte"):
        offres[col] = pd.to_datetime(offres[col])

    sortie = []
    ecrire = sortie.append
    n = len(offres)
    derniere = offres["derniere_collecte"].max()
    premiere = offres["premiere_collecte"].min()
    jours_collecte = len(set(offres["premiere_collecte"]) | set(offres["derniere_collecte"]))
    en_ligne = offres["derniere_collecte"] == derniere

    ecrire("# Mesure des signaux de penurie — Detecteur de niches IT\n")
    ecrire(f"Genere le {datetime.now():%d/%m/%Y a %H:%M}. Offres du perimetre IT uniquement.\n")
    ecrire("## 0. Base de mesure\n")
    ecrire(f"- Offres : **{n}** ; encore en ligne a la derniere collecte : {en_ligne.sum()} ; disparues : {(~en_ligne).sum()}")
    ecrire(f"- Collectes observees : {jours_collecte} jours, du {premiere:%d/%m/%Y} au {derniere:%d/%m/%Y}")
    ecrire(f"- Offres signalees « manque de candidats » : {offres['manque'].sum()} ({pct(offres['manque'].sum(), n)})\n")

    # 1. Couverture entreprise
    avec_nom = offres["id_entreprise"].notna().sum()
    ecrire("## 1. Offres avec un nom d'entreprise\n")
    ecrire(f"**{avec_nom} sur {n} ({pct(avec_nom, n)})**. Les autres sont anonymes : "
           "une republication ne peut pas y etre reperee.\n")

    # 2. Duree de vie des offres disparues, observees depuis leur publication
    ecrire("## 2. Duree de vie des offres disparues\n")
    observees = offres[(~en_ligne) & (offres["date_creation"] >= premiere)].copy()
    observees["duree"] = (observees["derniere_collecte"] - observees["date_creation"]).dt.days
    tranches = [-1, 7, 14, 20, 27, 34, 45, 10_000]
    noms = ["0-7 j", "8-14 j", "15-20 j", "21-27 j", "28-34 j", "35-45 j", "plus de 45 j"]
    repartition = (
        pd.cut(observees["duree"], tranches, labels=noms).value_counts().reindex(noms).fillna(0).astype(int)
    )
    total_obs = int(repartition.sum())
    ecrire(f"Offres publiees apres le debut de la collecte puis disparues : **{total_obs}**. "
           "Duree = derniere collecte - date de publication.\n")
    ecrire(tableau(pd.DataFrame({
        "Duree de vie": noms,
        "Offres": repartition.values,
        "Part": [pct(v, total_obs) for v in repartition.values],
    })))
    ecrire("\nLecture : un pic dans la tranche 21-27 j est la trace possible des offres "
           "publiees 3 semaines pour une demande d'autorisation de travail.\n")

    # 3. Republications
    avec_cle, rep = republications(offres)
    ecrire("## 3. Republications\n")
    ecrire(f"Regle : meme entreprise, meme intitule (sans accents ni « H/F »), meme commune, "
           f"nouvelle offre publiee au moins {ECART_REPUBLICATION} jours apres la premiere.\n")
    nb_rep = len(rep)
    apres_retrait = int(rep["apres_retrait"].sum()) if nb_rep else 0
    ecrire(f"- Offres comparables (avec entreprise, intitule et commune) : {len(avec_cle)}")
    ecrire(f"- Offres qui republient un poste deja vu : **{nb_rep}** ({pct(nb_rep, len(avec_cle))} des offres comparables)")
    ecrire(f"- dont republiees apres le retrait de la precedente : **{apres_retrait}**")
    if nb_rep:
        ecrire(f"- Ecart median entre deux publications : {rep['ecart_jours'].median():.0f} jours")
    ecrire(f"- Pour comparer : offres en ligne depuis plus de {SEUIL_PERSISTANCE} jours (signal actuel) : "
           f"{(offres['jours_en_ligne'] > SEUIL_PERSISTANCE).sum()}\n")

    # 4. Qui republie le plus
    ecrire("## 4. Entreprises qui republient le plus\n")
    if nb_rep:
        top = (rep.groupby("entreprise").size().sort_values(ascending=False).head(15)
               .rename("Republications").reset_index())
        top["Part des republications"] = [pct(v, nb_rep) for v in top["Republications"]]
        ecrire(tableau(top.rename(columns={"entreprise": "Entreprise"})))
        ecrire("\nA verifier a la main : ESN, cabinets de recrutement et agences d'interim "
               "republient des annonces modeles, ce qui n'est pas forcement une penurie.\n")
    else:
        ecrire("_Aucune republication detectee._\n")

    # 5. Par region : republications et persistance
    ecrire("## 5. Par region : republications et persistance\n")
    par_region = offres.groupby("region").agg(
        offres=("id_offre", "count"),
        persistantes=("jours_en_ligne", lambda s: int((s > SEUIL_PERSISTANCE).sum())),
        manque=("manque", "sum"),
    )
    if nb_rep:
        par_region["republications"] = rep.groupby("region").size()
    else:
        par_region["republications"] = 0
    par_region = par_region.fillna(0)
    par_region = par_region[par_region["offres"] >= 30].sort_values("offres", ascending=False)
    par_region["taux persistance"] = par_region["persistantes"] / par_region["offres"]
    par_region["taux republication"] = par_region["republications"] / par_region["offres"]
    accord = None
    if len(par_region) >= 5 and par_region["taux republication"].std() > 0:
        # Spearman = correlation de Pearson sur les rangs (sans scipy).
        accord = par_region["taux persistance"].rank().corr(par_region["taux republication"].rank())
    affichage = par_region.reset_index()
    affichage["taux persistance"] = [f"{v:.1%}" for v in affichage["taux persistance"]]
    affichage["taux republication"] = [f"{v:.1%}" for v in affichage["taux republication"]]
    ecrire(tableau(affichage[["region", "offres", "taux persistance", "taux republication"]]
                   .rename(columns={"region": "Region", "offres": "Offres"})))
    if accord is not None:
        ecrire(f"\nCorrelation de rang (Spearman) entre les deux taux, par region : **{accord:.2f}** "
               "(1 = meme classement, 0 = aucun lien, negatif = classements opposes).\n")
    else:
        ecrire("\nPas assez de regions (30 offres ou plus) pour une correlation.\n")

    # 6. Types de contrat
    ecrire("## 6. Types de contrat\n")
    contrats = (offres.assign(contrat=offres["type_contrat"].fillna("?") + " — " +
                              offres["type_libelle"].fillna("non renseigne"))
                .groupby("contrat").size().sort_values(ascending=False).rename("Offres").reset_index())
    contrats["Part"] = [pct(v, n) for v in contrats["Offres"]]
    ecrire(tableau(contrats.rename(columns={"contrat": "Contrat"})))
    ecrire("\nLes missions freelance passent surtout par d'autres plateformes : "
           "France Travail en contient peu (contrat LIB, profession liberale).\n")
    return "\n".join(sortie) + "\n"


def main():
    with psycopg2.connect(
        host=os.getenv("DWH_HOST", "postgres-dwh"),
        port=os.getenv("DWH_PORT", "5432"),
        dbname=os.getenv("DWH_DB"),
        user=os.getenv("DWH_USER"),
        password=os.getenv("DWH_PASSWORD"),
    ) as conn, conn.cursor() as cur:
        cur.execute(OFFRES)
        offres = pd.DataFrame(cur.fetchall(), columns=[c.name for c in cur.description])

    texte = mesurer(offres)
    print(texte)
    try:
        os.makedirs(DOSSIER_RAPPORTS, exist_ok=True)
        chemin = os.path.join(DOSSIER_RAPPORTS, f"mesure_signaux_{datetime.now():%Y-%m-%d_%Hh%M}.md")
        with open(chemin, "w", encoding="utf-8") as fichier:
            fichier.write(texte)
        print(f"Rapport enregistre : {chemin}", file=sys.stderr)
    except OSError as erreur:
        print(f"Rapport non enregistre ({erreur}).", file=sys.stderr)


if __name__ == "__main__":
    main()