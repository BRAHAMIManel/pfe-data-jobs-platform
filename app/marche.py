"""
Page d'accueil « Le marché » : ce que l'entrepot dit du marche informatique.

Tout vient des offres collectees (table dbt mart_offres_candidat) et du
repere officiel BMO 2026. Aucune donnee du candidat ici : c'est la vue
d'ensemble, avant le depot du CV.

Charte « data / detection » (style.py) : bandeau graphite a trame de
grille, chiffres cles dans des cadres de detection, police monospace pour
les donnees. Graphiques Altair : barres graphite, et une seule barre en
rouge signal, la valeur la plus haute. Le rouge marque ce qui compte,
jamais une decoration ; l'identite des barres est donnee par l'axe.
"""

import altair as alt
import pandas as pd
import streamlit as st

import calculs as c
import style as s

SEMAINES_AFFICHEES = 16
TOP_COMPETENCES = 15
CONTRATS = {"CDI": "CDI", "LIB": "Freelance", "MIS": "Intérim", "CDD": "CDD"}
TRANCHES_EXPERIENCE = [
    (-0.1, 0.0, "Débutant accepté"),
    (0.0, 2.0, "Moins de 2 ans"),
    (2.0, 4.99, "2 à 4 ans"),
    (4.99, 9.99, "5 à 9 ans"),
    (9.99, 99.0, "10 ans et plus"),
]


# ------------------------------------------------------------ mise en forme

def _style(graphique, hauteur):
    """Charte commune : fond transparent, axes et grille discrets."""
    return (
        graphique.properties(height=hauteur)
        .configure(background="transparent", font="Manrope, sans-serif")
        .configure_view(stroke=None)
        .configure_axis(
            labelColor=s.GRIS, titleColor=s.GRIS, labelFontSize=12, titleFontSize=12,
            gridColor=s.BORD, domainColor=s.BORD, tickColor=s.BORD,
        )
    )


def barres(df, categorie, valeur, format_valeur, infobulle, hauteur=None, tri="-x", repere=None):
    """Barres horizontales triees, graphite ; la plus haute en rouge signal.

    `repere` : valeur de reference tracee en pointille (ex. 0,5 = moyenne).
    """
    hauteur = hauteur or max(160, 28 * len(df))
    df = df.assign(_signal=df[valeur] == df[valeur].max())
    maxi = max(float(df[valeur].max()), repere or 0) * 1.15 or 1
    base = alt.Chart(df).encode(
        y=alt.Y(f"{categorie}:N", sort=tri, title=None,
                axis=alt.Axis(labelLimit=260, labelOverlap=False)),
        x=alt.X(f"{valeur}:Q", title=None, scale=alt.Scale(domain=[0, maxi], nice=False),
                axis=alt.Axis(format=format_valeur, grid=True, tickCount=4)),
        tooltip=infobulle,
    )
    corps = base.mark_bar(cornerRadiusEnd=4, height={"band": 0.7}).encode(
        color=alt.condition("datum._signal", alt.value(s.ROUGE), alt.value(s.TRAME))
    )
    etiquettes = base.mark_text(align="left", dx=4, color=s.ENCRE, fontSize=12,
                                font="JetBrains Mono").encode(
        text=alt.Text(f"{valeur}:Q", format=format_valeur)
    )
    graphique = corps + etiquettes
    if repere is not None:
        regle = alt.Chart(pd.DataFrame({"r": [repere]})).mark_rule(
            color=s.GRIS, strokeDash=[4, 4], strokeWidth=1.5).encode(x="r:Q")
        graphique = graphique + regle
    return _style(graphique, hauteur)


def tuile(colonne, valeur, libelle, detail=""):
    """Chiffre cle dans un cadre de detection (coins rouges)."""
    colonne.markdown(
        f'<div class="dn-cible"><span class="dn-eyebrow">{libelle}</span>'
        f'<div class="dn-chiffre" style="margin:8px 0 4px">{valeur}</div>'
        f'<div class="dn-muted" style="font-size:12.5px">{detail}</div></div>',
        unsafe_allow_html=True,
    )


def section(titre):
    st.markdown(f'<div class="dn-section">{titre}</div>', unsafe_allow_html=True)


def pct(x):
    return f"{x:.0%}".replace("%", " %")


def nombre(n):
    return f"{int(n):,}".replace(",", " ")


# ------------------------------------------------------------- indicateurs

