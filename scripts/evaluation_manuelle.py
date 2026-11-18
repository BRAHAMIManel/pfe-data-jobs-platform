"""
Evaluation manuelle du detecteur : est-ce qu'il trouve JUSTE ?

Les tests prouvent que le code fait ce qu'on attend. Ils ne disent pas si
le resultat est correct sur de vraies offres. Ici, un humain verifie un
echantillon tire au hasard, et on en tire un taux de precision.

Deux controles :
  1. Competences : pour 50 offres, les competences detectees dans la
     description sont-elles vraiment demandees ? En manque-t-il ?
  2. Republications : pour 30 republications retenues, s'agit-il vraiment
     du meme poste remis en ligne ?

Etape 1 - preparer les fichiers a remplir :
    docker compose exec airflow-scheduler python /opt/airflow/scripts/evaluation_manuelle.py preparer

    Deux fichiers apparaissent dans logs/rapports/evaluation/ (ouvrables
    dans Excel) : competences_a_verifier.csv, republications_a_verifier.csv.

Etape 2 - remplir dans Excel les colonnes en MAJUSCULES, puis enregistrer
    au format CSV (separateur point-virgule), sans changer les noms :
      VU        : x quand l'offre est verifiee (meme si tout est juste)
      FAUSSES   : competences detectees a tort, separees par des virgules
      OUBLIEES  : competences demandees mais non detectees
      VERDICT   : oui / non (republication = meme poste remis en ligne)
    Une ligne laissee vide n'est pas comptee : on peut s'arreter en route.

Etape 3 - calculer les taux :
    docker compose exec airflow-scheduler python /opt/airflow/scripts/evaluation_manuelle.py calculer

L'echantillon est tire au hasard mais de facon reproductible (meme graine) :
relancer "preparer" redonne les memes offres tant que l'entrepot ne change
pas. Lecture seule : rien n'est modifie dans l'entrepot ni dans MinIO.
"""

import io
import math
import os
import sys
import warnings
from datetime import datetime

import pandas as pd
import psycopg2

from storage import lire_json, lire_octets, lister_objets

DOSSIER = "/opt/airflow/logs/rapports/evaluation"
FICHIER_COMPETENCES = os.path.join(DOSSIER, "competences_a_verifier.csv")
FICHIER_REPUBLICATIONS = os.path.join(DOSSIER, "republications_a_verifier.csv")
TAILLE_COMPETENCES = 50
TAILLE_REPUBLICATIONS = 30
GRAINE = "pfe-2026"        # tirage reproductible : tri sur md5(id || graine)
BUCKET_SILVER = "silver"
LONGUEUR_MAX = 3000        # description tronquee pour rester lisible dans Excel

# Meme normalisation d'intitule que dbt (int_republications).
INTITULE = r"""trim(regexp_replace(regexp_replace(
    translate(lower({t}.intitule), 'àâäéèêëîïôöùûüç', 'aaaeeeeiioouuuc'),
    '\(?\s*(h\s*/\s*f|f\s*/\s*h)\s*\)?', '', 'g'), '\s+', ' ', 'g'))"""

ECHANTILLON_COMPETENCES = f"""
    SELECT f.id_offre, f.intitule, f.url_offre,
           STRING_AGG(c.libelle, ', ' ORDER BY c.libelle) AS competences_detectees,
           COUNT(c.libelle) AS nb_detectees
    FROM fait_offre f
    LEFT JOIN pont_offre_competence p ON p.id_offre = f.id_offre
    LEFT JOIN dim_competence c ON c.id_competence = p.id_competence
    WHERE NOT f.hors_perimetre
    GROUP BY f.id_offre
    ORDER BY md5(f.id_offre || '{GRAINE}')
    LIMIT {TAILLE_COMPETENCES}
"""

