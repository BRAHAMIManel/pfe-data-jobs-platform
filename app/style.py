"""
Charte graphique de l'application : couleurs, polices et petits blocs HTML.

Palette bordeaux, claire. Les couleurs principales sont aussi declarees
dans .streamlit/config.toml pour les composants natifs de Streamlit.
"""

from html import escape

BORDEAUX = "#7A1F3D"
BORDEAUX_FONCE = "#6A1834"
ROSE = "#F2C4CE"
ROSE_PALE = "#F6E4EA"
FOND = "#FBF7F6"
ENCRE = "#2A1418"
GRIS = "#6E5A5E"
BRIQUE = "#D2603A"
BRIQUE_PALE = "#FBE4DA"
VERT = "#1F7A52"
VERT_BARRE = "#2E9B6A"
VERT_PALE = "#DDF2E7"

CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Sora:wght@600;700;800&family=Manrope:wght@400;500;600;700&display=swap');

html, body, [class*="st-"], .stMarkdown, button, input, textarea {{
  font-family: 'Manrope', 'Segoe UI', system-ui, sans-serif;
}}
h1, h2, h3, .dn-titre {{
  font-family: 'Sora', 'Segoe UI', system-ui, sans-serif !important;
  color: {ENCRE};
  letter-spacing: -0.01em;
}}
.block-container {{ padding-top: 1.2rem; max-width: 1200px; }}
header[data-testid="stHeader"] {{ background: transparent; }}

/* Bandeau */
.dn-bandeau {{
  background: {BORDEAUX}; color: #fff; border-radius: 18px;
  padding: 14px 20px; display: flex; align-items: center; gap: 14px;
  flex-wrap: wrap; margin-bottom: 6px;
}}
.dn-marque {{ display: flex; align-items: center; gap: 10px;
  font: 800 20px 'Sora', system-ui, sans-serif; }}
.dn-etapes {{ display: flex; gap: 6px; margin-left: auto; flex-wrap: wrap; }}
.dn-etape {{ display: flex; align-items: center; gap: 8px; padding: 6px 12px;
  border-radius: 999px; font-weight: 600; font-size: 14px; color: rgba(255,255,255,.8); }}
.dn-etape b {{ display: grid; place-items: center; width: 22px; height: 22px;
  border-radius: 50%; background: rgba(255,255,255,.2); font-size: 12px; }}
