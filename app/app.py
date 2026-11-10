"""
Detecteur de niches IT — application finale.

Parcours en 3 etapes : Mon CV -> Territoires -> Offres.

L'entrepot fournit les offres (DAG Airflow). L'application ne fait que
lire : elle croise les offres avec le CV du candidat (calculs.py) et
affiche le resultat. Le CV n'est jamais enregistre.
"""

import os
from html import escape
from urllib.parse import quote

import pandas as pd
import psycopg2
import streamlit as st

import calculs as c
import style as s
from cv import CVIlisible, analyser_cv
from transformation import charger_categories, charger_dictionnaire, charger_postes

st.set_page_config(
    page_title="Détecteur de niches IT",
    layout="wide",
)
st.markdown(s.CSS, unsafe_allow_html=True)

POSTES = {f["id"]: f["libelle"] for f in charger_postes()}
CATEGORIE_DU_POSTE = {f["id"]: f["categorie"] for f in charger_postes()}
CATEGORIES = {cat: libelle for cat, libelle, _ in charger_categories()}
POSTES_PAR_CATEGORIE = {cat: list(postes) for cat, _, postes in charger_categories()}
TOUTES_COMPETENCES = sorted({lib for lib, _, _ in charger_dictionnaire()}, key=str.lower)
PRESETS = {
    "Île-de-France": ["11"],
    "Le Sud": ["76", "93", "75", "94"],
    "Grand Ouest": ["53", "52", "28"],
    "Le Nord": ["32", "28", "11"],
    "L'Est": ["44", "27", "84"],
}


# ================================================================ donnees

# Table preparee chaque jour par dbt (dbt/models/marts/mart_offres_candidat.sql).
REQUETE_MART = "SELECT * FROM analytique.mart_offres_candidat"

# Meme resultat calcule directement sur l'etoile : utilise tant que dbt
# n'a pas encore tourne (premiere installation).
REQUETE_OFFRES = """
SELECT f.id_offre, f.intitule, f.url_offre, f.id_poste, f.date_creation,
       f.jours_en_ligne, f.derniere_collecte,
       COALESCE(f.manque_candidats, FALSE) AS manque,
       f.experience_annees::float AS experience_annees,
       f.salaire_min::float AS salaire_min, f.salaire_max::float AS salaire_max,
       f.salaire_periode,
       l.ville, l.ville_normalisee, l.departement,
       l.latitude::float AS latitude, l.longitude::float AS longitude,
       d.code_region, r.nom AS region,
       e.nom AS entreprise, ct.type_contrat, ct.alternance,
       ARRAY_REMOVE(ARRAY_AGG(cp.libelle), NULL) AS competences
FROM fait_offre f
JOIN dim_lieu l ON l.code_insee = f.code_insee
JOIN ref_departement d ON d.departement = l.departement
JOIN ref_region r ON r.code_region = d.code_region
LEFT JOIN dim_entreprise e ON e.id_entreprise = f.id_entreprise
LEFT JOIN dim_contrat ct ON ct.id_contrat = f.id_contrat
LEFT JOIN pont_offre_competence p ON p.id_offre = f.id_offre
LEFT JOIN dim_competence cp ON cp.id_competence = p.id_competence
WHERE l.ville_normalisee IS NOT NULL
  AND NOT f.hors_perimetre
GROUP BY f.id_offre, l.code_insee, d.code_region, r.nom, e.nom,
         ct.type_contrat, ct.alternance
"""

REQUETE_REGIONS = """
SELECT code_region AS code, nom, abrev, grille_ligne, grille_col FROM ref_region
"""


def lire(requete):
    with psycopg2.connect(
        host=os.getenv("DWH_HOST", "postgres-dwh"),
        port=os.getenv("DWH_PORT", "5432"),
        dbname=os.getenv("DWH_DB"),
        user=os.getenv("DWH_USER"),
        password=os.getenv("DWH_PASSWORD"),
    ) as conn, conn.cursor() as cur:
        cur.execute(requete)
        colonnes = [d[0] for d in cur.description]
        return pd.DataFrame(cur.fetchall(), columns=colonnes)


@st.cache_data(ttl=600, show_spinner="Chargement des offres…")
def charger():
    try:
        brut = lire(REQUETE_MART)
    except psycopg2.errors.UndefinedTable:
        brut = lire(REQUETE_OFFRES)
    offres = c.preparer_offres(brut)
    regions = lire(REQUETE_REGIONS)
    return offres, regions


try:
    OFFRES, REGIONS = charger()
