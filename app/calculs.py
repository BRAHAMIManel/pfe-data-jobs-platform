"""
Calculs personnalises de l'application : tout ce qui depend du candidat.

L'entrepot fournit les offres ; ici on les croise avec le CV (competences,
experience), les postes vises et la zone choisie. Fonctions pures sur des
DataFrame : aucune requete, aucun affichage, donc faciles a tester.

Score d'opportunite d'un territoire, sur 100 :
    100 x ( 0,45 x penurie + 0,35 x adequation au CV + 0,20 x volume )

Le score classe les territoires selon des signaux de tension et
l'adequation au profil ; ce n'est pas une probabilite d'embauche.
"""

import math

import numpy as np
import pandas as pd

from transformation import MOTIF_ARRONDISSEMENT

SEUIL_JOURS = 30        # au-dela, une offre est "persistante"
LISSAGE = 20            # poids de la moyenne nationale, en offres fictives
EVENEMENTS_MINIMUM = 3  # l'a priori contient au moins 3 signaux attendus
MIN_OFFRES_CONSEIL = 5  # en dessous, pas de competences a apprendre
JOURS_RECENTS = 14      # offres affichees par defaut
ECART_NIVEAU = 2        # annees d'experience tolerees au-dela du CV
MIN_COMMUNES = 2        # competences communes minimum entre CV et offre
SEUIL_FIABLE = 30
SEUIL_INDICATIF = 10
POIDS = {"penurie": 0.45, "adequation": 0.35, "volume": 0.20}


# --------------------------------------------------------- preparation

def _ville_affichee(ville):
    if not isinstance(ville, str):
        return None
    return MOTIF_ARRONDISSEMENT.sub("", ville.strip()).strip() or None


def preparer_offres(df):
    """Colonnes derivees, calculees une fois au chargement."""
    df = df.copy()
    jour = df["derniere_collecte"].max()
    df["jour_collecte"] = jour
    df["en_ligne"] = df["derniere_collecte"] == jour
    df["age_jours"] = (
        pd.to_datetime(jour) - pd.to_datetime(df["date_creation"])
    ).dt.days
    df["recente"] = df["en_ligne"] & (df["age_jours"] <= JOURS_RECENTS)
    df["persistante"] = df["jours_en_ligne"] > SEUIL_JOURS
    df["manque"] = df["manque"].fillna(False).astype(bool)
    df["competences"] = df["competences"].apply(
        lambda l: sorted(set(l)) if isinstance(l, (list, tuple)) else []
    )
    df["nb_requises"] = df["competences"].str.len()
    df["cle_ville"] = df["ville_normalisee"] + "|" + df["departement"]

    # Nom affiche : la forme la plus frequente, sans arrondissement.
    propre = df["ville"].map(_ville_affichee)
    noms = (
        propre.groupby(df["cle_ville"])
        .agg(lambda s: s.mode().iat[0] if not s.mode().empty else None)
    )
    df["ville_affichee"] = df["cle_ville"].map(noms).fillna(
        df["ville_normalisee"].str.title()
    )
    return df


def references(df):
    """Taux nationaux des deux signaux de penurie, sur toutes les offres."""
    return {
        "persistance": float(df["persistante"].mean()) if len(df) else 0.0,
        "manque": float(df["manque"].mean()) if len(df) else 0.0,
    }


# ------------------------------------------------------- croisement CV

def evaluer_offres(df, competences_cv, annees_cv):
    """Ajoute a chaque offre : competences communes, adequation, niveau."""
    mes = {c.lower() for c in competences_cv}
    df = df.copy()
    df["communes"] = df["competences"].apply(
        lambda req: [c for c in req if c.lower() in mes]
    )
    df["nb_communes"] = df["communes"].str.len()
    df["adequation"] = np.where(
        df["nb_requises"] > 0, df["nb_communes"] / df["nb_requises"].clip(lower=1), 0.0
    )
    seuil = np.minimum(MIN_COMMUNES, df["nb_requises"])
    df["compatible"] = (df["nb_requises"] > 0) & (df["nb_communes"] >= seuil)
    if annees_cv is None:
        df["hors_niveau"] = False
    else:
        df["hors_niveau"] = df["experience_annees"].fillna(0) > annees_cv + ECART_NIVEAU
    return df


