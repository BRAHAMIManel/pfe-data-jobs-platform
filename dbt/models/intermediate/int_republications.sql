-- Signal de penurie n°3 : le poste est REPUBLIE.
--
-- Une offre B republie une offre A quand elles ont la meme entreprise, le
-- meme intitule (minuscules, sans accents ni "H/F") et la meme commune, que
-- A avait DISPARU des collectes quand B est apparue, et que B a ete publiee
-- au moins 14 jours apres A. Un employeur qui retire son annonce puis la
-- remet n'a pas trouve : c'est un signal plus solide qu'une offre restee
-- longtemps en ligne, qui peut simplement avoir ete oubliee.
--
-- Deux garde-fous :
--   1. les intermediaires (seed intermediaires.csv) ne comptent pas ;
--   2. un meme employeur compte au plus 3 republications par commune,
--      pour qu'une seule entreprise ne fasse pas la penurie d'une ville.

{% set ecart_minimum = 14 %}
{% set plafond_par_employeur = 3 %}

with offres as (
    select
        f.id_offre,
        f.id_entreprise,
        f.code_insee,
        f.date_creation,
        f.premiere_collecte,
        f.derniere_collecte,
        lower(translate(e.nom, 'ÀÂÄÉÈÊËÎÏÔÖÙÛÜÇàâäéèêëîïôöùûüç',
                               'aaaeeeeiioouuucaaaeeeeiioouuuc'))           as entreprise,
        trim(regexp_replace(regexp_replace(
            translate(lower(f.intitule), 'àâäéèêëîïôöùûüç', 'aaaeeeeiioouuuc'),
            '\(?\s*(h\s*/\s*f|f\s*/\s*h)\s*\)?', '', 'g'), '\s+', ' ', 'g'))  as intitule
    from {{ source('entrepot', 'fait_offre') }} f
    join {{ source('entrepot', 'dim_entreprise') }} e on e.id_entreprise = f.id_entreprise
    where not f.hors_perimetre
      and f.intitule is not null
      and f.date_creation is not null
),

intermediaires as (
    select distinct o.id_entreprise, i.type
    from offres o
    join {{ ref('intermediaires') }} i
      on (i.mode = 'exact'    and o.entreprise = i.motif)
      or (i.mode = 'contient' and o.entreprise like '%' || i.motif || '%')
),

republiees as (
    select b.id_offre, min(b.date_creation - a.date_creation) as ecart_jours
    from offres b
    join offres a
      on  a.id_entreprise = b.id_entreprise
      and a.intitule      = b.intitule
      and a.code_insee    = b.code_insee
      and a.id_offre     <> b.id_offre
      and a.derniere_collecte < b.premiere_collecte                      -- A avait disparu
      and b.date_creation >= a.date_creation + {{ ecart_minimum }}
    group by b.id_offre
),

classees as (
    select
        o.id_offre,
        o.id_entreprise,
        o.code_insee,
        r.ecart_jours,
        i.type                                  as type_intermediaire,
        row_number() over (
            partition by o.id_entreprise, o.code_insee,
                         (i.type is null and r.id_offre is not null)
            order by o.date_creation, o.id_offre
        )                                       as rang_employeur
    from offres o
    join republiees r on r.id_offre = o.id_offre
    left join intermediaires i on i.id_entreprise = o.id_entreprise
)

select
    id_offre,
    ecart_jours,
    type_intermediaire,
    type_intermediaire is null
        and rang_employeur <= {{ plafond_par_employeur }}  as republication_retenue
from classees