except psycopg2.Error as erreur:
    st.markdown(s.bandeau(1), unsafe_allow_html=True)
    st.error(
        "L'entrepôt n'est pas encore prêt pour cette version de l'application. "
        "Lance le DAG **chargement_gold** dans Airflow, puis recharge la page."
    )
    st.caption(f"Détail technique : {erreur.pgerror or erreur}")
    st.stop()

if OFFRES.empty:
    st.markdown(s.bandeau(1), unsafe_allow_html=True)
    st.warning("Aucune offre dans l'entrepôt. Lance la collecte puis le chargement dans Airflow.")
    st.stop()

REFS = c.references(OFFRES)
NOMS_REGIONS = dict(zip(REGIONS["code"], REGIONS["nom"]))
VILLES_CONNUES = (
    OFFRES.groupby("cle_ville")
    .agg(nom=("ville_affichee", "first"), dept=("departement", "first"), n=("id_offre", "size"))
    .sort_values("n", ascending=False)
)


# ================================================================== etat

def init_etat():
    defauts = {
        "etape": 1,
        "competences": [],
        "annees": 2.0,
        "postes": ["de", "da", "cd"],
        "contrat": "Tous",
        "zone_mode": "Toute la France",
        "zone_regions": ["11"],
        "zone_centre": VILLES_CONNUES.index[0],
        "zone_rayon": 50,
        "regions_sel": [],
        "villes_sel": [],
        "cv_nom": None,
        "cv_infos": None,
        "niveau": "Régions",
        "anciennes": False,
        "nav": 0,
    }
    for cle, valeur in defauts.items():
        st.session_state.setdefault(cle, valeur)


init_etat()
E = st.session_state

# Streamlit efface l'etat d'un widget absent de l'ecran. Le profil saisi a
# l'etape 1 doit survivre aux etapes 2 et 3 : on le reaffecte a chaque tour.
for _cle in ("competences", "annees", "postes", "zone_mode", "zone_regions",
             "zone_centre", "zone_rayon", "contrat", "niveau", "anciennes"):
    E[_cle] = E[_cle]


def aller(etape, **valeurs):
    for cle, valeur in valeurs.items():
        E[cle] = valeur
    E["etape"] = etape
    # Nouvelles cles pour les tableaux : une ligne selectionnee avant de
    # changer d'ecran ne doit pas renvoyer aussitot vers l'ecran suivant.
    E["nav"] = E.get("nav", 0) + 1


def zone():
    mode = {"Des régions": "regions", "Autour d'une ville": "rayon"}.get(E.zone_mode, "france")
    return {"mode": mode, "regions": E.zone_regions, "centre": E.zone_centre, "rayon": E.zone_rayon}


def libelle_zone():
    z = zone()
    if z["mode"] == "regions":
        return ", ".join(NOMS_REGIONS.get(r, r) for r in z["regions"]) or "Aucune région"
    if z["mode"] == "rayon":
        return f"À {z['rayon']} km autour de {VILLES_CONNUES.loc[z['centre'], 'nom']}"
    return "Toute la France"


def pct(x):
    """0.456 -> '46 %' (espace insecable, a la francaise)."""
    return f"{round(100 * x)}\u00a0%"


def mot(n, singulier, pluriel=None):
    return f"{n} {singulier if n == 1 else (pluriel or singulier + 's')}"


# ============================================================== calculs

def calculer():
    """Tout ce qui depend du candidat, recalcule a chaque interaction."""
    evaluees = c.evaluer_offres(OFFRES, E.competences, E.annees)
    perim = c.perimetre(evaluees, E.postes, E.contrat, {"mode": "france"})
    dans_zone = c.masque_zone(perim, zone())
    return {
        "perimetre": perim,
        "zone": perim[dans_zone],
        "regions": c.noter_territoires(perim, "region", REFS),
        "villes": c.noter_territoires(perim, "ville", REFS),
        "villes_zone": set(perim.loc[dans_zone, "cle_ville"]),
        "regions_zone": set(perim.loc[dans_zone, "code_region"]),
    }


