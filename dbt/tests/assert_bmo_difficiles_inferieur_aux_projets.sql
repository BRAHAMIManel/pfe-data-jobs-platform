-- Un departement ne peut pas avoir plus de projets difficiles que de projets.
select departement, code_fap, projets, difficiles
from {{ ref('bmo_2026_informatique') }}
where difficiles > projets or projets < 0 or difficiles < 0
