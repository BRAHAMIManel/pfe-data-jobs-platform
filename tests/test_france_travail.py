"""
Tests du client France Travail.

Aucun appel reseau : les reponses de l'API sont simulees. On teste la
logique de pagination, la deduplication et le filtre de fraicheur.
"""

from datetime import datetime, timedelta, timezone

import pytest

import france_travail
from france_travail import dedupliquer, filtrer_offres, get_offres_par_rome


class FausseReponse:
    """Imite le minimum d'une reponse requests."""

    def __init__(self, status_code, resultats=None):
        self.status_code = status_code
        self._resultats = resultats or []
        self.text = ""

    def json(self):
        return {"resultats": self._resultats}


def offres_factices(nombre, prefixe="off"):
    return [{"id": f"{prefixe}{i}"} for i in range(nombre)]


def maintenant_moins(jours):
    date = datetime.now(timezone.utc) - timedelta(days=jours)
    return date.isoformat().replace("+00:00", "Z")


# --------------------------------------------------------------- pagination

class TestPagination:

    def test_arret_sur_page_incomplete(self, monkeypatch):
        """Bug corrige : quand un metier renvoyait moins d'offres que
        demande, la boucle continuait et finissait par construire un
        intervalle inverse (range=600-499), rejete en HTTP 400."""
        appels = []

        def faux_get(url, headers=None, params=None, timeout=None):
            appels.append(params["range"])
            debut, fin = (int(x) for x in params["range"].split("-"))
            assert debut <= fin, f"intervalle inverse demande : {params['range']}"
            return FausseReponse(200, offres_factices(40))  # < 150 demandees

        monkeypatch.setattr(france_travail.requests, "get", faux_get)

        offres = get_offres_par_rome("token", "M1805", total_souhaite=500)

        assert len(offres) == 40
        assert len(appels) == 1, "une page incomplete doit arreter la boucle"

    def test_plafond_respecte(self, monkeypatch):
        def faux_get(url, headers=None, params=None, timeout=None):
            debut, fin = (int(x) for x in params["range"].split("-"))
            return FausseReponse(200, offres_factices(fin - debut + 1))

        monkeypatch.setattr(france_travail.requests, "get", faux_get)

        offres = get_offres_par_rome("token", "M1805", total_souhaite=300)
        assert len(offres) == 300

    def test_code_204_termine_la_collecte(self, monkeypatch):
        def faux_get(url, headers=None, params=None, timeout=None):
            return FausseReponse(204)

        monkeypatch.setattr(france_travail.requests, "get", faux_get)
        assert get_offres_par_rome("token", "M1805") == []

    def test_reessai_sur_erreur_serveur(self, monkeypatch):
        tentatives = {"n": 0}

        def faux_get(url, headers=None, params=None, timeout=None):
            tentatives["n"] += 1
            if tentatives["n"] < 3:
                return FausseReponse(503)
            return FausseReponse(200, offres_factices(10))

        monkeypatch.setattr(france_travail.requests, "get", faux_get)
        monkeypatch.setattr(france_travail.time, "sleep", lambda s: None)

        offres = get_offres_par_rome("token", "M1805", total_souhaite=50)
        assert len(offres) == 10
        assert tentatives["n"] == 3

    def test_erreur_client_non_reessayee(self, monkeypatch):
        tentatives = {"n": 0}

        def faux_get(url, headers=None, params=None, timeout=None):
            tentatives["n"] += 1
            return FausseReponse(400)

        monkeypatch.setattr(france_travail.requests, "get", faux_get)

        assert get_offres_par_rome("token", "M1805") == []
        assert tentatives["n"] == 1, "une erreur 4xx ne doit pas etre reessayee"


# ------------------------------------------------------------ deduplication

class TestDedupliquer:

    def test_doublons_supprimes(self):
        offres = [{"id": "a"}, {"id": "b"}, {"id": "a"}]
        assert len(dedupliquer(offres)) == 2

    def test_premiere_occurrence_conservee(self):
        offres = [{"id": "a", "v": 1}, {"id": "a", "v": 2}]
        assert dedupliquer(offres)[0]["v"] == 1

    def test_offre_sans_identifiant_ecartee(self):
        assert dedupliquer([{"intitule": "sans id"}]) == []

    def test_liste_vide(self):
        assert dedupliquer([]) == []


# ------------------------------------------------------ filtre de fraicheur

class TestFiltrerOffres:

    def test_offre_recente_conservee(self):
        gardees, _ = filtrer_offres([{"dateCreation": maintenant_moins(5)}])
        assert len(gardees) == 1

    def test_offre_ancienne_ecartee(self):
        gardees, stats = filtrer_offres([{"dateCreation": maintenant_moins(45)}])
        assert gardees == []
        assert stats["rejetees_trop_anciennes"] == 1

    def test_offre_sans_date_comptee_a_part(self):
        gardees, stats = filtrer_offres([{"intitule": "sans date"}])
        assert gardees == []
        assert stats["rejetees_sans_date"] == 1

    def test_signal_manque_candidats_compte(self):
        _, stats = filtrer_offres([
            {"dateCreation": maintenant_moins(2), "offresManqueCandidats": True},
            {"dateCreation": maintenant_moins(2), "offresManqueCandidats": False},
            {"dateCreation": maintenant_moins(2)},
        ])
        assert stats["dont_peu_concurrentielles"] == 1
        assert stats["total_gardees"] == 3

    def test_seuil_personnalisable(self):
        offres = [{"dateCreation": maintenant_moins(45)}]
        gardees, _ = filtrer_offres(offres, jours_max=60)
        assert len(gardees) == 1

    def test_statistiques_coherentes(self):
        offres = [
            {"dateCreation": maintenant_moins(1)},
            {"dateCreation": maintenant_moins(100)},
            {"intitule": "sans date"},
        ]
        _, stats = filtrer_offres(offres)
        assert stats["total_initial"] == 3
        assert (
            stats["total_gardees"]
            + stats["rejetees_trop_anciennes"]
            + stats["rejetees_sans_date"]
        ) == stats["total_initial"]