def bloc_apprendre(offres, titre):
    a = c.competences_a_apprendre(offres, E.competences)
    if a.empty:
        n = int((~offres["hors_niveau"]).sum()) if len(offres) else 0
        if n < c.MIN_OFFRES_CONSEIL:
            st.markdown(
                f'<div class="dn-carte"><h3 style="font-size:17px;margin:0">{escape(titre)}</h3>'
                f'<p class="dn-muted" style="margin:8px 0 0">Trop peu d\'offres ici ({n}) pour conseiller '
                "des compétences. Regarde les conseils de la région ou de toute ta zone.</p></div>",
                unsafe_allow_html=True,
            )
        return
    rang = a["debloque"] + 3 * a["points"]
    maxi = max(rang.max(), 1e-9)
    lignes = "".join(
        s.barre(
            r.competence, (r.debloque + 3 * r.points) / maxi, s.VERT_BARRE,
            f"+{r.points:g} pts" + (f" · +{mot(int(r.debloque), 'offre')}" if r.debloque else ""),
        )
        for r in a.itertuples()
    )
    st.markdown(
        f'<div class="dn-carte"><div class="dn-groupe" style="margin-top:0"><h3>{escape(titre)}</h3>'
        f'<span class="dn-eyebrow">Absentes de ton CV</span></div>{lignes}'
        '<p class="dn-muted" style="margin:10px 0 0;font-size:12.5px">« +pts » : gain moyen d\'adéquation '
        'à ton CV. « +offres » : offres qui deviendraient compatibles.</p></div>',
        unsafe_allow_html=True,
    )


# ============================================================== etape 1

def definir_postes(postes):
    """Postes vises : la liste de reference et les selecteurs par categorie."""
    E.postes = list(dict.fromkeys(postes))
    for cat, ids in POSTES_PAR_CATEGORIE.items():
        E[f"cat_{cat}"] = [p for p in ids if p in E.postes]


def synchroniser_postes():
    """Appele quand on coche ou decoche un poste dans une categorie."""
    E.postes = [p for cat in CATEGORIES for p in E.get(f"cat_{cat}", [])]


def ajouter_poste(id_poste):
    if id_poste not in E.postes:
        definir_postes(E.postes + [id_poste])


def bloc_postes_recommandes():
    """Familles de postes classees selon les chances du candidat."""
    evaluees = c.evaluer_offres(OFFRES, E.competences, E.annees)
    perim = evaluees[c.masque_contrat(evaluees, E.contrat) & c.masque_zone(evaluees, zone())]
    reco = c.recommander_postes(perim, REFS, POSTES)
    if reco.empty:
        return

    with st.container(border=True):
        st.markdown(
            '<div class="dn-groupe" style="margin-top:0"><h3>Postes recommandés pour ton profil</h3>'
            f'<span class="dn-eyebrow">{escape(libelle_zone())}</span></div>',
            unsafe_allow_html=True,
        )
        for r in reco.head(6).itertuples():
            texte, action = st.columns([4, 1.3], vertical_alignment="center")
            exemples = " · ".join(escape(x) for x in r.exemples) or "—"
            texte.markdown(
                f'<div style="padding:4px 0"><span class="dn-eyebrow">{escape(CATEGORIES.get(CATEGORIE_DU_POSTE.get(r.id_poste), ""))}</span><br>'
                f'<b>{escape(r.libelle)}</b>{s.badge(r.fiabilite)}'
                f'<span style="float:right;font:800 18px Sora,sans-serif;color:{s.BORDEAUX_FONCE}">{r.score}<span style="font-size:13px;font-weight:600">\u00a0/\u00a0100</span></span>'
                f'<div class="dn-muted" style="font-size:13px">{mot(int(r.offres), "offre compatible", "offres compatibles")} · '
                f'adéquation {pct(r.adequation)} · pénurie {pct(r.penurie)}</div>'
                f'<div class="dn-muted" style="font-size:12.5px;font-style:italic">Ex. : {exemples}</div></div>',
                unsafe_allow_html=True,
            )
            if r.id_poste in E.postes:
                action.markdown('<span class="dn-pill neuve" style="margin:0">✓ Choisi</span>', unsafe_allow_html=True)
            else:
                action.button("Ajouter", key=f"ajout_{r.id_poste}", on_click=ajouter_poste, args=(r.id_poste,))
        st.caption(
            "Même calcul que pour les villes : pénurie, adéquation à ton CV et nombre d'offres, "
            "dans ta zone et pour le contrat choisi."
        )


