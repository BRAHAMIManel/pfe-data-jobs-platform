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

-- ---------------------------------------------------------------
-- Application finale : lien, experience, famille de poste, region
-- ---------------------------------------------------------------

-- Familles de postes proposees aux candidats (scripts/postes.json).
CREATE TABLE IF NOT EXISTS dim_poste (
    id_poste  VARCHAR(10) PRIMARY KEY,
    libelle   TEXT NOT NULL
);
ALTER TABLE dim_poste ADD COLUMN IF NOT EXISTS categorie TEXT;

-- Colonnes ajoutees a une base existante : sans effet si deja presentes.
ALTER TABLE fait_offre ADD COLUMN IF NOT EXISTS url_offre TEXT;
ALTER TABLE fait_offre ADD COLUMN IF NOT EXISTS experience_annees NUMERIC(4, 1);
ALTER TABLE fait_offre ADD COLUMN IF NOT EXISTS id_poste VARCHAR(10)
    REFERENCES dim_poste(id_poste);

CREATE INDEX IF NOT EXISTS idx_fait_poste ON fait_offre (id_poste);

-- Offres mal codees, sans rapport avec l'informatique (scripts/hors_perimetre.json).
-- Elles sont gardees mais exclues de toutes les analyses.
ALTER TABLE fait_offre ADD COLUMN IF NOT EXISTS hors_perimetre BOOLEAN NOT NULL DEFAULT FALSE;

-- Referentiel geographique (scripts/regions.json) : departement -> region.
CREATE TABLE IF NOT EXISTS ref_region (
    code_region   VARCHAR(3) PRIMARY KEY,
    nom           TEXT NOT NULL,
    abrev         VARCHAR(5) NOT NULL,
    grille_ligne  INT,
    grille_col    INT
);

CREATE TABLE IF NOT EXISTS ref_departement (
    departement   VARCHAR(5) PRIMARY KEY,
    code_region   VARCHAR(3) NOT NULL REFERENCES ref_region(code_region)
);

CREATE TABLE IF NOT EXISTS pont_offre_competence (
    id_offre       VARCHAR(20) REFERENCES fait_offre(id_offre) ON DELETE CASCADE,
    id_competence  INT REFERENCES dim_competence(id_competence),
    PRIMARY KEY (id_offre, id_competence)
);

-- Agregat du detecteur de niches : un cliche par jour de calcul, afin de
-- suivre l'evolution de la tension dans le temps et non seulement son
-- etat courant.
CREATE TABLE IF NOT EXISTS agg_tension (
    date_calcul       DATE NOT NULL,
    code_rome         VARCHAR(10) REFERENCES dim_metier(code_rome),
    departement       VARCHAR(5),
    nb_offres         INT NOT NULL,
    nb_persistantes   INT NOT NULL,
    taux_brut         NUMERIC(6, 4),
    taux_reference    NUMERIC(6, 4),
    score             NUMERIC(6, 4),
    mediane_jours     NUMERIC(6, 1),
    PRIMARY KEY (date_calcul, code_rome, departement)
);

CREATE INDEX IF NOT EXISTS idx_tension_score
    ON agg_tension (date_calcul, score DESC);

-- Index sur les axes d'analyse du detecteur de niches.
CREATE INDEX IF NOT EXISTS idx_fait_rome_lieu
    ON fait_offre (code_rome, code_insee);
CREATE INDEX IF NOT EXISTS idx_fait_derniere_collecte
    ON fait_offre (derniere_collecte);
CREATE INDEX IF NOT EXISTS idx_pont_competence
    ON pont_offre_competence (id_competence);

-- Agregat de l'application finale : indice de penurie par region et par
-- ville, sur toutes les offres. Un cliche par jour, pour suivre l'evolution.
-- La partie personnelle du score (adequation au CV, zone, niveau) se
-- calcule dans l'application, car elle depend de chaque candidat.
CREATE TABLE IF NOT EXISTS agg_opportunite (
    date_calcul        DATE NOT NULL,
    niveau             VARCHAR(10) NOT NULL,   -- 'region' ou 'ville'
    code               TEXT NOT NULL,          -- code region, ou ville|departement
    libelle            TEXT NOT NULL,
    code_region        VARCHAR(3),
    nb_offres          INT NOT NULL,
    nb_persistantes    INT NOT NULL,           -- en ligne depuis plus de 30 jours
    nb_manque          INT NOT NULL,           -- signalees manque de candidats
    nb_en_ligne        INT NOT NULL,           -- vues a la derniere collecte
    nb_recentes        INT NOT NULL,           -- en ligne et publiees depuis 14 jours ou moins
    mediane_jours      NUMERIC(6, 1),
    indice_penurie     NUMERIC(6, 4),          -- 1,00 = moyenne nationale
    fiabilite          VARCHAR(10) NOT NULL,   -- fiable / indicatif / fragile
    PRIMARY KEY (date_calcul, niveau, code)
);