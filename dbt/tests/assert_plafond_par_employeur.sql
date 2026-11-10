-- Au plus 3 republications retenues par employeur et par commune.
select f.id_entreprise, f.code_insee, count(*) as retenues
from {{ ref('int_republications') }} r
join {{ source('entrepot', 'fait_offre') }} f on f.id_offre = r.id_offre
where r.republication_retenue
group by f.id_entreprise, f.code_insee
having count(*) > 3