def etape_cv():
    st.markdown(
        '<span class="dn-eyebrow">Étape 1 sur 3</span>', unsafe_allow_html=True
    )
    st.title("Ton CV, lu compétence par compétence")
    st.markdown(
        '<p class="dn-muted">Dépose ton CV : on repère tes technologies avec le même dictionnaire '
        "que celui qui lit les offres, pour que la comparaison soit juste. Ton CV n'est pas "
        "enregistré. Corrige la liste si besoin.</p>",
        unsafe_allow_html=True,
    )

    gauche, droite = st.columns([1.1, 1], gap="large")

    with gauche:
        fichier = st.file_uploader("Ton CV (PDF ou Word)", type=["pdf", "docx"])
        if fichier is not None and fichier.name != E.cv_nom:
            try:
                infos = analyser_cv(fichier.getvalue(), fichier.name)
            except CVIlisible as erreur:
                st.error(str(erreur))
            except Exception:
                st.error("Impossible de lire ce fichier. Essaie de le réexporter en PDF.")
            else:
                E.cv_nom, E.cv_infos = fichier.name, infos
                E.competences = infos["competences"]
                definir_postes(infos["postes"])
                if infos["experience_annees"] is not None:
                    E.annees = float(min(infos["experience_annees"], 40))
                st.rerun()

        if E.cv_infos:
            i = E.cv_infos
            exp = f"{i['experience_annees']:g} ans" if i["experience_annees"] is not None else "non trouvée"
            note = "" if i["experience_fiable"] else " (rubrique expérience non repérée, vérifie)"
            st.markdown(
                f'<div class="dn-carte"><span class="dn-eyebrow">Analysé · {escape(E.cv_nom)}</span>'
                f'<p style="margin:8px 0 0">{mot(len(i["competences"]), "compétence reconnue", "compétences reconnues")} · '
                f'expérience {exp}{note} · diplôme {i["diplome"] or "non trouvé"}</p></div>',
                unsafe_allow_html=True,
            )

        st.multiselect(
            "Tes compétences",
            options=sorted(set(TOUTES_COMPETENCES) | set(E.competences), key=str.lower),
            key="competences",
            help="Ajoute ou retire des compétences. Tu peux aussi tout saisir à la main, sans CV.",
        )
        st.number_input(
            "Tes années d'expérience", min_value=0.0, max_value=40.0, step=0.5, key="annees",
            help=f"Les offres qui demandent plus de {c.ECART_NIVEAU} ans au-delà sont écartées.",
        )

    with droite:
        st.markdown("#### Postes visés")
        proposes = set((E.cv_infos or {}).get("postes", []))
        for cat, libelle in CATEGORIES.items():
            cle = f"cat_{cat}"
            if cle not in E:
                E[cle] = [p for p in POSTES_PAR_CATEGORIE[cat] if p in E.postes]
            st.pills(
                libelle, options=POSTES_PAR_CATEGORIE[cat],
                format_func=lambda p: ("★ " if p in proposes else "") + POSTES[p],
                selection_mode="multi", key=cle, on_change=synchroniser_postes,
            )
        st.caption(
            ("★ proposé à partir de ton CV. " if proposes else "")
            + "Choisis un ou plusieurs postes, dans une ou plusieurs catégories."
        )

        st.markdown("#### Où chercher ?")
        st.segmented_control(
            "Zone", ["Toute la France", "Des régions", "Autour d'une ville"],
            key="zone_mode", label_visibility="collapsed",
        )
        if E.zone_mode == "Des régions":
            choix = st.pills("Raccourcis", list(PRESETS), selection_mode="single", key="preset")
            if choix and sorted(PRESETS[choix]) != sorted(E.zone_regions):
                E.zone_regions = PRESETS[choix]
                st.rerun()
            st.multiselect(
                "Régions", options=list(NOMS_REGIONS), format_func=NOMS_REGIONS.get,
                key="zone_regions",
            )
        elif E.zone_mode == "Autour d'une ville":
            col1, col2 = st.columns([1.2, 1])
            col1.selectbox(
                "Ville de départ", options=list(VILLES_CONNUES.index),
                format_func=lambda k: f"{VILLES_CONNUES.loc[k, 'nom']} ({VILLES_CONNUES.loc[k, 'dept']})",
                key="zone_centre",
            )
            col2.slider("Rayon (km)", 10, 150, step=10, key="zone_rayon")

        st.selectbox("Contrat", ["Tous", "CDI", "CDI ou CDD", "Alternance"], key="contrat")

    if not E.competences:
        st.info("Dépose ton CV ou ajoute tes compétences pour continuer.")
        return

    with gauche:
        bloc_postes_recommandes()

    if not E.postes:
        st.warning("Choisis au moins un poste visé, ou ajoute un poste recommandé.")
        return

    r = calculer()
    with droite:
        bloc_apprendre(r["zone"], "Compétences qui t'ouvriraient le plus d'offres")
    st.button(
        "Voir où mon profil est recherché →", type="primary",
        on_click=aller, args=(2,), kwargs={"regions_sel": []},
    )


# ============================================================== etape 2

