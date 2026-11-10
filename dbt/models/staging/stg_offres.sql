-- Offres du perimetre informatique, avec leur lieu, leur region et leur
-- contrat. Une ligne par offre. Les offres hors perimetre (serveur de
-- restaurant, BTP...) et celles sans ville exploitable sont exclues ici,
-- une seule fois, pour tous les modeles en aval.
select
    f.id_offre,
    f.intitule,
    f.url_offre,
    f.id_poste,
    f.code_rome,
    f.date_creation,
    f.premiere_collecte,
    f.derniere_collecte,
    f.jours_en_ligne,
    coalesce(f.manque_candidats, false)  as manque,
    f.experience_annees::float           as experience_annees,
    f.salaire_min::float                 as salaire_min,
    f.salaire_max::float                 as salaire_max,
    f.salaire_periode,
    l.ville,
    l.ville_normalisee,
    l.departement,
    l.latitude::float                    as latitude,
    l.longitude::float                   as longitude,
    d.code_region,
    r.nom                                as region,
    e.nom                                as entreprise,
    ct.type_contrat,
    ct.alternance
from {{ source('entrepot', 'fait_offre') }} f
join {{ source('entrepot', 'dim_lieu') }} l          on l.code_insee = f.code_insee
join {{ source('entrepot', 'ref_departement') }} d   on d.departement = l.departement
join {{ source('entrepot', 'ref_region') }} r        on r.code_region = d.code_region
left join {{ source('entrepot', 'dim_entreprise') }} e on e.id_entreprise = f.id_entreprise
left join {{ source('entrepot', 'dim_contrat') }} ct   on ct.id_contrat = f.id_contrat
where l.ville_normalisee is not null
  and not f.hors_perimetre
