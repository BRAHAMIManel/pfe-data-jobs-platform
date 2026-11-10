-- Experience demandee entre 0 et 30 ans. Au-dela, le parsing s'est trompe.
-- Avertissement seulement : une offre etrange ne doit pas bloquer la journee.
{{ config(severity='warn') }}
select id_offre, experience_annees
from {{ source('entrepot', 'fait_offre') }}
where experience_annees < 0 or experience_annees > 30