def tableau_classement(lignes, niveau, cle):
    vue = pd.DataFrame({
        "Territoire": lignes["libelle"] + (
            " (" + lignes["departement"].astype(str) + ")" if niveau == "ville" else ""
        ),
        "Fiabilité": lignes["fiabilite"],
        "Offres": lignes["offres"],
        "< 14 j": lignes["recentes"].astype(int),
        "Pénurie": (lignes["penurie"] * 100).round().astype(int),
        "Opportunité": lignes["score"],
    })
    return st.dataframe(
        vue, hide_index=True, use_container_width=True, key=cle,
        on_select="rerun", selection_mode="multi-row",
        column_config={
            "Pénurie": st.column_config.NumberColumn(format="%d %%", help="0 % = recrutements faciles, 100 % = forte pénurie"),
            "Opportunité": st.column_config.ProgressColumn(
                format="%d / 100", min_value=0, max_value=100,
                help="Score sur 100. Ce n'est pas une probabilité d'embauche.",
            ),
            "< 14 j": st.column_config.NumberColumn(help="Offres publiées depuis moins de 14 jours"),
        },
    )


def etape_territoires():
    r = calculer()
    if r["villes"].empty:
        st.warning(
            "Aucune offre ne correspond à ton profil avec ces critères. Ajoute des compétences, "
            "d'autres postes, ou élargis la zone."
        )
        st.button("← Modifier mon profil", on_click=aller, args=(1,))
        return

    choisies = E.regions_sel or []
    villes = r["villes"][r["villes"]["code"].isin(r["villes_zone"])]
    regions = r["regions"][r["regions"]["code"].isin(r["regions_zone"])]
    if choisies:
        villes = villes[villes["code_region"].isin(choisies)]
    zone_offres = r["zone"] if not choisies else r["zone"][r["zone"]["code_region"].isin(choisies)]
    retenues = zone_offres[zone_offres["compatible"] & ~zone_offres["hors_niveau"]]
    noms_choisies = ", ".join(NOMS_REGIONS.get(x, x) for x in choisies)

    st.markdown('<span class="dn-eyebrow">Étape 2 sur 3</span>', unsafe_allow_html=True)
    st.title(
        f"{noms_choisies} : les villes" if choisies
        else ("Où ton profil a le plus de chances" if zone()["mode"] == "france"
              else "Les meilleures pistes dans ta zone")
    )
    st.markdown(
        f'<p class="dn-muted"><b>{escape(libelle_zone())}</b> · pour '
        f'{escape(", ".join(POSTES[p] for p in E.postes))}. Score d\'opportunité sur 100 : '
        "pénurie de candidats, adéquation à ton CV et volume d'offres. Coche une ou plusieurs lignes du "
        "classement, ou prends toute la liste.</p>",
        unsafe_allow_html=True,
    )

    k1, k2, k3, k4 = st.columns(4)
    n = len(retenues)
    k1.metric("Offres compatibles", f"{n:,}".replace(",", " "), help="À ton niveau, 2 compétences communes ou plus")
    k2.metric("En ligne, < 14 jours", int(retenues["recente"].sum()))
    if n:
        k3.metric(
            "Signaux de pénurie",
            f"{pct(retenues['persistante'].mean())} · {pct(retenues['manque'].mean())}",
            help="En ligne depuis plus de 30 jours · signalées « manque de candidats »",
        )
    jour = OFFRES["jour_collecte"].iloc[0]
    k4.metric("Dernière collecte", pd.to_datetime(jour).strftime("%d/%m/%Y"))

    gauche, droite = st.columns([1, 1.25], gap="large")
    with gauche:
        notes = dict(zip(r["regions"]["code"], r["regions"]["score"]))
        lignes = [
            {**reg, "score": notes.get(reg["code"])}
            for reg in REGIONS.to_dict("records")
        ]
        st.markdown(
            '<div class="dn-carte"><h3 style="font-size:17px;margin:0">Carte des régions</h3>'
            + s.mini_carte(lignes, r["regions_zone"]) + "</div>",
            unsafe_allow_html=True,
        )
        bloc_apprendre(
            zone_offres,
            f"À apprendre pour {noms_choisies}" if choisies else "À apprendre dans ta zone",
        )

    with droite:
        haut = st.columns([1, 1])
        haut[0].markdown("#### Classement")
        par_region = not choisies and zone()["mode"] != "rayon" and len(regions) > 1
        if par_region:
            haut[1].segmented_control(
                "Niveau", ["Régions", "Villes"], key="niveau", label_visibility="collapsed"
            )
        if choisies:
            haut[1].button("← Toute la zone", on_click=aller, args=(2,), kwargs={"regions_sel": []})

        if par_region and E.niveau != "Villes":
            liste = regions.head(20)
            choix = tableau_classement(liste, "region", f"tab_regions_{E.nav}")
            cochees = liste.iloc[choix.selection.rows]["code"].tolist()
            villes_cochees = villes[villes["code_region"].isin(cochees)]["code"].tolist()
            b1, b2 = st.columns(2)
            b1.button(
                f"Voir les villes ({len(cochees)} région{'s' if len(cochees) > 1 else ''})",
                disabled=not cochees, use_container_width=True,
                on_click=aller, args=(2,), kwargs={"regions_sel": cochees},
            )
            b2.button(
                f"Toutes leurs offres ({mot(len(villes_cochees), 'ville')}) →", type="primary",
                disabled=not cochees, use_container_width=True,
                on_click=aller, args=(3,), kwargs={"villes_sel": villes_cochees, "anciennes": False},
            )
            st.caption("Coche une ou plusieurs régions, puis choisis : détail des villes, ou toutes les offres d'un coup.")
        else:
            liste = villes.head(60)
            choix = tableau_classement(liste, "ville", f"tab_villes_{'-'.join(choisies)}_{E.niveau}_{E.nav}")
            cochees = liste.iloc[choix.selection.rows]["code"].tolist()
            b1, b2 = st.columns(2)
            b1.button(
                f"Offres des villes cochées ({len(cochees)}) →", type="primary",
                disabled=not cochees, use_container_width=True,
                on_click=aller, args=(3,), kwargs={"villes_sel": cochees, "anciennes": False},
            )
            b2.button(
                f"Toutes les villes de la liste ({len(liste)}) →",
                use_container_width=True,
                on_click=aller, args=(3,), kwargs={"villes_sel": liste["code"].tolist(), "anciennes": False},
            )
            st.caption("Coche une ou plusieurs villes, ou prends toute la liste.")

        st.caption(
            "Fiabilité : Fiable à partir de 30 offres, Indicatif de 10 à 29, Fragile en dessous."
        )

        if zone()["mode"] != "france" and not villes.empty:
            ailleurs = r["villes"][~r["villes"]["code"].isin(r["villes_zone"])]
            ailleurs = ailleurs[ailleurs["fiabilite"] != "Fragile"]
            if not ailleurs.empty and ailleurs.iloc[0]["score"] > villes["score"].max():
                meilleure = ailleurs.iloc[0]
                st.markdown(
                    f'<div class="dn-encart">Hors de ta zone : <b>{escape(meilleure["libelle"])}</b> '
                    f'({escape(meilleure["region"])}) atteint <b>{meilleure["score"]} / 100</b>.</div>',
                    unsafe_allow_html=True,
                )
                st.button(
                    "Voir quand même", on_click=aller, args=(3,),
                    kwargs={"villes_sel": [meilleure["code"]], "anciennes": False},
                )

    st.button("← Modifier mon profil", on_click=aller, args=(1,))