# ------------------------------------------------------------- filtres

def distance_km(lat, lon, lat0, lon0):
    """Distance a vol d'oiseau (formule de haversine)."""
    lat, lon = np.radians(lat.astype(float)), np.radians(lon.astype(float))
    lat0, lon0 = math.radians(lat0), math.radians(lon0)
    a = (
        np.sin((lat - lat0) / 2) ** 2
        + np.cos(lat) * math.cos(lat0) * np.sin((lon - lon0) / 2) ** 2
    )
    return 12742 * np.arcsin(np.sqrt(a))


def centre_ville(df, cle_ville):
    lignes = df[df["cle_ville"] == cle_ville]
    return float(lignes["latitude"].mean()), float(lignes["longitude"].mean())


def masque_zone(df, zone):
    """zone = {'mode': 'france' | 'regions' | 'rayon', 'regions': [...],
    'centre': cle_ville, 'rayon': km}"""
    if zone["mode"] == "regions" and zone.get("regions"):
        return df["code_region"].isin(zone["regions"])
    if zone["mode"] == "rayon" and zone.get("centre"):
        lat0, lon0 = centre_ville(df, zone["centre"])
        if math.isnan(lat0):
            return pd.Series(True, index=df.index)
        return distance_km(df["latitude"], df["longitude"], lat0, lon0) <= zone["rayon"]
    return pd.Series(True, index=df.index)


def masque_contrat(df, contrat):
    if contrat == "CDI":
        return df["type_contrat"] == "CDI"
    if contrat == "CDI ou CDD":
        return df["type_contrat"].isin(["CDI", "CDD"])
    if contrat == "Alternance":
        return df["alternance"].fillna(False).astype(bool)
    return pd.Series(True, index=df.index)


def perimetre(df, postes, contrat, zone):
    """Offres des postes vises, du contrat voulu, dans la zone."""
    return df[
        df["id_poste"].isin(postes) & masque_contrat(df, contrat) & masque_zone(df, zone)
    ]


# --------------------------------------------------------------- score

def fiabilite(nb_offres):
    if nb_offres >= SEUIL_FIABLE:
        return "Fiable"
    if nb_offres >= SEUIL_INDICATIF:
        return "Indicatif"
    return "Fragile"


def etiquette(score, fiabilite_territoire="Fiable"):
    if fiabilite_territoire == "Fragile":
        return "Trop peu d'offres pour conclure"
    if score >= 65:
        return "Très bonne piste"
    if score >= 50:
        return "Bonne piste"
    return "Piste possible"


def _signal(evenements, offres, taux):
    """Taux d'un signal, lisse vers la moyenne nationale, rapporte a elle.

    L'a priori pese LISSAGE offres fictives, et au moins assez pour contenir
    EVENEMENTS_MINIMUM signaux attendus : un signal rare (3 % des offres)
    ne doit pas s'envoler parce qu'une ville de 2 offres en compte un.
    """
    poids = max(LISSAGE, EVENEMENTS_MINIMUM / taux)
    return (evenements + poids * taux) / (offres + poids) / taux


def penurie_depuis_indice(indice):
    """Indice de penurie -> note entre 0 et 1.

    Regle : la moyenne nationale (indice 1,0) vaut 0,5. Chaque point de
    signaux en plus ou en moins deplace la note d'autant : indice 1,5
    (50 % de signaux de plus que la moyenne) = 1 ; indice 0,5 = 0.
    Meme pente que l'ancienne formule (indice - 0,6), donc meme
    classement : seul le point de depart change, la moyenne vaut 50.
    """
    return (indice - 0.5).clip(0, 1)


