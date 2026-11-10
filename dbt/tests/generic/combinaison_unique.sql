-- Test generique ecrit a la main : aucune combinaison de colonnes ne doit
-- apparaitre deux fois. Renvoie les lignes en faute (0 ligne = test reussi).
{% test combinaison_unique(model, columns) %}
select {{ columns | join(', ') }}, count(*) as nb
from {{ model }}
group by {{ columns | join(', ') }}
having count(*) > 1
{% endtest %}
