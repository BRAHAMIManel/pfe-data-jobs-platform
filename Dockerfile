FROM apache/airflow:2.9.3-python3.11

# --- Java : PySpark en a besoin pour faire tourner Spark -------------------
# L'installation systeme se fait en root, puis on revient a l'utilisateur
# airflow, comme le demande l'image officielle.
USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends openjdk-17-jre-headless \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* \
    && ln -s "$(dirname "$(dirname "$(readlink -f "$(which java)")")")" /usr/lib/jvm/java-pfe

# Chemin identique sur PC Intel/AMD et sur Mac ARM grace au lien ci-dessus.
ENV JAVA_HOME=/usr/lib/jvm/java-pfe
USER airflow

# --- Bibliotheques Python ------------------------------------------------
COPY requirements.txt /requirements.txt

RUN pip install --no-cache-dir -r /requirements.txt

# --- dbt, dans son propre environnement virtuel ---------------------------
# dbt et Airflow dependent de versions differentes des memes bibliotheques :
# les separer evite tout conflit. On l'appelle par son chemin complet.
RUN python -m venv /home/airflow/dbt-venv \
    && /home/airflow/dbt-venv/bin/pip install --no-cache-dir \
       dbt-core==1.8.8 dbt-postgres==1.8.2