# ============================================================== etape 3

def carte_offre(o):
    ville = o.ville_affichee or ""
    puces = "".join(
        f'<span class="dn-puce">✓ {escape(x)}</span>' if x in o.communes
        else f'<span class="dn-puce apprendre">+ {escape(x)}</span>' if x in o.a_apprendre
        else f'<span class="dn-puce manque">{escape(x)}</span>'
        for x in o.competences
    )
    if o.persistante or pd.isna(o.age_jours):
        age = f'<span class="dn-pill dure">{o.jours_en_ligne} j · difficile à pourvoir</span>'
    else:
        age = f'<span class="dn-pill neuve">il y a {mot(int(o.age_jours), "jour")}</span>'
    manque = '<span class="dn-pill dure">manque de candidats</span>' if o.manque else ""

    meta = [POSTES.get(o.id_poste, ""), o.entreprise, o.type_contrat]
    if o.experience_annees is not None and not pd.isna(o.experience_annees):
        meta.append("Débutant accepté" if o.experience_annees == 0 else f"{o.experience_annees:g} an(s) d'exp.")
    meta.append(f"{ville} ({o.departement})")
    if pd.notna(o.salaire_min) and o.salaire_periode == "annuel":
        meta.append(f"{o.salaire_min / 1000:.0f}–{(o.salaire_max if pd.notna(o.salaire_max) else o.salaire_min) / 1000:.0f} k€")
    elif pd.notna(o.salaire_min) and o.salaire_periode == "mensuel":
        meta.append(f"{o.salaire_min:,.0f} € / mois".replace(",", " "))
    meta = " · ".join(escape(str(m)) for m in meta if m)

    linkedin = (
        "https://www.linkedin.com/jobs/search/?keywords="
        + quote(f"{o.intitule} {o.entreprise or ''}".strip())
        + "&location=" + quote(ville)
    )
    voir = (
        f'<a class="dn-bouton plein" href="{escape(o.url_offre)}" target="_blank" rel="noopener">Voir l\'offre</a>'
        if o.url_offre else ""
    )
    return (
        f'<div class="dn-carte dn-offre"><div style="min-width:0"><h4>{escape(o.intitule or "")}{age}{manque}</h4>'
        f'<div class="dn-meta">{meta}</div><div class="dn-puces">{puces}</div></div>'
        f'<div class="dn-cote"><div class="dn-match">{pct(o.adequation)}<small>{o.nb_communes}/{o.nb_requises} compétences</small></div>'
        f'<div class="dn-boutons">{voir}<a class="dn-bouton vide" href="{linkedin}" target="_blank" rel="noopener">LinkedIn</a></div></div></div>'
    )


