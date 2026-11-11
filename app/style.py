"""
Charte graphique de l'application : couleurs, polices et petits blocs HTML.

Palette « data / detection » : graphite pour la structure, rouge signal
pour ce qui doit ressortir, fond gris tres clair pour la lecture. Le rouge
est un signal, pas une decoration : il marque l'element qui compte
(etape en cours, valeur la plus haute d'un graphique, bouton principal).
Les couleurs principales sont aussi declarees dans .streamlit/config.toml
pour les composants natifs de Streamlit.
"""

from html import escape

# Structure (theme sombre, esprit « data / detection »)
FOND = "#0E1014"          # fond de page
GRAPHITE = "#16181D"      # bandeau, blocs d'ouverture
CARTE = "#1A1D24"         # cartes et panneaux
BORD = "#2A2F38"          # bordures, pistes des barres, grille
TRAME = "#4B5262"         # barres « ordinaires » des graphiques
ARDOISE = "#5B6272"
GRIS = "#9AA1AD"          # texte secondaire
GRIS_CLAIR = BORD
ENCRE = "#EEF0F3"         # texte principal
# Signal
ROUGE = "#E0182D"
ROUGE_FONCE = "#FF7A85"   # texte rouge lisible sur fond sombre
ROUGE_CLAIR = "#FF5A68"
ROSE = "#FFD2D7"
ROSE_PALE = "#3A161C"     # fond rouge discret
# Etats
VERT = "#5BD49A"
VERT_BARRE = "#2E9B6A"
VERT_PALE = "#12352A"

# Anciens noms gardes pour le reste du code
BORDEAUX = ROUGE
BORDEAUX_FONCE = ENCRE    # chiffres mis en avant : clairs sur fond sombre
BRIQUE = ROUGE_CLAIR
BRIQUE_PALE = ROSE_PALE

CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Sora:wght@600;700;800&family=Manrope:wght@400;500;600;700&family=JetBrains+Mono:wght@500;700&display=swap');

html, body, [class*="st-"], .stMarkdown, button, input, textarea {{
  font-family: 'Manrope', 'Segoe UI', system-ui, sans-serif;
}}
h1, h2, h3, .dn-titre {{
  font-family: 'Sora', 'Segoe UI', system-ui, sans-serif !important;
  color: {ENCRE};
  letter-spacing: -0.01em;
}}
.block-container {{ padding-top: 1.2rem; padding-left: 2.5rem; padding-right: 2.5rem; max-width: 100%; }}
header[data-testid="stHeader"] {{ background: transparent; }}