# Pour chaque republication retenue (B), l'offre d'origine (A) : la plus
# proche dans le temps parmi celles qui remplissent les conditions de dbt.
ECHANTILLON_REPUBLICATIONS = f"""
    WITH b AS (
        SELECT r.id_offre, r.ecart_jours
        FROM analytique.int_republications r
        WHERE r.republication_retenue
        ORDER BY md5(r.id_offre || '{GRAINE}')
        LIMIT {TAILLE_REPUBLICATIONS}
    )
    SELECT DISTINCT ON (fb.id_offre)
           e.nom AS entreprise, l.ville,
           fa.id_offre AS id_origine, fa.intitule AS intitule_origine,
           fa.date_creation AS publiee_le_origine,
           fa.derniere_collecte AS vue_jusqu_au_origine,
           fb.id_offre AS id_republiee, fb.intitule AS intitule_republiee,
           fb.date_creation AS publiee_le_republiee,
           b.ecart_jours,
           fa.url_offre AS url_origine, fb.url_offre AS url_republiee
    FROM b
    JOIN fait_offre fb ON fb.id_offre = b.id_offre
    JOIN fait_offre fa
      ON  fa.id_entreprise = fb.id_entreprise
      AND fa.code_insee = fb.code_insee
      AND fa.id_offre <> fb.id_offre
      AND {INTITULE.format(t="fa")} = {INTITULE.format(t="fb")}
      AND fa.derniere_collecte < fb.premiere_collecte
      AND fb.date_creation >= fa.date_creation + 14
    JOIN dim_entreprise e ON e.id_entreprise = fb.id_entreprise
    LEFT JOIN dim_lieu l ON l.code_insee = fb.code_insee
    ORDER BY fb.id_offre, fa.date_creation DESC
"""


# pandas prefere SQLAlchemy, mais psycopg2 suffit pour une lecture simple.
warnings.filterwarnings("ignore", message=".*SQLAlchemy.*")


def connexion():
    return psycopg2.connect(
        host=os.getenv("DWH_HOST", "postgres-dwh"),
        port=os.getenv("DWH_PORT", "5432"),
        dbname=os.getenv("DWH_DB"),
        user=os.getenv("DWH_USER"),
        password=os.getenv("DWH_PASSWORD"),
    )


# ------------------------------------------------------------ silver

def fichiers_silver():
    """Chemins des fichiers silver, du plus recent au plus ancien."""
    chemins = [
        c for c in lister_objets(BUCKET_SILVER, "france_travail/date=")
        if c.endswith(("offres.json", "offres.parquet"))
    ]
    return sorted(chemins, reverse=True)


def lire_fichier_silver(chemin):
    if chemin.endswith(".parquet"):
        import pyarrow.parquet as pq

        table = pq.read_table(io.BytesIO(lire_octets(BUCKET_SILVER, chemin)))
        return table.to_pylist()
    return lire_json(BUCKET_SILVER, chemin)


def descriptions(ids):
    """Description de chaque offre, cherchee dans silver (pas dans l'entrepot,
    qui ne la stocke pas). On s'arrete des que toutes sont trouvees."""
    restantes, trouvees = set(ids), {}
    for chemin in fichiers_silver():
        if not restantes:
            break
        for offre in lire_fichier_silver(chemin) or []:
            identifiant = offre.get("id")
            if identifiant in restantes:
                trouvees[identifiant] = offre.get("description") or ""
                restantes.discard(identifiant)
    if restantes:
        print(f"  {len(restantes)} description(s) introuvable(s) dans silver.")
    return trouvees


def couper(texte):
    texte = " ".join((texte or "").split())
    return texte if len(texte) <= LONGUEUR_MAX else texte[:LONGUEUR_MAX] + " [...]"


# ---------------------------------------------------------- preparer

def preparer():
    os.makedirs(DOSSIER, exist_ok=True)
    with connexion() as conn:
        competences = pd.read_sql(ECHANTILLON_COMPETENCES, conn)
        republications = pd.read_sql(ECHANTILLON_REPUBLICATIONS, conn)

    print(f"Echantillon : {len(competences)} offres, {len(republications)} republications.")
    print("Recherche des descriptions dans silver...")
    textes = descriptions(
        list(competences["id_offre"])
        + list(republications["id_origine"])
        + list(republications["id_republiee"])
    )

    competences["competences_detectees"] = competences["competences_detectees"].fillna("")
    competences["description"] = competences["id_offre"].map(textes).map(couper)
    competences["VU"] = ""
    competences["FAUSSES"] = ""
    competences["OUBLIEES"] = ""
    competences["COMMENTAIRE"] = ""
    competences = competences[[
        "id_offre", "intitule", "competences_detectees", "VU", "FAUSSES", "OUBLIEES",
        "COMMENTAIRE", "nb_detectees", "description", "url_offre",
    ]]

    republications["description_origine"] = republications["id_origine"].map(textes).map(couper)
    republications["description_republiee"] = republications["id_republiee"].map(textes).map(couper)
    republications.insert(0, "VERDICT", "")
    republications.insert(1, "COMMENTAIRE", "")

    # utf-8-sig + point-virgule : Excel en francais l'ouvre directement.
    competences.to_csv(FICHIER_COMPETENCES, sep=";", index=False, encoding="utf-8-sig")
    republications.to_csv(FICHIER_REPUBLICATIONS, sep=";", index=False, encoding="utf-8-sig")
    print("Fichiers a remplir :")
    print("  logs/rapports/evaluation/competences_a_verifier.csv")
    print("  logs/rapports/evaluation/republications_a_verifier.csv")