def groupes(offres):
    for numero, titre, detail in (
        (1, "Avec tes compétences actuelles", "aucune compétence recommandée manquante"),
        (2, "En apprenant une compétence recommandée", "compétence à apprendre en pointillés verts"),
    ):
        g = offres[offres["groupe"] == numero]
        st.markdown(
            f'<div class="dn-groupe"><h3>{titre}</h3><span class="dn-muted">'
            f'{mot(len(g), "offre")} · {detail}</span></div>',
            unsafe_allow_html=True,
        )
        if g.empty:
            st.markdown('<p class="dn-muted">Aucune offre dans ce groupe.</p>', unsafe_allow_html=True)
        for o in g.itertuples():
            st.markdown(carte_offre(o), unsafe_allow_html=True)


def titre_selection(lignes):
    """'Paris (75)' pour une ville, 'Paris, Nanterre et 4 autres' sinon."""
    if len(lignes) == 1:
        v = lignes.iloc[0]
        return f'{v["libelle"]} ({v["departement"]})'
    noms = lignes.sort_values("offres", ascending=False)["libelle"].tolist()
    if len(noms) <= 3:
        return ", ".join(noms[:-1]) + " et " + noms[-1]
    return f'{", ".join(noms[:2])} et {len(noms) - 2} autres villes'


