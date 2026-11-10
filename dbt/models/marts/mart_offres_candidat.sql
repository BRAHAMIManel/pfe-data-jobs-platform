-- Table lue par l'application Streamlit : une ligne par offre, avec la
-- liste de ses competences. C'est exactement ce dont le calcul du score
-- a besoin, prepare une fois par jour au lieu d'a chaque visite.
with competences as (
    select
        p.id_offre,
        array_agg(c.libelle order by c.libelle) as competences
    from {{ source('entrepot', 'pont_offre_competence') }} p
    join {{ source('entrepot', 'dim_competence') }} c on c.id_competence = p.id_competence
    group by p.id_offre
)

select
    o.*,
    coalesce(c.competences, array[]::text[]) as competences,
    coalesce(r.republication_retenue, false)  as republication
from {{ ref('stg_offres') }} o
left join competences c on c.id_offre = o.id_offre
left join {{ ref('int_republications') }} r on r.id_offre = o.id_offre
