"""
Compte rendu de l'ingestion : Data Lake (MinIO) et entrepot (PostgreSQL).

Lecture seule : le script ne modifie rien. Il affiche le rapport et
l'enregistre en Markdown dans logs/rapports/ (dossier visible depuis
Windows dans le projet).

Lancement, depuis le dossier du projet :
    docker compose exec airflow-scheduler python /opt/airflow/scripts/rapport_ingestion.py

Options :
    --date AAAA-MM-JJ   collecte a analyser dans le Data Lake (defaut : la plus recente)
    --rapide            ne relit pas les fichiers bruts (pas de comptage par metier)
"""

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from datetime import date, datetime

import psycopg2

from storage import get_minio_client

BUCKET_RAW = "raw"
BUCKET_SILVER = "silver"
LIMITE_API = 3150          # offres max par recherche dans l'API France Travail
ANCIEN_PLAFOND = 2000      # plafond par metier de l'ancienne version du DAG
DOSSIER_RAPPORTS = "/opt/airflow/logs/rapports"

MOTIF_BRUT = re.compile(
    r"france_travail/code_rome=(?P<rome>[^/]+)/date=(?P<date>\d{4}-\d{2}-\d{2})/"
)
MOTIF_SILVER = re.compile(r"france_travail/date=(?P<date>\d{4}-\d{2}-\d{2})/")


# ------------------------------------------------------------ mise en forme

class Rapport:
    def __init__(self):
        self.lignes = []

    def titre(self, texte, niveau=2):
        self.lignes += ["", "#" * niveau + " " + texte, ""]

    def texte(self, texte=""):
        self.lignes.append(texte)

    def puce(self, texte):
        self.lignes.append(f"- {texte}")

    def tableau(self, entetes, lignes):
        if not lignes:
            self.texte("_Aucune donnee._")
            return
        self.lignes.append("| " + " | ".join(entetes) + " |")
        self.lignes.append("| " + " | ".join("---" for _ in entetes) + " |")
        for ligne in lignes:
            self.lignes.append("| " + " | ".join(str(v) for v in ligne) + " |")

    def contenu(self):
        return "\n".join(self.lignes).strip() + "\n"


def nombre(n):
    return f"{n:,}".replace(",", " ") if isinstance(n, int) else str(n)


def pct(part, total):
    return f"{100 * part / total:.0f} %" if total else "–"


# ---------------------------------------------------------------- Data Lake

def lister(client, bucket, prefixe):
    if not client.bucket_exists(bucket):
        return []
    return list(client.list_objects(bucket, prefix=prefixe, recursive=True))


def lire(client, bucket, nom):
    reponse = client.get_object(bucket, nom)
    try:
        return json.loads(reponse.read().decode("utf-8"))
    finally:
        reponse.close()
        reponse.release_conn()


def section_data_lake(r, client, date_choisie, rapide):
    r.titre("1. Data Lake (MinIO)")

    bruts = lister(client, BUCKET_RAW, "france_travail/")
    par_date = defaultdict(lambda: {"fichiers": 0, "metiers": set(), "octets": 0})
    for obj in bruts:
        m = MOTIF_BRUT.search(obj.object_name)
        if m:
            d = par_date[m["date"]]
            d["fichiers"] += 1
            d["metiers"].add(m["rome"])
            d["octets"] += obj.size or 0

    silvers = {}
    for obj in lister(client, BUCKET_SILVER, "france_travail/"):
        m = MOTIF_SILVER.search(obj.object_name)
        if m:
            silvers[m["date"]] = obj

    dates = sorted(set(par_date) | set(silvers))
    if not dates:
        r.texte("Aucune collecte trouvee dans le Data Lake.")
        return None

    r.puce(f"Jours de collecte : **{len(dates)}**, du {dates[0]} au {dates[-1]}")
    premier = date.fromisoformat(dates[0])
    attendus = (date.fromisoformat(dates[-1]) - premier).days + 1
    r.puce(f"Jours sans collecte sur la periode : **{attendus - len(dates)}** sur {attendus}")
    manquants = [
        str(premier.fromordinal(premier.toordinal() + i))
        for i in range(attendus)
        if str(premier.fromordinal(premier.toordinal() + i)) not in dates
    ]
    if manquants:
        r.puce("Dates manquantes : " + ", ".join(manquants[:30])
               + (" …" if len(manquants) > 30 else ""))

    r.texte()
    lignes = []
    for d in dates[-15:]:
        brut = par_date.get(d)
        silver = silvers.get(d)
        nb_silver = "–"
        if silver is not None:
            try:
                nb_silver = nombre(len(lire(client, BUCKET_SILVER, silver.object_name)))
            except Exception as erreur:  # fichier illisible : on le signale
                nb_silver = f"illisible ({type(erreur).__name__})"
        lignes.append((
            d,
            brut["fichiers"] if brut else 0,
            len(brut["metiers"]) if brut else 0,
            f"{(brut['octets'] if brut else 0) / 1e6:.1f} Mo",
            nb_silver,
        ))
    r.texte("15 dernieres collectes :")
    r.texte()
    r.tableau(["Date", "Fichiers bruts", "Metiers", "Taille brute", "Offres silver (dedoublonnees)"], lignes)

    date_cible = date_choisie or max(par_date) if par_date else None
    if date_cible and not rapide:
        section_metiers(r, client, bruts, date_cible)
    return date_cible