# ---------------------------------------------------------- calculer

def lire_rempli(chemin):
    """Relit un fichier rempli, quel que soit l'encodage choisi par Excel."""
    for encodage in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return pd.read_csv(chemin, sep=";", dtype=str, encoding=encodage).fillna("")
        except UnicodeDecodeError:
            continue
    raise ValueError(f"Impossible de lire {chemin}")


def liste(cellule):
    return [x.strip() for x in str(cellule).replace(";", ",").split(",") if x.strip()]


def intervalle(succes, total):
    """Intervalle de confiance a 95 % (Wilson) d'une proportion : avec 50
    offres, il faut dire a quel point le taux est precis."""
    if total == 0:
        return float("nan"), float("nan")
    z, p = 1.96, succes / total
    centre = (p + z * z / (2 * total)) / (1 + z * z / total)
    marge = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / (1 + z * z / total)
    return max(0.0, centre - marge), min(1.0, centre + marge)


def pct(x):
    return "—" if x != x else f"{100 * x:.0f} %"


def calculer():
    lignes = [f"# Evaluation manuelle du detecteur — {datetime.now():%d/%m/%Y}", ""]

    c = lire_rempli(FICHIER_COMPETENCES)
    # Une offre est comptee si elle est cochee (VU) ou corrigee.
    verifiees = c[(c["VU"].str.strip() != "") | (c["FAUSSES"] != "") | (c["OUBLIEES"] != "")]
    detectees = sum(len(liste(x)) for x in verifiees["competences_detectees"])
    fausses = sum(len(liste(x)) for x in verifiees["FAUSSES"])
    oubliees = sum(len(liste(x)) for x in verifiees["OUBLIEES"])
    justes = detectees - fausses
    precision = justes / detectees if detectees else float("nan")
    rappel = justes / (justes + oubliees) if (justes + oubliees) else float("nan")
    bas, haut = intervalle(justes, detectees)
    lignes += [
        "## 1. Competences detectees",
        f"- Offres verifiees : {len(verifiees)}",
        f"- Competences detectees : {detectees}, dont {fausses} fausses",
        f"- Competences oubliees : {oubliees}",
        f"- **Precision : {pct(precision)}** (IC 95 % : {pct(bas)} – {pct(haut)})"
        " — part des competences detectees qui sont vraiment demandees",
        f"- **Rappel : {pct(rappel)}** — part des competences demandees qui sont detectees",
        "",
    ]
    erreurs = pd.Series([x.lower() for f in verifiees["FAUSSES"] for x in liste(f)]).value_counts()
    if len(erreurs):
        lignes += ["Erreurs les plus frequentes : "
                   + ", ".join(f"{k} ({v})" for k, v in erreurs.head(5).items()), ""]

    r = lire_rempli(FICHIER_REPUBLICATIONS)
    verdict = r["VERDICT"].str.lower().str.strip().str.replace("é", "e")
    oui, non = int(verdict.isin(["oui", "o", "vrai"]).sum()), int(verdict.isin(["non", "n", "faux"]).sum())
    bas, haut = intervalle(oui, oui + non)
    lignes += [
        "## 2. Republications",
        f"- Republications verifiees : {oui + non} (oui : {oui}, non : {non})",
        f"- **Precision : {pct(oui / (oui + non) if oui + non else float('nan'))}**"
        f" (IC 95 % : {pct(bas)} – {pct(haut)})"
        " — part des republications detectees qui sont vraiment le meme poste remis en ligne",
    ]

    texte = "\n".join(lignes)
    print(texte)
    sortie = os.path.join(DOSSIER, f"resultats_{datetime.now():%Y-%m-%d}.md")
    with open(sortie, "w", encoding="utf-8") as fichier:
        fichier.write(texte + "\n")
    print(f"\nRapport enregistre : logs/rapports/evaluation/{os.path.basename(sortie)}")


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else ""
    if action == "preparer":
        preparer()
    elif action == "calculer":
        calculer()
    else:
        print("Usage : evaluation_manuelle.py preparer | calculer")
        sys.exit(1)