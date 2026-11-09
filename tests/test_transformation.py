"""
Tests de la couche transformation.

Chaque test correspond a une regle metier explicite. Plusieurs d'entre
eux encadrent des bugs reellement rencontres pendant le projet, pour
qu'ils ne puissent pas reapparaitre.
"""

from datetime import date

import pytest

from transformation import (
    extraire_competences,
    normaliser_ville,
    parser_date,
    parser_lieu,
    parser_salaire,
)


# ------------------------------------------------ normalisation des villes

class TestNormaliserVille:
    """Bug rencontre : Paris apparaissait en quatre lignes distinctes
    (Paris, PARIS, Paris 1er Arrondissement, Paris 9e Arrondissement),
    ce qui le faisait passer pour une niche alors qu'il concentre le plus
    d'offres de France."""

    @pytest.mark.parametrize("entree, attendu", [
        ("Paris", "PARIS"),
        ("PARIS", "PARIS"),
        ("Paris 1er Arrondissement", "PARIS"),
        ("Paris 9e Arrondissement", "PARIS"),
        ("Lyon 1er Arrondissement", "LYON"),
        ("Marseille 15e Arrondissement", "MARSEILLE"),
    ])
    def test_variantes_fusionnent(self, entree, attendu):
        assert normaliser_ville(entree) == attendu

    def test_accents_supprimes(self):
        assert normaliser_ville("Saint-Étienne") == "SAINT-ETIENNE"

    def test_traits_union_conserves(self):
        assert normaliser_ville("Aix-en-Provence") == "AIX-EN-PROVENCE"

    def test_espaces_superflus_ignores(self):
        assert normaliser_ville("  Nantes  ") == "NANTES"

    @pytest.mark.parametrize("entree", [None, "", "   "])
    def test_valeurs_vides(self, entree):
        assert normaliser_ville(entree) is None

    def test_numero_final_retire(self):
        # Choix assume : "PARIS 15" etait compte a part de "PARIS". Aucune
        # commune francaise ne finit par un nombre, on retire donc tout
        # numero final.
        assert normaliser_ville("PARIS 15") == "PARIS"
        assert normaliser_ville("Lyon 3eme") == "LYON"


# -------------------------------------------------------- decoupage du lieu

class TestParserLieu:

    def test_libelle_departement_et_ville(self):
        lieu = parser_lieu({
            "libelle": "55 - Revigny-sur-Ornain",
            "commune": "55427",
            "codePostal": "55800",
            "latitude": 48.828119,
            "longitude": 4.987223,
        })
        assert lieu["code_insee"] == "55427"
        assert lieu["departement"] == "55"
        assert lieu["ville"] == "Revigny-sur-Ornain"
        assert lieu["ville_normalisee"] == "REVIGNY-SUR-ORNAIN"
        assert lieu["code_postal"] == "55800"

    def test_libelle_sans_separateur(self):
        lieu = parser_lieu({"libelle": "Nantes", "commune": "44109"})
        assert lieu["departement"] is None
        assert lieu["ville"] == "Nantes"

    def test_sans_code_insee_renvoie_none(self):
        # Sans cle naturelle, la ligne ne peut pas entrer en dimension.
        assert parser_lieu({"libelle": "75 - Paris"}) is None

    def test_lieu_absent(self):
        assert parser_lieu(None) is None

    def test_coordonnees_absentes_tolerees(self):
        lieu = parser_lieu({"libelle": "75 - Paris", "commune": "75101"})
        assert lieu["latitude"] is None


# ------------------------------------------------------- parsing du salaire

class TestParserSalaire:

    def test_fourchette_mensuelle(self):
        minimum, maximum, periode = parser_salaire(
            {"libelle": "Mensuel de 2500.0 Euros à 3200.0 Euros"}
        )
        assert (minimum, maximum, periode) == (2500.0, 3200.0, "mensuel")

    def test_montant_unique_borne_les_deux_cotes(self):
        minimum, maximum, periode = parser_salaire(
            {"libelle": "Annuel de 45000.0 Euros"}
        )
        assert minimum == maximum == 45000.0
        assert periode == "annuel"

    def test_periode_horaire(self):
        _, _, periode = parser_salaire({"libelle": "Horaire de 15.5 Euros"})
        assert periode == "horaire"

    @pytest.mark.parametrize("entree", [
        None,
        {},
        {"libelle": None},
        {"libelle": ""},
        {"libelle": "Selon profil"},
        {"libelle": "A negocier"},
    ])
    def test_libelles_non_exploitables(self, entree):
        # Beaucoup d'offres n'affichent aucun salaire : la fonction doit
        # renvoyer des valeurs nulles, jamais lever d'exception.
        assert parser_salaire(entree) == (None, None, None)


# ---------------------------------------------------------- parsing de date

class TestParserDate:

    def test_format_iso_avec_fuseau(self):
        assert parser_date("2026-09-11T20:12:08.543Z") == date(2026, 9, 11)

    def test_date_simple(self):
        assert parser_date("2026-09-11") == date(2026, 9, 11)

    @pytest.mark.parametrize("entree", [None, "", "pas une date", "11/09/2026"])
    def test_valeurs_invalides(self, entree):
        assert parser_date(entree) is None


# ------------------------------------------------ extraction des competences

class TestExtraireCompetences:

    @staticmethod
    def libelles(description):
        return {libelle for libelle, _ in extraire_competences(description)}

    def test_detection_simple(self):
        trouvees = self.libelles(
            "Développeur Python, maîtrise de Docker et Kubernetes exigée."
        )
        assert {"Python", "Docker", "Kubernetes"} <= trouvees

    def test_insensible_a_la_casse_et_aux_accents(self):
        assert "Python" in self.libelles("Maitrise de PYTHON attendue")

    def test_r_ne_matche_pas_ruby(self):
        # La competence "R" ne doit pas se declencher sur "Ruby".
        assert "R" not in self.libelles("Développeur Ruby confirmé")

    def test_go_ne_matche_pas_google(self):
        assert "Go" not in self.libelles("Experience sur Google Cloud")

    @pytest.mark.parametrize("terme", ["C#", ".NET", "C++"])
    def test_competences_a_caracteres_speciaux(self, terme):
        # Bug corrige : les limites de mot rendaient ces competences
        # introuvables, car '#', '.' et '+' ne sont pas des caracteres
        # de mot. Elles n'etaient jamais extraites.
        assert terme in self.libelles(f"Développement en {terme} sur Windows")

    def test_description_vide(self):
        assert extraire_competences("") == []
        assert extraire_competences(None) == []

    def test_aucune_competence_reconnue(self):
        assert extraire_competences("Poste de jardinier paysagiste") == []

    def test_categorie_renvoyee(self):
        resultat = dict(extraire_competences("Nous utilisons PostgreSQL"))
        assert resultat["PostgreSQL"] == "Donnees"