def section_metiers(r, client, bruts, date_cible):
    r.titre(f"2. Collecte du {date_cible}, metier par metier")

    # Plusieurs executions le meme jour : on garde le fichier le plus recent.
    fichiers = {}
    for obj in bruts:
        m = MOTIF_BRUT.search(obj.object_name)
        if m and m["date"] == date_cible:
            actuel = fichiers.get(m["rome"])
            if actuel is None or obj.last_modified > actuel.last_modified:
                fichiers[m["rome"]] = obj

    perimetre = []
    referentiels = lister(client, BUCKET_RAW, f"referentiel_rome/date={date_cible}/")
    if referentiels:
        try:
            perimetre = lire(client, BUCKET_RAW, referentiels[-1].object_name)
        except Exception:
            perimetre = []
    libelles = {m["code"]: m.get("libelle", "") for m in perimetre}

    lignes, total, tronques = [], 0, []
    for rome in sorted(fichiers):
        n = len(lire(client, BUCKET_RAW, fichiers[rome].object_name))
        total += n
        alerte = ""
        if n >= LIMITE_API:
            alerte = "limite de l'API atteinte"
            tronques.append(rome)
        elif n == ANCIEN_PLAFOND:
            alerte = "plafond de 2 000 atteint"
            tronques.append(rome)
        lignes.append((rome, libelles.get(rome, "")[:55], nombre(n), alerte))
    lignes.sort(key=lambda l: -int(l[2].replace(" ", "")))

    sans_fichier = sorted(set(libelles) - set(fichiers))
    r.puce(f"Metiers du perimetre (referentiel du jour) : **{len(libelles) or 'inconnu'}**")
    r.puce(f"Metiers avec des offres : **{len(fichiers)}** · offres brutes : **{nombre(total)}**")
    r.puce(f"Metiers sans aucune offre recuperee : **{len(sans_fichier)}**"
           " (aucune offre publiee, ou collecte en erreur : voir les logs Airflow)")
    r.puce(f"Metiers probablement **tronques** : **{len(tronques)}** "
           + ("(" + ", ".join(tronques) + ")" if tronques else ""))
    r.texte()
    r.tableau(["ROME", "Metier", "Offres brutes", "Alerte"], lignes)
    if sans_fichier:
        r.texte()
        r.texte("Metiers sans offre : " + ", ".join(
            f"{c} {libelles.get(c, '')[:40]}" for c in sans_fichier))


# ---------------------------------------------------------------- entrepot

def requete(cur, sql, params=None):
    cur.execute(sql, params)
    return cur.fetchall()


def colonnes(cur, table):
    return {l[0] for l in requete(cur, """
        SELECT column_name FROM information_schema.columns WHERE table_name = %s
    """, (table,))}


def table_existe(cur, table):
    return bool(requete(cur, "SELECT to_regclass(%s)", (table,))[0][0])


