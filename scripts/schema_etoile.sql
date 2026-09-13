-- Schema en etoile — offres d'emploi
-- Idempotent : peut etre rejoue a chaque execution du DAG.

CREATE TABLE IF NOT EXISTS dim_metier (
    code_rome    VARCHAR(10) PRIMARY KEY,
    libelle      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS dim_lieu (
    code_insee   VARCHAR(10) PRIMARY KEY,
    ville        TEXT,
    ville_normalisee TEXT,
    code_postal  VARCHAR(10),
    departement  VARCHAR(5),
    latitude     NUMERIC(9, 6),
    longitude    NUMERIC(9, 6)
);

-- Pour une base creee avant l'ajout de la colonne.
ALTER TABLE dim_lieu ADD COLUMN IF NOT EXISTS ville_normalisee TEXT;

CREATE INDEX IF NOT EXISTS idx_lieu_departement
    ON dim_lieu (departement);
CREATE INDEX IF NOT EXISTS idx_lieu_ville_normalisee
    ON dim_lieu (ville_normalisee);

CREATE TABLE IF NOT EXISTS dim_entreprise (
    id_entreprise    SERIAL PRIMARY KEY,
    nom              TEXT NOT NULL,
    secteur_libelle  TEXT,
    tranche_effectif TEXT,
    UNIQUE (nom, secteur_libelle)
);

CREATE TABLE IF NOT EXISTS dim_contrat (
    id_contrat        SERIAL PRIMARY KEY,
    type_contrat      VARCHAR(20),
    type_libelle      TEXT,
    experience_exige  VARCHAR(5),
    qualification     TEXT,
    alternance        BOOLEAN,
    UNIQUE (type_contrat, experience_exige, qualification, alternance)
);

CREATE TABLE IF NOT EXISTS dim_date (
    id_date  DATE PRIMARY KEY,
    annee    INT NOT NULL,
    mois     INT NOT NULL,
    semaine  INT NOT NULL,
    jour_semaine INT NOT NULL
);

CREATE TABLE IF NOT EXISTS dim_competence (
    id_competence  SERIAL PRIMARY KEY,
    libelle        TEXT NOT NULL UNIQUE,
    categorie      TEXT
);

-- Table de faits. Une ligne par offre, jamais dupliquee :
-- les executions suivantes mettent a jour derniere_collecte.
CREATE TABLE IF NOT EXISTS fait_offre (
    id_offre           VARCHAR(20) PRIMARY KEY,
    code_rome          VARCHAR(10) REFERENCES dim_metier(code_rome),
    code_insee         VARCHAR(10) REFERENCES dim_lieu(code_insee),
    id_entreprise      INT REFERENCES dim_entreprise(id_entreprise),
    id_contrat         INT REFERENCES dim_contrat(id_contrat),
    date_creation      DATE REFERENCES dim_date(id_date),
    premiere_collecte  DATE NOT NULL,
    derniere_collecte  DATE NOT NULL,
    jours_en_ligne     INT DEFAULT 0,
    nombre_postes      INT,
    manque_candidats   BOOLEAN,
    salaire_min        NUMERIC(10, 2),
    salaire_max        NUMERIC(10, 2),
    salaire_periode    VARCHAR(20),
    intitule           TEXT,
    source             VARCHAR(20) NOT NULL
);

CREATE TABLE IF NOT EXISTS pont_offre_competence (
    id_offre       VARCHAR(20) REFERENCES fait_offre(id_offre) ON DELETE CASCADE,
    id_competence  INT REFERENCES dim_competence(id_competence),
    PRIMARY KEY (id_offre, id_competence)
);

-- Index sur les axes d'analyse du detecteur de niches.
CREATE INDEX IF NOT EXISTS idx_fait_rome_lieu
    ON fait_offre (code_rome, code_insee);
CREATE INDEX IF NOT EXISTS idx_fait_derniere_collecte
    ON fait_offre (derniere_collecte);
CREATE INDEX IF NOT EXISTS idx_pont_competence
    ON pont_offre_competence (id_competence);