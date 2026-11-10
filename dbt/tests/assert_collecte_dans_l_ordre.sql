-- La premiere collecte d'une offre precede (ou egale) la derniere.
select id_offre, premiere_collecte, derniere_collecte
from {{ source('entrepot', 'fait_offre') }}
where premiere_collecte > derniere_collecte
