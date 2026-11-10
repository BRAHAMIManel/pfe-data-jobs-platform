-- Une republication d'intermediaire (ESN, interim, plateforme...) ne doit
-- jamais compter dans le signal de penurie.
select id_offre, type_intermediaire
from {{ ref('int_republications') }}
where republication_retenue and type_intermediaire is not null