def etape_offres():
    if not E.villes_sel:
        st.info("Choisis d'abord une ou plusieurs villes dans le classement.")
        st.button("← Retour au classement", on_click=aller, args=(2,))
        return

    r = calculer()
    lignes = r["villes"][r["villes"]["code"].isin(E.villes_sel)]
    if lignes.empty:
        st.warning("Plus aucune offre compatible dans ces villes avec tes critères actuels.")
        st.button("← Retour au classement", on_click=aller, args=(2,))
        return

    cles = lignes["code"].tolist()
    une_seule = len(cles) == 1
    volume_max = r["villes"]["offres"].max()
    v = lignes.iloc[0] if une_seule else c.noter_groupe(r["perimetre"], cles, REFS, volume_max)
    offres_sel = r["perimetre"][r["perimetre"]["cle_ville"].isin(cles)]
    regions_sel = sorted(lignes["region"].unique())

    tete = st.columns([3, 1])
    tete[0].markdown(
        f'<span class="dn-eyebrow">Étape 3 sur 3 · {escape(", ".join(regions_sel))}</span>',
        unsafe_allow_html=True,
    )
    tete[0].markdown(
        f'<h1 class="dn-titre" style="margin:4px 0 0">{escape(titre_selection(lignes))}'
        f'{s.badge(v["fiabilite"])}</h1>',
        unsafe_allow_html=True,
    )
    if not une_seule:
        tete[0].caption(
            f"{len(cles)} villes : " + ", ".join(
                lignes.sort_values("offres", ascending=False)["libelle"].tolist()
            )
        )
    tete[1].button("← Retour au classement", on_click=aller, args=(2,))

    gauche, droite = st.columns([1, 1.2], gap="large")
    with gauche:
        commentaire = (
            "Marché tendu : les employeurs ont plus de mal qu'ailleurs à recruter."
            if v["indice"] > 1.15 else
            "Marché fluide : les postes se pourvoient vite, postule tôt."
            if v["indice"] < 0.95 else
            "Pénurie proche de la moyenne nationale."
        )
        if v["fiabilite"] != "Fiable":
            commentaire += " Peu d'offres ici : à lire comme une tendance."
        st.markdown(
            '<div class="dn-carte"><span class="dn-eyebrow">Opportunité'
            + ("" if une_seule else " de ta sélection") + "</span>"
            '<div style="display:flex;gap:18px;align-items:center;flex-wrap:wrap;margin-top:8px">'
            + s.jauge(int(v["score"]))
            + f'<div style="flex:1;min-width:160px"><span class="dn-pill dure" style="margin:0">{c.etiquette(v["score"], v["fiabilite"])}</span>'
            f'<p class="dn-muted" style="margin:8px 0 0">{commentaire}</p></div></div>'
            + s.barre("Pénurie", v["penurie"], s.BRIQUE, pct(v["penurie"]))
            + s.barre("Adéquation CV", v["adequation"], s.VERT_BARRE, pct(v["adequation"]))
            + s.barre("Volume", v["volume"], s.BORDEAUX, mot(int(v["offres"]), "offre"))
            + f'<p class="dn-muted" style="margin:12px 0 0">{pct(v["part_persistantes"])} des offres encore en ligne '
            f'après 30 jours · {pct(v["part_manque"])} signalées « manque de candidats ».</p></div>',
            unsafe_allow_html=True,
        )
    with droite:
        bloc_apprendre(
            offres_sel,
            f"À apprendre pour {v['libelle']}" if une_seule else "À apprendre pour ta sélection",
        )

    recommandees = c.competences_a_apprendre(offres_sel, E.competences, limite=3)["competence"].tolist()

    cle_filtres = abs(hash(tuple(sorted(cles))))
    filtre = st.pills(
        "Poste", ["Tous mes postes"] + E.postes,
        format_func=lambda p: POSTES.get(p, p), default="Tous mes postes", key=f"filtre_{cle_filtres}",
    )
    if filtre and filtre != "Tous mes postes":
        offres_sel = offres_sel[offres_sel["id_poste"] == filtre]
    if not une_seule:
        noms = dict(zip(lignes["code"], lignes["libelle"] + " (" + lignes["departement"].astype(str) + ")"))
        ville_filtre = st.selectbox(
            "Ville", ["Toutes les villes"] + cles,
            format_func=lambda k: noms.get(k, k), key=f"ville_{cle_filtres}",
        )
        if ville_filtre != "Toutes les villes":
            cles = [ville_filtre]

    recentes, anciennes, ecartees = c.offres_de_la_ville(offres_sel, cles, recommandees)

    st.markdown(
        f'<h2 style="margin:8px 0 0">Offres récentes</h2><p class="dn-muted">Publiées il y a moins de '
        f'{c.JOURS_RECENTS} jours. D\'abord celles accessibles avec ton CV actuel, puis celles qui '
        "demandent une des compétences recommandées.</p>",
        unsafe_allow_html=True,
    )
    if recentes.empty:
        st.markdown('<div class="dn-carte">Aucune offre récente ici. Regarde les offres plus anciennes ci-dessous.</div>', unsafe_allow_html=True)
    else:
        groupes(recentes)

    if not anciennes.empty:
        dures = int(anciennes["persistante"].sum())
        st.toggle(
            f"Voir les {mot(len(anciennes), 'offre plus ancienne encore ouverte', 'offres plus anciennes encore ouvertes')}",
            key="anciennes",
        )
        st.caption(
            f"{mot(dures, 'offre en ligne', 'offres en ligne')} depuis plus de 30 jours : l'employeur peine "
            "à recruter, ta candidature a des chances d'être lue."
        )
        if E.anciennes:
            groupes(anciennes)

    if ecartees:
        st.caption(
            f"{mot(ecartees, 'offre demande', 'offres demandent')} beaucoup plus d'expérience que la tienne : "
            "non affichée(s), non comptée(s) dans le score."
        )


# ================================================================= page

st.markdown(s.bandeau(E.etape), unsafe_allow_html=True)
with st.popover("Comment le score est calculé"):
    st.markdown(
        f"""
**Score d'opportunité (sur 100) = 45 % pénurie + 35 % adéquation au CV + 20 % volume d'offres.**

Le score classe les territoires selon des signaux de tension et l'adéquation au profil ;
ce n'est pas une probabilité d'embauche.

- **Pénurie** : deux signaux, les offres encore en ligne après {c.SEUIL_JOURS} jours et celles que
  France Travail signale comme manquant de candidats. Chacun est lissé vers la moyenne nationale
  ({pct(REFS['persistance'])} et {pct(REFS['manque'])} aujourd'hui), pour qu'une ville avec 3 offres
  ne passe pas devant Paris par hasard. Un territoire dans la moyenne nationale a une pénurie de 50 %.
- **Adéquation** : pour chaque offre, compétences demandées présentes dans ton CV ÷ compétences demandées.
- **Volume** : nombre d'offres compatibles, sur une échelle logarithmique.
- Seules comptent les offres qui partagent au moins {c.MIN_COMMUNES} compétences avec ton CV et qui
  ne demandent pas plus de {c.ECART_NIVEAU} ans d'expérience au-delà de la tienne.
- Toutes les offres comptent dans le calcul, même anciennes. L'écran des offres n'affiche par défaut
  que celles de moins de {c.JOURS_RECENTS} jours.
"""
    )

{1: etape_cv, 2: etape_territoires, 3: etape_offres}[E.etape]()