def indice_penurie(offres, persistantes, manque, refs):
    """1,00 = marche moyen. Moyenne des deux signaux quand ils existent."""
    tp, tm = refs["persistance"], refs["manque"]
    signaux = []
    if tp > 0:
        signaux.append(_signal(persistantes, offres, tp))
    if tm > 0:
        signaux.append(_signal(manque, offres, tm))
    return sum(signaux) / len(signaux) if signaux else offres * 0 + 1.0


def noter_territoires(offres, niveau, refs, volume_max=None):
    """Score par region ('region') ou par ville ('ville').

    `offres` : offres du perimetre deja evaluees. Seules les offres
    compatibles et a la portee du candidat comptent.
    """
    retenues = offres[offres["compatible"] & ~offres["hors_niveau"]]
    if retenues.empty:
        return pd.DataFrame()

    cle = "code_region" if niveau == "region" else "cle_ville"
    g = retenues.groupby(cle)
    t = pd.DataFrame({
        "offres": g.size(),
        "persistantes": g["persistante"].sum(),
        "manque": g["manque"].sum(),
        "recentes": g["recente"].sum(),
        "mediane_jours": g["jours_en_ligne"].median(),
        "adequation": g["adequation"].mean(),
        "region": g["region"].first(),
        "code_region": g["code_region"].first(),
    })
    if niveau == "ville":
        t["libelle"] = g["ville_affichee"].first()
        t["departement"] = g["departement"].first()
        t["nb_villes"] = 1
    else:
        t["libelle"] = t["region"]
        t["departement"] = None
        t["nb_villes"] = g["cle_ville"].nunique()

    t["indice"] = indice_penurie(t["offres"], t["persistantes"], t["manque"], refs)

    t["penurie"] = penurie_depuis_indice(t["indice"])
    maxi = volume_max or t["offres"].max()
    t["volume"] = (np.log1p(t["offres"]) / np.log1p(maxi)).clip(upper=1)
    t["score"] = (
        100 * (
            POIDS["penurie"] * t["penurie"]
            + POIDS["adequation"] * t["adequation"]
            + POIDS["volume"] * t["volume"]
        )
    ).round().astype(int)
    t["fiabilite"] = t["offres"].map(fiabilite)
    t["part_persistantes"] = t["persistantes"] / t["offres"]
    t["part_manque"] = t["manque"] / t["offres"]
    t.index.name = "code"
    # Un territoire "Fragile" (moins de 10 offres) peut afficher un bon
    # score par hasard : il passe apres tous les autres dans le classement.
    t["_fragile"] = t["fiabilite"] == "Fragile"
    return (
        t.reset_index()
        .sort_values(["_fragile", "score"], ascending=[True, False])
        .drop(columns="_fragile")
    )


# --------------------------------------------- competences a apprendre

def competences_a_apprendre(offres, competences_cv, limite=5):
    """Competences absentes du CV qui ouvriraient le plus d'offres.

    debloque : offres aujourd'hui non compatibles qui le deviendraient.
    points   : gain moyen d'adequation au CV sur le perimetre, en points.
    """
    base = offres[(offres["nb_requises"] > 0) & ~offres["hors_niveau"]]
    if len(base) < MIN_OFFRES_CONSEIL:
        return pd.DataFrame(columns=["competence", "debloque", "points"])

    mes = {c.lower() for c in competences_cv}
    eclate = base[["competences", "nb_requises", "nb_communes", "compatible"]].explode(
        "competences"
    )
    eclate = eclate[~eclate["competences"].str.lower().isin(mes)]
    if eclate.empty:
        return pd.DataFrame(columns=["competence", "debloque", "points"])

    seuil = np.minimum(MIN_COMMUNES, eclate["nb_requises"])
    eclate["debloque"] = (~eclate["compatible"]) & (eclate["nb_communes"] + 1 >= seuil)
    eclate["gain"] = 1 / eclate["nb_requises"]

    r = eclate.groupby("competences").agg(
        debloque=("debloque", "sum"), gain=("gain", "sum")
    )
    r["points"] = (100 * r["gain"] / len(base)).round(1)
    r["rang"] = r["debloque"] + 3 * r["points"]
    r = r.sort_values("rang", ascending=False).head(limite)
    return r.reset_index().rename(columns={"competences": "competence"})[
        ["competence", "debloque", "points"]
    ]