def tension_par_region(offres, refs):
    """Tension relative par region (0,5 = moyenne nationale), sans CV."""
    g = offres.groupby("code_region")
    t = pd.DataFrame({
        "offres": g.size(),
        "persistantes": g["persistante"].sum(),
        "manque": g["manque"].sum(),
        "republications": g["republication"].sum(),
        "region": g["region"].first(),
    })
    t["tension"] = c.penurie_depuis_indice(c.indice_penurie(t, refs))
    return t[t["offres"] >= c.SEUIL_INDICATIF].reset_index()


def bmo_par_region(bmo):
    if bmo.empty:
        return pd.DataFrame(columns=["code_region", "bmo"])
    r = bmo.groupby("code_region")[["projets", "difficiles"]].sum()
    r["bmo"] = r["difficiles"] / r["projets"]
    return r[r["projets"] >= 20][["bmo"]].reset_index()


def tranche_experience(annees):
    if pd.isna(annees):
        return "Non précisé"
    for bas, haut, libelle in TRANCHES_EXPERIENCE:
        if bas < annees <= haut:
            return libelle
    return "Non précisé"


# ------------------------------------------------------------- blocs HTML

def courbe_svg(valeurs, largeur=520, hauteur=150):
    """Petite courbe rouge sur fond sombre, pour le bandeau d'ouverture."""
    if len(valeurs) < 2:
        return ""
    maxi = max(valeurs) or 1
    pas = largeur / (len(valeurs) - 1)
    points = [(i * pas, hauteur - 10 - (v / maxi) * (hauteur - 30)) for i, v in enumerate(valeurs)]
    trace = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
    x_fin, y_fin = points[-1]
    x_max, y_max = max(points, key=lambda p: -p[1])
    return (
        f'<svg viewBox="0 0 {largeur} {hauteur}" role="img" aria-label="Offres publiées par semaine">'
        f'<polygon points="0,{hauteur} {trace} {largeur},{hauteur}" fill="{s.ROUGE}" fill-opacity=".12"/>'
        f'<polyline points="{trace}" fill="none" stroke="{s.ROUGE_CLAIR}" stroke-width="2.5" '
        'stroke-linejoin="round" stroke-linecap="round"/>'
        f'<circle cx="{x_max:.1f}" cy="{y_max:.1f}" r="5" fill="{s.ROUGE}"/>'
        f'<circle cx="{x_max:.1f}" cy="{y_max:.1f}" r="11" fill="none" stroke="{s.ROUGE}" stroke-opacity=".5"/>'
        f'<circle cx="{x_fin:.1f}" cy="{y_fin:.1f}" r="3.5" fill="#fff"/>'
        "</svg>"
        '<div class="dn-eyebrow" style="color:rgba(255,255,255,.55);margin-top:8px">'
        "Offres publiées par semaine · le point rouge marque le pic</div>"
    )


def fait(chiffre, texte, signal=False):
    return (f'<div class="dn-fait{" signal" if signal else ""}">'
            f'<span class="dn-eyebrow">À retenir</span><span class="chiffre">{chiffre}</span><p>{texte}</p></div>')


# ------------------------------------------------------------------ page

