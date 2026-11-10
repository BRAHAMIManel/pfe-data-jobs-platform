-- Une offre ne peut pas etre en ligne depuis un nombre de jours negatif.
select id_offre, jours_en_ligne
from {{ source('entrepot', 'fait_offre') }}
where jours_en_ligne < 0
