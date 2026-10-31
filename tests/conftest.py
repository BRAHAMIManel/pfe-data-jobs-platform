"""
Configuration commune des tests.

Les tests portent sur les fonctions pures du pipeline : aucune base de
donnees, aucun appel reseau. Ils doivent tourner en quelques secondes.
"""

import os
import sys
from pathlib import Path

# Dans le conteneur Airflow, les modules sont dans /opt/airflow/scripts.
# En dehors, ils sont dans ./scripts a la racine du depot.
RACINE = Path(__file__).resolve().parent.parent
CANDIDATS = [Path("/opt/airflow/scripts"), RACINE / "scripts"]

for dossier in CANDIDATS:
    if dossier.is_dir():
        sys.path.insert(0, str(dossier))
        dictionnaire = dossier / "competences_it.json"
        if dictionnaire.is_file():
            # Doit etre defini AVANT l'import de transformation : le module
            # lit cette variable au chargement.
            os.environ.setdefault("CHEMIN_COMPETENCES", str(dictionnaire))
        break