def section_entrepot(r, cur):
    r.titre("3. Entrepot (PostgreSQL)")
    if not table_existe(cur, "fait_offre"):
        r.texte("La table fait_offre n'existe pas : lance le DAG chargement_gold.")
        return

    cols = colonnes(cur, "fait_offre")
    (total, en_ligne, jour, premiere, sources), = requete(cur, """
        WITH m AS (SELECT MAX(derniere_collecte) AS jour FROM fait_offre)
        SELECT COUNT(*),
               COUNT(*) FILTER (WHERE derniere_collecte = m.jour),
               m.jour, MIN(premiere_collecte), COUNT(DISTINCT source)
        FROM fait_offre CROSS JOIN m GROUP BY m.jour
    """)
    r.puce(f"Offres dans l'entrepot (historique complet) : **{nombre(total)}**")
    r.puce(f"Offres vues a la derniere collecte ({jour}) : **{nombre(en_ligne)}**")
    r.puce(f"Premiere collecte en base : {premiere} · sources : {sources}")

    # Qualite des donnees
    r.titre("4. Qualite des donnees", 3)
    mesures = [
        ("Lieu exploitable (ville + departement)", """
            SELECT COUNT(*) FROM fait_offre f JOIN dim_lieu l USING (code_insee)
            WHERE l.ville_normalisee IS NOT NULL AND l.departement IS NOT NULL"""),
        ("Au moins une competence reconnue", """
            SELECT COUNT(DISTINCT id_offre) FROM pont_offre_competence"""),
        ("Au moins 3 competences reconnues", """
            SELECT COUNT(*) FROM (SELECT id_offre FROM pont_offre_competence
            GROUP BY id_offre HAVING COUNT(*) >= 3) t"""),
        ("Signalees « manque de candidats »", """
            SELECT COUNT(*) FROM fait_offre WHERE manque_candidats"""),
        ("Avec un salaire lisible", """
            SELECT COUNT(*) FROM fait_offre WHERE salaire_min IS NOT NULL"""),
    ]
    if "experience_annees" in cols:
        mesures.append(("Experience demandee connue", """
            SELECT COUNT(*) FROM fait_offre WHERE experience_annees IS NOT NULL"""))
    if "url_offre" in cols:
        mesures.append(("Lien vers l'annonce", """
            SELECT COUNT(*) FROM fait_offre WHERE url_offre IS NOT NULL"""))
    if "hors_perimetre" in cols:
        mesures.append(("Hors perimetre (mal codees, exclues des analyses)", """
            SELECT COUNT(*) FROM fait_offre WHERE hors_perimetre"""))
    if "id_poste" in cols:
        mesures.append(("Rangees dans un poste de l'application", """
            SELECT COUNT(*) FROM fait_offre WHERE id_poste IS NOT NULL"""))
    if table_existe(cur, "ref_departement"):
        mesures.append(("Rattachees a une region", """
            SELECT COUNT(*) FROM fait_offre f JOIN dim_lieu l USING (code_insee)
            JOIN ref_departement d ON d.departement = l.departement"""))

    lignes = []
    for libelle, sql in mesures:
        n = requete(cur, sql)[0][0]
        lignes.append((libelle, nombre(n), pct(n, total)))
    r.tableau(["Indicateur", "Offres", "Part"], lignes)

    # Fraicheur des offres en ligne
    r.titre("5. Fraicheur des offres en ligne", 3)
    lignes = requete(cur, """
        WITH m AS (SELECT MAX(derniere_collecte) AS jour FROM fait_offre)
        SELECT CASE
                 WHEN f.date_creation IS NULL THEN '5. date inconnue'
                 WHEN m.jour - f.date_creation <= 14 THEN '1. 0 a 14 jours'
                 WHEN m.jour - f.date_creation <= 30 THEN '2. 15 a 30 jours'
                 WHEN m.jour - f.date_creation <= 60 THEN '3. 31 a 60 jours'
                 ELSE '4. plus de 60 jours' END AS tranche,
               COUNT(*)
        FROM fait_offre f CROSS JOIN m
        WHERE f.derniere_collecte = m.jour
        GROUP BY 1 ORDER BY 1
    """)
    r.tableau(["Anciennete", "Offres en ligne", "Part"],
              [(t[3:], nombre(n), pct(n, en_ligne)) for t, n in lignes])

    # Postes
    if "id_poste" in cols and table_existe(cur, "dim_poste"):
        r.titre("6. Repartition par poste", 3)
        cat = "COALESCE(p.categorie, '')" if "categorie" in colonnes(cur, "dim_poste") else "''"
        lignes = requete(cur, f"""
            WITH m AS (SELECT MAX(derniere_collecte) AS jour FROM fait_offre)
            SELECT {cat}, COALESCE(p.libelle, '(aucun poste reconnu)'),
                   COUNT(*),
                   COUNT(*) FILTER (WHERE f.derniere_collecte = m.jour),
                   COUNT(*) FILTER (WHERE f.derniere_collecte = m.jour
                                    AND m.jour - f.date_creation <= 14)
            FROM fait_offre f CROSS JOIN m
            LEFT JOIN dim_poste p ON p.id_poste = f.id_poste
            GROUP BY 1, 2 ORDER BY 4 DESC
        """)
        r.tableau(["Categorie", "Poste", "Total", "En ligne", "En ligne < 14 j"],
                  [(c, p, nombre(t), nombre(e), nombre(n)) for c, p, t, e, n in lignes])

        r.texte()
        r.texte("Intitules les plus frequents parmi les offres sans poste "
                "(pistes pour completer postes.json) :")
        r.texte()
        lignes = requete(cur, f"""
            SELECT intitule, COUNT(*) FROM fait_offre
            WHERE id_poste IS NULL {"AND NOT hors_perimetre" if "hors_perimetre" in cols else ""}
            GROUP BY 1 ORDER BY 2 DESC LIMIT 15
        """)
        r.tableau(["Intitule", "Offres"], [(i, nombre(n)) for i, n in lignes])

    # Metiers ROME
    r.titre("7. Repartition par metier ROME (offres en ligne)", 3)
    lignes = requete(cur, """
        WITH m AS (SELECT MAX(derniere_collecte) AS jour FROM fait_offre)
        SELECT f.code_rome, COALESCE(dm.libelle, ''), COUNT(*)
        FROM fait_offre f CROSS JOIN m
        LEFT JOIN dim_metier dm ON dm.code_rome = f.code_rome
        WHERE f.derniere_collecte = m.jour
        GROUP BY 1, 2 ORDER BY 3 DESC LIMIT 25
    """)
    r.tableau(["ROME", "Metier", "Offres en ligne"],
              [(c, l[:55], nombre(n)) for c, l, n in lignes])

    # Geographie
    if table_existe(cur, "ref_region"):
        r.titre("8. Repartition geographique (offres en ligne)", 3)
        lignes = requete(cur, """
            WITH m AS (SELECT MAX(derniere_collecte) AS jour FROM fait_offre)
            SELECT COALESCE(rr.nom, '(region inconnue)'), COUNT(*)
            FROM fait_offre f CROSS JOIN m
            JOIN dim_lieu l USING (code_insee)
            LEFT JOIN ref_departement d ON d.departement = l.departement
            LEFT JOIN ref_region rr ON rr.code_region = d.code_region
            WHERE f.derniere_collecte = m.jour
            GROUP BY 1 ORDER BY 2 DESC
        """)
        r.tableau(["Region", "Offres en ligne", "Part"],
                  [(n, nombre(c), pct(c, en_ligne)) for n, c in lignes])

    r.texte()
    r.texte("Villes les plus representees (offres en ligne) :")
    r.texte()
    lignes = requete(cur, """
        WITH m AS (SELECT MAX(derniere_collecte) AS jour FROM fait_offre)
        SELECT INITCAP(l.ville_normalisee), l.departement, COUNT(*)
        FROM fait_offre f CROSS JOIN m JOIN dim_lieu l USING (code_insee)
        WHERE f.derniere_collecte = m.jour AND l.ville_normalisee IS NOT NULL
        GROUP BY 1, 2 ORDER BY 3 DESC LIMIT 20
    """)
    r.tableau(["Ville", "Dept", "Offres en ligne"], [(v, d, nombre(n)) for v, d, n in lignes])

    # Historique de collecte vu de l'entrepot
    r.titre("9. Nouvelles offres par jour de collecte", 3)
    lignes = requete(cur, """
        SELECT premiere_collecte, COUNT(*) FROM fait_offre
        GROUP BY 1 ORDER BY 1 DESC LIMIT 20
    """)
    r.tableau(["Jour", "Nouvelles offres"], [(d, nombre(n)) for d, n in lignes])


