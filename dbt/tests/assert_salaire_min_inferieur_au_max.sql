-- Un salaire minimum ne peut pas depasser le maximum de la meme offre.
-- Renvoie les offres en faute : 0 ligne = test reussi.
select id_offre, salaire_min, salaire_max
from {{ source('entrepot', 'fait_offre') }}
where salaire_min is not null
  and salaire_max is not null
  and salaire_min > salaire_max