# ------------------------------------------------- offres d'une ville

def noter_groupe(offres, cles_villes, refs, volume_max):
    """Score d'un ensemble de villes, comme s'il s'agissait d'un territoire."""
    groupe = offres[offres["cle_ville"].isin(cles_villes)].copy()
    groupe["cle_ville"] = "selection"
    t = noter_territoires(groupe, "ville", refs, volume_max)
    return None if t.empty else t.iloc[0]


def offres_de_la_ville(offres, cles_villes, a_apprendre):
    """Offres affichables d'une ou plusieurs villes, en deux groupes.

    Groupe 1 : accessibles avec le CV actuel. Groupe 2 : demandent au
    moins une des competences recommandees. Dans chaque groupe, tri par
    adequation puis fraicheur.
    """
    o = offres[
        offres["cle_ville"].isin(cles_villes)
        & offres["compatible"]
        & ~offres["hors_niveau"]
        & offres["en_ligne"]
    ].copy()
    apprendre = set(a_apprendre)
    o["a_apprendre"] = o.apply(
        lambda r: [c for c in r["competences"] if c in apprendre and c not in r["communes"]],
        axis=1,
    ) if not o.empty else []
    o["groupe"] = np.where(o["a_apprendre"].str.len() > 0, 2, 1) if not o.empty else []
    o = o.sort_values(["groupe", "adequation", "age_jours"], ascending=[True, False, True])

    ecartees = int(
        (
            offres["cle_ville"].isin(cles_villes)
            & offres["compatible"]
            & offres["hors_niveau"]
            & offres["en_ligne"]
        ).sum()
    )
    return o[o["recente"]], o[~o["recente"]], ecartees


# ------------------------------------------------- postes recommandes

def recommander_postes(offres, refs, postes_libelles, exemples=3):
    """Classe les familles de postes selon les chances du candidat.

    `offres` : offres evaluees (CV croise), filtrees sur la zone et le
    contrat mais PAS sur les postes. Meme formule que pour un territoire :
    penurie, adequation au CV, volume d'offres compatibles.
    """
    retenues = offres[
        offres["id_poste"].notna() & offres["compatible"] & ~offres["hors_niveau"]
    ]
    if retenues.empty:
        return pd.DataFrame()

    g = retenues.groupby("id_poste")
    r = pd.DataFrame({
        "offres": g.size(),
        "persistantes": g["persistante"].sum(),
        "manque": g["manque"].sum(),
        "recentes": g["recente"].sum(),
        "adequation": g["adequation"].mean(),
        "region": None,
        "code_region": None,
    })

    r["indice"] = indice_penurie(r["offres"], r["persistantes"], r["manque"], refs)
    r["penurie"] = penurie_depuis_indice(r["indice"])
    r["volume"] = np.log1p(r["offres"]) / np.log1p(r["offres"].max())
    r["score"] = (
        100 * (
            POIDS["penurie"] * r["penurie"]
            + POIDS["adequation"] * r["adequation"]
            + POIDS["volume"] * r["volume"]
        )
    ).round().astype(int)
    r["fiabilite"] = r["offres"].map(fiabilite)
    r["libelle"] = r.index.map(postes_libelles)

    # Exemples : les intitules reels les plus frequents, nettoyes du "(H/F)".
    propres = (
        retenues["intitule"].fillna("")
        .str.replace(r"\s*[\(\[]?\s*[hf]\s*/\s*[hf]\s*[\)\]]?\s*", " ", regex=True, case=False)
        .str.replace(r"\s+", " ", regex=True).str.strip(" -–")
    )
    r["exemples"] = (
        propres.groupby(retenues["id_poste"])
        .agg(lambda s: s[s != ""].value_counts().head(exemples).index.tolist())
    )

    r.index.name = "id_poste"
    r["_fragile"] = r["fiabilite"] == "Fragile"
    return (
        r.reset_index()
        .sort_values(["_fragile", "score"], ascending=[True, False])
        .drop(columns="_fragile")
    )