/* Bandeau */
.dn-bandeau {{
  background: {GRAPHITE}; color: #fff; border-radius: 18px; border: 1px solid {BORD}; border-bottom: 3px solid {ROUGE};
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
.dn-etape.on {{ background: #fff; color: {GRAPHITE}; }}
.dn-etape.on b {{ background: {ROUGE}; color: #fff; }}

/* Cartes */
.dn-carte {{ background: {CARTE}; border: 1px solid {BORD}; border-radius: 16px; padding: 18px 20px;
  margin-bottom: 12px; color: {ENCRE}; }}
.dn-eyebrow {{ font: 700 11px/1 'JetBrains Mono', monospace; letter-spacing: .1em;
  text-transform: uppercase; color: {GRIS}; }}
.dn-mono {{ font-family: 'JetBrains Mono', monospace; letter-spacing: .06em; }}

/* Accueil « Le marche » : bandeau graphite, trame de grille, coins de detection */
.dn-hero {{ position: relative; background: {GRAPHITE}; color: #fff; border-radius: 18px; border: 1px solid {BORD};
  padding: 34px 36px 30px; margin: 4px 0 18px; overflow: hidden;
  background-image: linear-gradient(rgba(255,255,255,.05) 1px, transparent 1px),
                    linear-gradient(90deg, rgba(255,255,255,.05) 1px, transparent 1px);
  background-size: 32px 32px; }}
.dn-hero h1 {{ color: #fff !important; font-size: 40px; margin: 10px 0 8px; line-height: 1.1; }}
.dn-hero h1 em {{ font-style: normal; color: {ROUGE_CLAIR}; }}
.dn-hero p {{ color: rgba(255,255,255,.75); max-width: 760px; margin: 0; font-size: 15px; }}
.dn-hero .dn-eyebrow {{ color: {ROUGE_CLAIR}; }}
.dn-cible {{ position: relative; background: {CARTE}; border: 1px solid {BORD}; border-radius: 14px; padding: 18px 20px; color: {ENCRE}; }}
.dn-cible::before, .dn-cible::after {{ content: ""; position: absolute; width: 14px; height: 14px;
  border: 2px solid {ROUGE}; }}
.dn-cible::before {{ top: 8px; left: 8px; border-right: 0; border-bottom: 0; }}
.dn-cible::after {{ bottom: 8px; right: 8px; border-left: 0; border-top: 0; }}
.dn-chiffre {{ font: 700 30px 'JetBrains Mono', monospace; color: {ENCRE}; letter-spacing: -.02em; }}
.dn-section {{ font: 700 12px/1 'JetBrains Mono', monospace; letter-spacing: .12em;
  text-transform: uppercase; color: {ENCRE}; margin: 22px 0 10px;
  padding-left: 10px; border-left: 3px solid {ROUGE}; }}
.dn-muted {{ color: {GRIS}; font-size: 14px; }}
.dn-cta {{ display: inline-flex; align-items: center; gap: 8px; padding: 9px 18px; border-radius: 999px;
  background: {ROUGE}; color: #fff !important; font-weight: 800; text-decoration: none !important;
  white-space: nowrap; transition: background .15s ease; }}
.dn-cta:hover {{ background: #F23347; }}
.dn-cta.discret {{ background: transparent; border: 1.5px solid {ROUGE}; color: {ROUGE_CLAIR} !important; }}
.dn-cta.discret:hover {{ background: {ROSE_PALE}; }}
.dn-cta.grand {{ padding: 13px 26px; font-size: 16px; }}
/* Page « Le marche » : blocs editoriaux */
.dn-hero-grille {{ display: grid; grid-template-columns: minmax(0,1.25fr) minmax(0,1fr); gap: 28px; align-items: end; }}
.dn-hero-stats {{ display: flex; gap: 30px; flex-wrap: wrap; margin-top: 22px; }}
.dn-hero-stats div {{ display: flex; flex-direction: column; gap: 4px; }}
.dn-hero-stats b {{ font: 700 30px 'JetBrains Mono', monospace; color: #fff; }}
.dn-hero-stats span {{ font: 600 11px/1.2 'JetBrains Mono', monospace; letter-spacing: .1em;
  text-transform: uppercase; color: rgba(255,255,255,.6); }}
.dn-hero svg {{ width: 100%; height: auto; display: block; }}
.dn-retenir {{ display: grid; grid-template-columns: repeat(3, minmax(0,1fr)); gap: 16px; }}
.dn-fait {{ background: {CARTE}; border: 1px solid {BORD}; border-radius: 16px; padding: 22px 22px 20px; border-top: 3px solid {ARDOISE}; }}
.dn-fait.signal {{ border-top-color: {ROUGE}; }}
.dn-fait .chiffre {{ display: block; font: 700 38px/1 'JetBrains Mono', monospace; color: {ENCRE}; margin: 10px 0 10px; }}
.dn-fait.signal .chiffre {{ color: {ROUGE}; }}
.dn-fait p {{ margin: 0; color: {ENCRE}; font-size: 15px; line-height: 1.45; }}
.dn-tags {{ display: flex; flex-wrap: wrap; gap: 8px; }}
.dn-tag {{ display: inline-flex; align-items: baseline; gap: 8px; padding: 8px 14px; border-radius: 10px;
  background: {CARTE}; border: 1px solid {BORD}; color: {ENCRE}; font-weight: 700; }}
.dn-tag small {{ font: 600 12px 'JetBrains Mono', monospace; color: {GRIS}; }}
.dn-tag.top {{ background: {ENCRE}; border-color: {ENCRE}; color: {GRAPHITE}; }}
.dn-tag.top small {{ color: {ROUGE}; }}
.dn-tag.top small {{ color: {ROUGE_CLAIR}; }}
.dn-familles {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(230px, 1fr)); gap: 14px; }}
.dn-famille {{ background: {CARTE}; border: 1px solid {BORD}; border-radius: 14px; padding: 16px 18px; }}
.dn-famille h4 {{ margin: 6px 0 2px; font-size: 17px; }}
.dn-famille .n {{ font: 700 22px 'JetBrains Mono', monospace; color: {ENCRE}; }}
.dn-famille ul {{ margin: 8px 0 0; padding-left: 18px; color: {GRIS}; font-size: 13.5px; }}
.dn-podium {{ display: flex; flex-direction: column; gap: 10px; }}
.dn-region {{ display: grid; grid-template-columns: 34px minmax(0,1fr) auto; gap: 12px; align-items: center;
  background: {CARTE}; border: 1px solid {BORD}; border-radius: 12px; padding: 12px 16px; }}
.dn-region .rang {{ font: 700 18px 'JetBrains Mono', monospace; color: {ROUGE}; }}
.dn-region .t {{ font: 700 20px 'JetBrains Mono', monospace; color: {ENCRE}; text-align: right; }}
.dn-contrats {{ display: flex; height: 44px; border-radius: 10px; overflow: hidden; gap: 2px; margin: 8px 0 12px; }}
.dn-contrats div {{ display: flex; align-items: center; justify-content: center; color: #fff;
  font: 700 12.5px 'JetBrains Mono', monospace; white-space: nowrap; overflow: hidden; }}
.dn-appel {{ background: {GRAPHITE}; color: #fff; border: 1px solid {BORD}; border-radius: 18px; padding: 30px 34px; margin-top: 40px;
  background-image: linear-gradient(rgba(255,255,255,.05) 1px, transparent 1px),
                    linear-gradient(90deg, rgba(255,255,255,.05) 1px, transparent 1px);
  background-size: 32px 32px; }}
.dn-appel h2 {{ color: #fff !important; margin: 6px 0 8px; font-size: 28px; }}
.dn-appel p {{ color: rgba(255,255,255,.75); margin: 0; max-width: 760px; }}
@media (max-width: 900px) {{ .dn-hero-grille, .dn-retenir {{ grid-template-columns: 1fr; }} }}
div[data-testid="stMetric"] {{ background: {CARTE}; border: 1px solid {BORD}; border-radius: 16px;
  padding: 14px 16px; }}
div[data-testid="stMetricValue"] {{ font-family: 'JetBrains Mono', monospace; color: {ENCRE}; }}

/* Puces */
.dn-puces {{ display: flex; flex-wrap: wrap; gap: 6px; }}
.dn-puce {{ padding: 4px 10px; border-radius: 999px; font-size: 12.5px; font-weight: 600;
  background: {VERT_PALE}; color: {VERT}; }}
.dn-puce.apprendre {{ background: transparent; border: 1.5px dashed {VERT_BARRE}; color: {VERT}; }}
.dn-puce.manque {{ background: {GRIS_CLAIR}; color: {GRIS}; }}
.dn-badge {{ display: inline-block; font: 700 10.5px/1 'Manrope', sans-serif; letter-spacing: .04em;
  text-transform: uppercase; padding: 4px 8px; border-radius: 999px; margin-left: 6px; vertical-align: 3px; }}
.dn-badge.Fiable {{ background: {VERT_PALE}; color: {VERT}; }}
.dn-badge.Indicatif {{ background: {BRIQUE_PALE}; color: {ROUGE_FONCE}; }}
.dn-badge.Fragile {{ background: {GRIS_CLAIR}; color: {GRIS}; }}
.dn-pill {{ display: inline-block; margin-left: 8px; padding: 3px 9px; border-radius: 999px;
  font-size: 11.5px; font-weight: 700; vertical-align: 2px; }}
.dn-pill.neuve {{ background: {ROSE_PALE}; color: {BORDEAUX_FONCE}; }}
.dn-pill.dure {{ background: {BRIQUE_PALE}; color: {ROUGE_FONCE}; }}

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
.dn-bouton.vide {{ background: {CARTE}; color: {ROUGE_CLAIR} !important; }}
@media (max-width: 640px) {{
  .dn-offre {{ grid-template-columns: minmax(0,1fr); }}
  .dn-cote {{ text-align: left; }}
  .dn-boutons {{ justify-content: flex-start; }}
}}

/* Barres */
.dn-barre {{ display: grid; grid-template-columns: 120px minmax(0,1fr) 150px; gap: 10px;
  align-items: center; font-size: 13.5px; font-weight: 600; margin: 9px 0; }}
.dn-piste {{ height: 10px; border-radius: 999px; background: {GRIS_CLAIR}; overflow: hidden; }}
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
  background: linear-gradient(90deg, {BORD}, {ROUGE}); }}

.dn-encart {{ background: {BRIQUE_PALE}; border-radius: 14px; padding: 12px 16px; font-size: 14px; }}
.dn-groupe {{ display: flex; justify-content: space-between; align-items: baseline; flex-wrap: wrap;
  gap: 10px; margin: 18px 0 8px; }}
.dn-groupe h3 {{ font-size: 17px !important; margin: 0; }}

.stButton > button[kind="primary"] {{ border-radius: 10px; font-weight: 700; }}
.stButton > button {{ border-radius: 10px; }}
</style>
"""


# Lien vers l'etape « Mon CV » depuis l'accueil. Un vrai lien (et non un
# bouton Streamlit) pour pouvoir le placer dans le bandeau et dans les blocs
# HTML ; app.py lit ?etape=1 au chargement. Sur l'accueil, aucune saisie
# n'est encore faite : recharger la page ne fait rien perdre.
LIEN_CV = "?etape=1"


def bouton_cv(texte="Déposer mon CV", discret=False):
    return (f'<a class="dn-cta{" discret" if discret else ""}" href="{LIEN_CV}" target="_self">'
            f"{texte} <span aria-hidden=\"true\">→</span></a>")


def bandeau(etape):
    """Accueil : « Le marché » + bouton « Déposer mon CV ». Ensuite : les 3 étapes."""
    if etape == 0:
        etapes = '<span class="dn-etape on"><b>◎</b>Le marché</span>' + bouton_cv()
    else:
        noms = ["Mon CV", "Territoires", "Offres"]
        etapes = '<span class="dn-etape"><b>◎</b>Le marché</span>' + "".join(
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
    """Du gris ardoise (25 %) au rouge signal (75 %), sur fond sombre."""
    t = min(max((score - 25) / 50, 0), 1)
    a, b = (0x2A, 0x2F, 0x38), (0xE0, 0x18, 0x2D)
    r, g, bl = (round(a[i] + (b[i] - a[i]) * t) for i in range(3))
    return f"rgb({r},{g},{bl})", t > 0.5


def mini_carte(regions, dans_zone, legende="opportunité"):
    """regions : lignes avec abrev, nom, grille_ligne, grille_col, score."""
    cases = {}
    for r in regions:
        if r["grille_ligne"] is None or r["grille_ligne"] != r["grille_ligne"]:
            continue  # outre-mer : pas de case sur la mini-carte
        a_score = r["score"] is not None and r["score"] == r["score"]
        fond, sombre = couleur_chaleur(r["score"]) if a_score else (GRIS_CLAIR, False)
        texte = "#fff"
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
        f'<div class="dn-legende">25 %<i></i>75 % · {legende}</div>'
    )


def jauge(score):
    c = 326.7
    return (
        '<svg viewBox="0 0 120 120" width="132" height="132" role="img" '
        f'aria-label="Opportunité {score} sur 100" style="flex:none">'
        f'<circle cx="60" cy="60" r="52" fill="none" stroke="{GRIS_CLAIR}" stroke-width="12"/>'
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