.dn-etape.on {{ background: #fff; color: {BORDEAUX_FONCE}; }}
.dn-etape.on b {{ background: {ROSE}; color: {BORDEAUX_FONCE}; }}

/* Cartes */
.dn-carte {{ background: #fff; border-radius: 16px; padding: 18px 20px;
  box-shadow: 0 2px 12px rgba(122,31,61,.08); margin-bottom: 12px; }}
.dn-eyebrow {{ font: 700 11px/1 'Manrope', sans-serif; letter-spacing: .08em;
  text-transform: uppercase; color: {GRIS}; }}
.dn-muted {{ color: {GRIS}; font-size: 14px; }}
div[data-testid="stMetric"] {{ background: #fff; border-radius: 16px;
  padding: 14px 16px; box-shadow: 0 2px 12px rgba(122,31,61,.08); }}
div[data-testid="stMetricValue"] {{ font-family: 'Sora', sans-serif; color: {BORDEAUX_FONCE}; }}

/* Puces */
.dn-puces {{ display: flex; flex-wrap: wrap; gap: 6px; }}
.dn-puce {{ padding: 4px 10px; border-radius: 999px; font-size: 12.5px; font-weight: 600;
  background: {VERT_PALE}; color: {VERT}; }}
.dn-puce.apprendre {{ background: transparent; border: 1.5px dashed {VERT_BARRE}; color: {VERT}; }}
.dn-puce.manque {{ background: #F4E9EB; color: {GRIS}; }}
.dn-badge {{ display: inline-block; font: 700 10.5px/1 'Manrope', sans-serif; letter-spacing: .04em;
  text-transform: uppercase; padding: 4px 8px; border-radius: 999px; margin-left: 6px; vertical-align: 3px; }}
.dn-badge.Fiable {{ background: {VERT_PALE}; color: {VERT}; }}
.dn-badge.Indicatif {{ background: {BRIQUE_PALE}; color: #9C4422; }}
.dn-badge.Fragile {{ background: #F4E9EB; color: {GRIS}; }}
.dn-pill {{ display: inline-block; margin-left: 8px; padding: 3px 9px; border-radius: 999px;
  font-size: 11.5px; font-weight: 700; vertical-align: 2px; }}
.dn-pill.neuve {{ background: {ROSE_PALE}; color: {BORDEAUX_FONCE}; }}
.dn-pill.dure {{ background: {BRIQUE_PALE}; color: #9C4422; }}

/* Offres */
.dn-offre {{ display: grid; grid-template-columns: minmax(0,1fr) auto; gap: 14px; }}
.dn-offre h4 {{ margin: 0; font: 700 16px 'Manrope', sans-serif; color: {ENCRE}; }}
.dn-meta {{ color: {GRIS}; font-size: 13.5px; margin: 3px 0 10px; }}
.dn-cote {{ text-align: right; display: flex; flex-direction: column; justify-content: space-between; gap: 10px; }}
.dn-match {{ font: 800 24px 'Sora', sans-serif; color: {BORDEAUX_FONCE}; }}
.dn-match small {{ display: block; font: 600 11.5px 'Manrope', sans-serif; color: {GRIS}; }}
.dn-boutons {{ display: flex; gap: 6px; justify-content: flex-end; flex-wrap: wrap; }}
.dn-bouton {{ padding: 7px 12px; border-radius: 10px; font-weight: 700; font-size: 13px;
  text-decoration: none !important; border: 2px solid {BORDEAUX}; }}
.dn-bouton.plein {{ background: {BORDEAUX}; color: #fff !important; }}
.dn-bouton.vide {{ background: #fff; color: {BORDEAUX} !important; }}
@media (max-width: 640px) {{
  .dn-offre {{ grid-template-columns: minmax(0,1fr); }}
  .dn-cote {{ text-align: left; }}
  .dn-boutons {{ justify-content: flex-start; }}
}}

/* Barres */
.dn-barre {{ display: grid; grid-template-columns: 120px minmax(0,1fr) 150px; gap: 10px;
  align-items: center; font-size: 13.5px; font-weight: 600; margin: 9px 0; }}
.dn-piste {{ height: 10px; border-radius: 999px; background: #F4E9EB; overflow: hidden; }}
.dn-piste span {{ display: block; height: 100%; border-radius: 999px; }}
.dn-barre .n {{ text-align: right; white-space: nowrap; color: {GRIS}; font-variant-numeric: tabular-nums; }}

/* Mini-carte */
.dn-carte-fr {{ display: grid; grid-template-columns: repeat(5, minmax(0,1fr)); gap: 6px;
  max-width: 420px; margin: 8px auto 0; }}
.dn-tuile {{ aspect-ratio: 1; border-radius: 10px; padding: 7px; display: flex;
  flex-direction: column; justify-content: space-between; font-weight: 700; font-size: 12px; }}
.dn-tuile .s {{ font: 800 14px 'Sora', sans-serif; }}
.dn-tuile.hors {{ opacity: .3; }}
.dn-legende {{ display: flex; gap: 8px; align-items: center; justify-content: center;
  font-size: 12px; color: {GRIS}; margin-top: 12px; }}
.dn-legende i {{ width: 120px; height: 8px; border-radius: 4px;
  background: linear-gradient(90deg, {ROSE_PALE}, {BORDEAUX}); }}

.dn-encart {{ background: {BRIQUE_PALE}; border-radius: 14px; padding: 12px 16px; font-size: 14px; }}
.dn-groupe {{ display: flex; justify-content: space-between; align-items: baseline; flex-wrap: wrap;
  gap: 10px; margin: 18px 0 8px; }}
.dn-groupe h3 {{ font-size: 17px !important; margin: 0; }}

.stButton > button[kind="primary"] {{ border-radius: 10px; font-weight: 700; }}
.stButton > button {{ border-radius: 10px; }}
</style>
"""


def bandeau(etape):
    noms = ["Mon CV", "Territoires", "Offres"]
    etapes = "".join(
        f'<span class="dn-etape{" on" if i + 1 == etape else ""}"><b>{i + 1}</b>{n}</span>'
        for i, n in enumerate(noms)
    )
    logo = (
        '<svg width="26" height="26" viewBox="0 0 26 26" aria-hidden="true">'
        '<circle cx="13" cy="13" r="11" fill="none" stroke="#fff" stroke-width="2"/>'
        f'<circle cx="13" cy="13" r="5.5" fill="none" stroke="{ROSE}" stroke-width="2.4"/>'
        '<circle cx="13" cy="13" r="1.8" fill="#fff"/></svg>'
    )
    return (
        f'<div class="dn-bandeau"><div class="dn-marque">{logo}Détecteur de niches IT</div>'
        f'<div class="dn-etapes">{etapes}</div></div>'
    )


def couleur_chaleur(score):
    """Du rose pale (25 %) au bordeaux (75 %)."""
    t = min(max((score - 25) / 50, 0), 1)
    a, b = (0xF6, 0xE4, 0xEA), (0x7A, 0x1F, 0x3D)
    r, g, bl = (round(a[i] + (b[i] - a[i]) * t) for i in range(3))
    return f"rgb({r},{g},{bl})", t > 0.5


def mini_carte(regions, dans_zone):
    """regions : lignes avec abrev, nom, grille_ligne, grille_col, score."""
    cases = {}
    for r in regions:
        if r["grille_ligne"] is None or r["grille_ligne"] != r["grille_ligne"]:
            continue  # outre-mer : pas de case sur la mini-carte
        a_score = r["score"] is not None and r["score"] == r["score"]
        fond, sombre = couleur_chaleur(r["score"]) if a_score else ("#F4E9EB", False)
        texte = "#fff" if sombre else ENCRE
        score = f'{int(r["score"])} %' if a_score else "–"
        hors = "" if r["code"] in dans_zone else " hors"
        cases[(int(r["grille_ligne"]), int(r["grille_col"]))] = (
            f'<div class="dn-tuile{hors}" style="background:{fond};color:{texte}" '
            f'title="{escape(r["nom"])} : {score}"><span>{r["abrev"]}</span>'
            f'<span class="s">{score}</span></div>'
        )
    grille = "".join(cases.get((i // 5, i % 5), "<div></div>") for i in range(25))
    return (
        f'<div class="dn-carte-fr">{grille}</div>'
        '<div class="dn-legende">25 %<i></i>75 % · opportunité</div>'
    )


def jauge(score):
    c = 326.7
    return (
        '<svg viewBox="0 0 120 120" width="132" height="132" role="img" '
        f'aria-label="Opportunité {score} sur 100" style="flex:none">'
        '<circle cx="60" cy="60" r="52" fill="none" stroke="#F4E9EB" stroke-width="12"/>'
        f'<circle cx="60" cy="60" r="52" fill="none" stroke="{BORDEAUX}" stroke-width="12" '
        f'stroke-linecap="round" stroke-dasharray="{c}" stroke-dashoffset="{c * (1 - score / 100):.1f}" '
        'transform="rotate(-90 60 60)"/>'
        f'<text x="60" y="62" text-anchor="middle" font-family="Sora, sans-serif" font-weight="800" '
        f'font-size="26" fill="{ENCRE}">{score}</text>'
        f'<text x="60" y="80" text-anchor="middle" font-size="10" fill="{GRIS}">sur 100</text>'
        f'</svg>'
    )


def barre(libelle, valeur, couleur, texte):
    return (
        f'<div class="dn-barre"><span>{escape(libelle)}</span>'
        f'<div class="dn-piste"><span style="width:{max(0, min(valeur, 1)) * 100:.0f}%;background:{couleur}"></span></div>'
        f'<span class="n">{escape(texte)}</span></div>'
    )


def badge(fiabilite):
    return f'<span class="dn-badge {fiabilite}">{fiabilite}</span>'