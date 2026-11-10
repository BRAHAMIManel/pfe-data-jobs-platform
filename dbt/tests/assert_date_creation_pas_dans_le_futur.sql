-- Une offre ne peut pas avoir ete publiee apres sa derniere collecte.
select id_offre, date_creation, derniere_collecte
from {{ source('entrepot', 'fait_offre') }}
where date_creation > derniere_collecte