def page(offres, bmo, refs, postes, categorie_du_poste, categories, aller, regions=None):
    en_ligne = offres[offres["en_ligne"]]
    jour = pd.to_datetime(offres["jour_collecte"].iloc[0])
    debut = pd.to_datetime(offres["premiere_collecte"]).min()

    dates = pd.to_datetime(offres["date_creation"]).dropna()
    semaines = (dates.dt.to_period("W-SUN").dt.start_time.value_counts().sort_index()
                .rename_axis("semaine").reset_index(name="offres"))
    semaines = semaines[semaines["semaine"] >= semaines["semaine"].max()
                        - pd.Timedelta(weeks=SEMAINES_AFFICHEES - 1)]

    tension = tension_par_region(offres, refs).merge(bmo_par_region(bmo), on="code_region", how="left")
    avec = en_ligne[en_ligne["nb_requises"] > 0]
    competences = (avec["competences"].explode().value_counts()
                   .rename_axis("competence").reset_index(name="offres"))
    competences["part"] = competences["offres"] / max(len(avec), 1)
    contrats = en_ligne["type_contrat"].map(CONTRATS).fillna("Autres")
    debutants = en_ligne["experience_annees"].fillna(-1).eq(0).mean()
    volume = offres.groupby("region").size().sort_values(ascending=False)

    # ---------------------------------------------------- 1. ouverture
    st.markdown(
        '<div class="dn-hero"><div class="dn-hero-grille"><div>'
        f'<span class="dn-eyebrow">Observatoire · collecte du {jour:%d/%m/%Y}</span>'
        "<h1>Le marché de l'emploi <em>informatique</em>, détecté chaque jour.</h1>"
        "<p>Les offres France Travail des 89 métiers du numérique, collectées et analysées "
        "chaque jour : où elles sont, ce qu'elles demandent, et où la concurrence semble "
        "plus faible qu'ailleurs.</p>"
        '<div class="dn-hero-stats">'
        f"<div><b>{nombre(len(en_ligne))}</b><span>offres en ligne</span></div>"
        f"<div><b>{nombre(len(offres))}</b><span>analysées depuis le {debut:%d/%m}</span></div>"
        f"<div><b>{nombre(offres['entreprise'].nunique())}</b><span>employeurs</span></div>"
        f"<div><b>{len(tension)}</b><span>régions couvertes</span></div>"
        f'</div><div style="margin-top:24px">{s.bouton_cv("Déposer mon CV")}</div>'
        f"</div><div>{courbe_svg(semaines['offres'].tolist())}</div></div></div>",
        unsafe_allow_html=True,
    )

    # ---------------------------------------------------- 2. a retenir
    section("Ce qu'il faut retenir")
    faits = []
    if not volume.empty:
        faits.append(fait(pct(volume.iloc[0] / volume.sum()),
                          f"des offres sont en <b>{volume.index[0]}</b>. Le reste du pays se partage "
                          "le marché, souvent avec moins de concurrence."))
    if not competences.empty:
        top = competences.iloc[0]
        faits.append(fait(pct(top["part"]),
                          f"des offres citent <b>{top['competence']}</b>, la compétence la plus "
                          "demandée en ce moment."))
    faits.append(fait(pct(debutants),
                      "seulement des offres acceptent un <b>débutant</b>. Pour un premier poste, "
                      "bien choisir sa ville compte double.", signal=True))
    st.markdown(f'<div class="dn-retenir">{"".join(faits)}</div>', unsafe_allow_html=True)
    st.markdown('<div style="display:flex;justify-content:flex-end;margin-top:12px">'
                + s.bouton_cv("Voir où mon profil a le plus de chances", discret=True) + "</div>",
                unsafe_allow_html=True)

    # ---------------------------------------------------- 3. ou chercher
    section("Où la concurrence est-elle la plus faible ?")
    gauche, droite = st.columns([1, 1.15], gap="large")
    with gauche:
        if regions is not None and not regions.empty:
            carte = regions.merge(tension[["code_region", "tension"]], left_on="code",
                                  right_on="code_region", how="left")
            carte["score"] = carte["tension"] * 100
            st.markdown('<div class="dn-carte">'
                        + s.mini_carte(carte.to_dict("records"), set(carte["code"]), "tension relative")
                        + "</div>", unsafe_allow_html=True)
        st.caption("Tension relative : 50 % = moyenne nationale. Plus la case est foncée, plus "
                   "les offres y restent en ligne, manquent de candidats ou sont republiées.")
    with droite:
        fiables = tension[tension["offres"] >= c.SEUIL_FIABLE].sort_values("tension", ascending=False)
        lignes = []
        for rang, r in enumerate(fiables.head(5).itertuples(), start=1):
            bmo_txt = f" · BMO : {pct(r.bmo)} de recrutements difficiles" if pd.notna(r.bmo) else ""
            lignes.append(
                f'<div class="dn-region"><span class="rang">{rang:02d}</span>'
                f'<div><b>{r.region}</b><div class="dn-muted" style="font-size:13px">'
                f"{nombre(r.offres)} offres{bmo_txt}</div></div>"
                f'<span class="t">{pct(r.tension)}</span></div>'
            )
        st.markdown('<span class="dn-eyebrow">Les 5 régions les moins saturées</span>'
                    f'<div class="dn-podium" style="margin-top:10px">{"".join(lignes)}</div>',
                    unsafe_allow_html=True)

    # ---------------------------------------------------- 4. competences
    section("Ce que le marché demande")
    tags = "".join(
        f'<span class="dn-tag{" top" if i < 3 else ""}">{r.competence}<small>{pct(r.part)}</small></span>'
        for i, r in enumerate(competences.head(24).itertuples())
    )
    st.markdown(f'<div class="dn-tags">{tags}</div>', unsafe_allow_html=True)
    st.caption(f"Part des offres en ligne qui citent chaque compétence ({nombre(len(avec))} offres "
               "avec au moins une compétence reconnue). En clair : le trio de tête.")

    # ---------------------------------------------------- 5. metiers
    section("Les métiers qui recrutent")
    rangees = en_ligne.dropna(subset=["id_poste"])
    blocs = []
    for cat, g in rangees.groupby(rangees["id_poste"].map(categorie_du_poste)):
        repartition = g["id_poste"].value_counts()
        details = "".join(
            f"<li>{postes.get(p, p)} · {pct(n / len(g))}</li>" for p, n in repartition.head(3).items()
        )
        blocs.append((len(g), f'<div class="dn-famille"><span class="dn-eyebrow">{categories.get(cat, cat)}</span>'
                              f'<div class="n">{nombre(len(g))}</div>'
                              f'<div class="dn-muted" style="font-size:12.5px">offres en ligne · '
                              f"{pct(len(g) / max(len(rangees), 1))} du total</div><ul>{details}</ul></div>"))
    st.markdown('<div class="dn-familles">' + "".join(b for _, b in sorted(blocs, reverse=True)) + "</div>",
                unsafe_allow_html=True)

    # ---------------------------------------------------- 6. contrats, rythme, experience
    section("Contrats, rythme et expérience")
    parts = contrats.value_counts(normalize=True)
    teintes = {"CDI": "#5B6272", "CDD": "#474D59", "Intérim": "#383D47", "Freelance": s.ROUGE, "Autres": "#2A2F38"}
    segments = "".join(
        f'<div style="flex:{v:.4f};background:{teintes.get(k, "#2A2F38")}" title="{k} : {pct(v)}">'
        f'{k + " " + pct(v) if v >= 0.06 else ""}</div>'
        for k, v in parts.items()
    )
    st.markdown(f'<span class="dn-eyebrow">Types de contrat des offres en ligne</span>'
                f'<div class="dn-contrats">{segments}</div>', unsafe_allow_html=True)
    st.caption("Freelance = « profession libérale » chez France Travail.")

    gauche, droite = st.columns(2, gap="large")
    with gauche:
        st.markdown('<span class="dn-eyebrow">Offres publiées par semaine</span>', unsafe_allow_html=True)
        ligne = alt.Chart(semaines).encode(
            x=alt.X("semaine:T", title=None, axis=alt.Axis(format="%d/%m", labelAngle=0, tickCount=8)),
            y=alt.Y("offres:Q", title=None, axis=alt.Axis(tickCount=4)),
            tooltip=[alt.Tooltip("semaine:T", title="Semaine du", format="%d/%m/%Y"),
                     alt.Tooltip("offres:Q", title="Offres publiées", format=",")],
        )
        courbe = (ligne.mark_area(color=s.ROUGE, opacity=0.08)
                  + ligne.mark_line(color=s.ROUGE, strokeWidth=2)
                  + ligne.mark_point(color=s.ROUGE, filled=True, size=40))
        st.altair_chart(_style(courbe, 230), use_container_width=True)
        st.caption("Par date de publication. Les semaines anciennes sont sous-estimées tant que la "
                   "collecte n'est pas quotidienne.")
    with droite:
        st.markdown('<span class="dn-eyebrow">Expérience demandée</span>', unsafe_allow_html=True)
        ordre = [t[2] for t in TRANCHES_EXPERIENCE] + ["Non précisé"]
        exp = (en_ligne["experience_annees"].map(tranche_experience)
               .value_counts(normalize=True).reindex(ordre).fillna(0)
               .rename_axis("experience").reset_index(name="part"))
        st.altair_chart(barres(exp, "experience", "part", ".0%",
                               [alt.Tooltip("experience:N", title="Expérience"),
                                alt.Tooltip("part:Q", title="Part des offres en ligne", format=".1%")],
                               hauteur=230, tri=ordre), use_container_width=True)
        st.caption("Le marché est saturé surtout pour les débutants : c'est là que repérer les "
                   "territoires moins concurrencés aide le plus.")

    # ---------------------------------------------------- 7. appel a l'action
    st.markdown(
        '<div class="dn-appel"><span class="dn-eyebrow" style="color:#FF5A68">Et pour toi ?</span>'
        "<h2>Où ton profil a-t-il le plus de chances ?</h2>"
        "<p>Dépose ton CV : l'application croise tes compétences et ton expérience avec ces offres, "
        "classe les régions et les villes, et te montre les offres à viser et les compétences à "
        "apprendre. Le CV est lu sur place, jamais enregistré ni envoyé à un service extérieur.</p>"
        f'<div style="margin-top:22px">{s.bouton_cv("Déposer mon CV").replace("dn-cta", "dn-cta grand", 1)}</div>'
        "</div>",
        unsafe_allow_html=True,
    )
    st.markdown("<div style='height:18px'></div>", unsafe_allow_html=True)

    st.caption(
        "Sources : offres de l'API France Travail collectées par le pipeline (domaine ROME M18) ; "
        "enquête Besoins en Main-d'Œuvre 2026 de France Travail pour le repère BMO."
    )