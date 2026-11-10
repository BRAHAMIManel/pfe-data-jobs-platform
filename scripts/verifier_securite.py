"""
Verification des protections de securite : prouver, pas supposer.

Chaque controle essaie une action et verifie le resultat attendu :
  - le compte de l'application LIT l'entrepot mais ne peut RIEN modifier ;
  - le compte MinIO du pipeline lit et ecrit raw et silver, mais ne peut
    ni supprimer, ni toucher aux autres buckets, ni en creer ;
  - les cles de chiffrement d'Airflow sont definies.

Sans danger : les essais d'ecriture dans l'entrepot sont faits dans une
transaction annulee (ROLLBACK), et la suppression MinIO vise un fichier
qui n'existe pas.

Lancement :
    docker compose exec airflow-scheduler python /opt/airflow/scripts/verifier_securite.py
"""

import io
import os
import sys
from datetime import datetime

import psycopg2
from minio.error import S3Error

from storage import get_minio_client

DOSSIER_RAPPORTS = "/opt/airflow/logs/rapports"
resultats = []


def controle(domaine, description, attendu_ok, action):
    """Execute `action` ; reussite si elle passe (attendu_ok) ou echoue (sinon)."""
    try:
        action()
        reussi, detail = attendu_ok, "autorise"
    except (psycopg2.Error, S3Error) as erreur:
        code = getattr(erreur, "pgcode", None) or getattr(erreur, "code", "")
        reussi, detail = (not attendu_ok), f"refuse ({code})"
    resultats.append((domaine, description, "autorise" if attendu_ok else "refuse", detail, reussi))


def controles_entrepot():
    utilisateur = os.getenv("APP_DWH_USER", "app_lecture")
    try:
        conn = psycopg2.connect(
            host=os.getenv("DWH_HOST", "postgres-dwh"), port=os.getenv("DWH_PORT", "5432"),
            dbname=os.getenv("DWH_DB"), user=utilisateur,
            password=os.getenv("APP_DWH_PASSWORD"),
        )
    except psycopg2.Error as erreur:
        resultats.append(("Entrepot", f"Connexion du compte {utilisateur}", "autorise",
                          f"impossible ({erreur.__class__.__name__})", False))
        return

    def essai(requete):
        def action():
            with conn.cursor() as cur:
                try:
                    cur.execute(requete)
                finally:
                    conn.rollback()   # rien n'est jamais enregistre
        return action

    d = f"Compte {utilisateur}"
    controle("Entrepot", f"{d} : lire la table de l'application", True,
             essai("SELECT count(*) FROM analytique.mart_offres_candidat"))
    controle("Entrepot", f"{d} : lire le schema en etoile", True,
             essai("SELECT count(*) FROM fait_offre"))
    controle("Entrepot", f"{d} : modifier une offre", False,
             essai("UPDATE fait_offre SET intitule = intitule WHERE false"))
    controle("Entrepot", f"{d} : supprimer des offres", False,
             essai("DELETE FROM fait_offre WHERE false"))
    controle("Entrepot", f"{d} : inserer une ligne", False,
             essai("INSERT INTO dim_metier (code_rome, libelle) VALUES ('ZZZZZ', 'test')"))
    controle("Entrepot", f"{d} : creer une table", False,
             essai("CREATE TABLE public.test_securite (x int)"))
    controle("Entrepot", f"{d} : supprimer une table", False,
             essai("DROP TABLE fait_offre"))
    conn.close()


def controles_data_lake():
    client = get_minio_client()
    d = f"Compte {os.getenv('MINIO_ACCESS_KEY')}"
    controle("Data Lake", f"{d} : lister raw", True,
             lambda: list(client.list_objects("raw", prefix="france_travail/", recursive=False)))
    controle("Data Lake", f"{d} : lister silver", True,
             lambda: list(client.list_objects("silver", prefix="france_travail/", recursive=False)))
    controle("Data Lake", f"{d} : supprimer un fichier de raw", False,
             lambda: client.remove_object("raw", "verification_securite/inexistant.json"))
    controle("Data Lake", f"{d} : ecrire dans gold", False,
             lambda: client.put_object("gold", "verification_securite.txt", io.BytesIO(b"x"), 1))
    controle("Data Lake", f"{d} : creer un bucket", False,
             lambda: client.make_bucket("verification-securite"))
    # MinIO ne refuse pas la liste des buckets : il n'y montre que ceux sur
    # lesquels le compte a des droits. On verifie donc ce qui est VISIBLE.
    visibles = sorted(b.name for b in client.list_buckets())
    resultats.append(("Data Lake", f"{d} : buckets visibles", "raw, silver",
                      ", ".join(visibles) or "aucun", visibles == ["raw", "silver"]))


def controles_secrets():
    for variable, role in (
        ("AIRFLOW__CORE__FERNET_KEY", "chiffrement des secrets Airflow"),
        ("AIRFLOW__WEBSERVER__SECRET_KEY", "signature des sessions web"),
    ):
        presente = bool(os.getenv(variable))
        resultats.append(("Secrets", f"Cle de {role} definie", "definie",
                          "definie" if presente else "absente", presente))
    racine = os.getenv("MINIO_ACCESS_KEY") == os.getenv("MINIO_ROOT_USER")
    resultats.append(("Secrets", "Le pipeline n'utilise pas le compte root MinIO", "oui",
                      "root utilise" if racine else "compte dedie", not racine))


def rapport():
    reussis = sum(1 for r in resultats if r[4])
    lignes = [
        "# Verification de securite — Detecteur de niches IT", "",
        f"Genere le {datetime.now():%d/%m/%Y a %H:%M}. **{reussis} controles reussis sur {len(resultats)}.**", "",
        "| Domaine | Controle | Attendu | Obtenu | Resultat |",
        "| --- | --- | --- | --- | --- |",
    ]
    lignes += [f"| {d} | {c} | {a} | {o} | {'OK' if r else '**ECHEC**'} |" for d, c, a, o, r in resultats]
    lignes += ["", "Ports (a verifier sur le PC avec `docker compose ps`) : chaque port doit "
               "commencer par 127.0.0.1, donc etre invisible depuis le reseau."]
    return "\n".join(lignes) + "\n", reussis == len(resultats)


def main():
    controles_entrepot()
    try:
        controles_data_lake()
    except Exception as erreur:  # MinIO injoignable
        resultats.append(("Data Lake", "Connexion au Data Lake", "autorise", f"impossible ({erreur})", False))
    controles_secrets()

    texte, tout_ok = rapport()
    print(texte)
    try:
        os.makedirs(DOSSIER_RAPPORTS, exist_ok=True)
        chemin = os.path.join(DOSSIER_RAPPORTS, f"securite_{datetime.now():%Y-%m-%d_%Hh%M}.md")
        with open(chemin, "w", encoding="utf-8") as fichier:
            fichier.write(texte)
        print(f"Rapport enregistre : {chemin}", file=sys.stderr)
    except OSError as erreur:
        print(f"Rapport non enregistre ({erreur}).", file=sys.stderr)
    sys.exit(0 if tout_ok else 1)


if __name__ == "__main__":
    main()