# ------------------------------------------------------------------- main

def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument("--date", help="collecte a analyser (AAAA-MM-JJ)")
    parser.add_argument("--rapide", action="store_true",
                        help="ne relit pas les fichiers bruts")
    args = parser.parse_args()

    r = Rapport()
    r.titre("Compte rendu de l'ingestion — Detecteur de niches IT", 1)
    r.texte(f"Genere le {datetime.now():%d/%m/%Y a %H:%M}.")

    try:
        section_data_lake(r, get_minio_client(), args.date, args.rapide)
    except Exception as erreur:
        r.texte(f"**Data Lake inaccessible** : {erreur}")

    try:
        with psycopg2.connect(
            host=os.getenv("DWH_HOST", "postgres-dwh"),
            port=os.getenv("DWH_PORT", "5432"),
            dbname=os.getenv("DWH_DB"),
            user=os.getenv("DWH_USER"),
            password=os.getenv("DWH_PASSWORD"),
        ) as conn, conn.cursor() as cur:
            section_entrepot(r, cur)
    except psycopg2.Error as erreur:
        r.texte(f"**Entrepot inaccessible** : {erreur}")

    texte = r.contenu()
    print(texte)

    try:
        os.makedirs(DOSSIER_RAPPORTS, exist_ok=True)
        chemin = os.path.join(
            DOSSIER_RAPPORTS, f"rapport_ingestion_{datetime.now():%Y-%m-%d_%Hh%M}.md"
        )
        with open(chemin, "w", encoding="utf-8") as fichier:
            fichier.write(texte)
        print(f"Rapport enregistre : {chemin}", file=sys.stderr)
    except OSError as erreur:
        print(f"Rapport non enregistre ({erreur}).", file=sys.stderr)


if __name__ == "__main__":
    main()