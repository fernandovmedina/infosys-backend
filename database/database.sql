-- =============================================================================
-- infosys-backend — complete database schema
-- =============================================================================
-- Target engine: PostgreSQL 14+
--
-- This file is the single source of truth for the schema. It is idempotent and
-- safe to run repeatedly. Future changes must NOT be made here: add them to
-- database/alter.sql instead (see that file for the rationale).
--
-- Run with:  psql "$DATABASE_URL" -f database/database.sql
-- =============================================================================

-- -----------------------------------------------------------------------------
-- Extensions
-- -----------------------------------------------------------------------------
-- pg_trgm powers the fuzzy company-name search (GIN trigram index + similarity).
-- unaccent is not used at query time (normalization happens in Python so that
-- the indexes stay plain B-tree/GIN lookups), but it is installed so that ad-hoc
-- SQL exploration of the dataset can fold accents too.
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS unaccent;


-- -----------------------------------------------------------------------------
-- Table: sat_blacklist_record
-- -----------------------------------------------------------------------------
-- One row per *procedure* published in the SAT "Artículo 69-B del CFF" listing,
-- NOT one row per taxpayer.
--
-- A taxpayer may legitimately appear several times: the same RFC can hold a
-- "Presunto" procedure and a separate "Definitivo" one, each with its own
-- oficio numbers. In the reference dataset 78 distinct RFCs occupy 322 rows,
-- and even (rfc, situacion) is not unique. RFC therefore CANNOT be a primary
-- or unique key; `source_hash` is used as the idempotency key instead.
CREATE TABLE IF NOT EXISTS sat_blacklist_record (
    id                          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    -- Sequence number of the row in the published listing (column "No").
    -- Informational only: it is reassigned by SAT on every publication.
    source_row_number           integer,

    -- ---- Identity -----------------------------------------------------------
    rfc                         text        NOT NULL,
    -- Uppercased, punctuation/whitespace stripped. Populated by the importer
    -- using app.sat.normalization.normalize_rfc so that lookups are a plain
    -- equality test against an indexed column (no function call on the column).
    rfc_normalized              text        NOT NULL,

    name                        text        NOT NULL,
    -- Accent-folded, uppercased, punctuation-stripped, whitespace-collapsed.
    name_normalized             text        NOT NULL,
    -- As above, with trailing corporate suffixes removed ("SA DE CV",
    -- "S DE RL DE CV", ...). This is the column the fuzzy search targets.
    name_core                   text        NOT NULL,

    -- ---- Status -------------------------------------------------------------
    -- Raw value from the listing ("Presunto", "Definitivo", "Desvirtuado",
    -- "Sentencia Favorable"). Deliberately kept as free text rather than an
    -- ENUM or CHECK constraint: an automated dataset refresh must not fail
    -- wholesale if SAT introduces a new status value.
    situacion                   text        NOT NULL,

    -- True when the taxpayer rebutted the presumption ("Desvirtuado") or won a
    -- favourable ruling ("Sentencia Favorable"). Derived by the importer.
    -- Unknown/new status values default to false (fail-safe: not cleared).
    is_cleared                  boolean     NOT NULL DEFAULT false,

    -- True for rows SAT publishes with the identity suppressed
    -- (rfc = 'XXXXXXXXXXXX', name = 'Información suprimida en cumplimiento...').
    -- They are stored so the table reconciles row-for-row with the published
    -- listing, but every search excludes them so that a query for the literal
    -- placeholder can never produce a false positive.
    is_redacted                 boolean     NOT NULL DEFAULT false,

    -- ---- Procedure trail ----------------------------------------------------
    -- Eight (oficio, publication date) pairs, preserved verbatim from the CSV.
    presuncion_sat_oficio       text,
    presuncion_sat_publicacion  date,
    presuncion_dof_oficio       text,
    presuncion_dof_publicacion  date,
    desvirtuado_sat_oficio      text,
    desvirtuado_sat_publicacion date,
    desvirtuado_dof_oficio      text,
    desvirtuado_dof_publicacion date,
    definitivo_sat_oficio       text,
    definitivo_sat_publicacion  date,
    definitivo_dof_oficio       text,
    definitivo_dof_publicacion  date,
    sentencia_sat_oficio        text,
    sentencia_sat_publicacion   date,
    sentencia_dof_oficio        text,
    sentencia_dof_publicacion   date,

    -- ---- Bookkeeping --------------------------------------------------------
    -- SHA-256 over every source column except "No". Two publications of the
    -- same procedure hash identically, which makes the import idempotent and
    -- collapses the exact-duplicate rows present in the source file.
    source_hash                 bytea       NOT NULL,

    created_at                  timestamptz NOT NULL DEFAULT now(),
    updated_at                  timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT sat_blacklist_record_source_hash_key UNIQUE (source_hash),
    CONSTRAINT sat_blacklist_record_rfc_not_blank   CHECK (length(btrim(rfc_normalized)) > 0),
    CONSTRAINT sat_blacklist_record_name_not_blank  CHECK (length(btrim(name_normalized)) > 0)
);

COMMENT ON TABLE  sat_blacklist_record IS
    'SAT Art. 69-B CFF listing. One row per published procedure, not per taxpayer.';
COMMENT ON COLUMN sat_blacklist_record.source_hash IS
    'SHA-256 of the source row excluding the "No" column; idempotency key for the importer.';


-- -----------------------------------------------------------------------------
-- Indexes
-- -----------------------------------------------------------------------------
-- All search indexes are PARTIAL (WHERE NOT is_redacted). The 238 redacted rows
-- are excluded from the index itself, so they cost nothing to skip at query time
-- and can never be returned.

-- Exact RFC lookup. Non-unique by design: see the table comment above.
CREATE INDEX IF NOT EXISTS sat_blacklist_record_rfc_normalized_idx
    ON sat_blacklist_record (rfc_normalized)
    WHERE NOT is_redacted;

-- Exact company-name lookup, full normalized form.
CREATE INDEX IF NOT EXISTS sat_blacklist_record_name_normalized_idx
    ON sat_blacklist_record (name_normalized)
    WHERE NOT is_redacted;

-- Exact company-name lookup ignoring corporate suffixes.
CREATE INDEX IF NOT EXISTS sat_blacklist_record_name_core_idx
    ON sat_blacklist_record (name_core)
    WHERE NOT is_redacted;

-- Fuzzy company-name search: trigram GIN index supporting `%` (similarity).
CREATE INDEX IF NOT EXISTS sat_blacklist_record_name_core_trgm_idx
    ON sat_blacklist_record USING gin (name_core gin_trgm_ops)
    WHERE NOT is_redacted;


-- -----------------------------------------------------------------------------
-- updated_at maintenance
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION sat_blacklist_touch_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS sat_blacklist_record_touch_updated_at ON sat_blacklist_record;
CREATE TRIGGER sat_blacklist_record_touch_updated_at
    BEFORE UPDATE ON sat_blacklist_record
    FOR EACH ROW
    EXECUTE FUNCTION sat_blacklist_touch_updated_at();


-- -----------------------------------------------------------------------------
-- Bulk import staging area
-- -----------------------------------------------------------------------------
-- The importer never issues one INSERT per row. It COPYs the parsed CSV into
-- this unlogged staging table and then calls sat_blacklist_merge_staging(),
-- which performs a single set-based upsert. Keeping the merge in SQL means the
-- Python importer and `psql -f database/exec.sql` share one definition.
CREATE UNLOGGED TABLE IF NOT EXISTS sat_blacklist_staging (
    source_row_number           integer,
    rfc                         text,
    rfc_normalized              text,
    name                        text,
    name_normalized             text,
    name_core                   text,
    situacion                   text,
    is_cleared                  boolean,
    is_redacted                 boolean,
    presuncion_sat_oficio       text,
    presuncion_sat_publicacion  date,
    presuncion_dof_oficio       text,
    presuncion_dof_publicacion  date,
    desvirtuado_sat_oficio      text,
    desvirtuado_sat_publicacion date,
    desvirtuado_dof_oficio      text,
    desvirtuado_dof_publicacion date,
    definitivo_sat_oficio       text,
    definitivo_sat_publicacion  date,
    definitivo_dof_oficio       text,
    definitivo_dof_publicacion  date,
    sentencia_sat_oficio        text,
    sentencia_sat_publicacion   date,
    sentencia_dof_oficio        text,
    sentencia_dof_publicacion   date,
    source_hash                 bytea
);

COMMENT ON TABLE sat_blacklist_staging IS
    'Scratch space for bulk loads. Truncated at the start of every import run.';


-- Merge whatever is currently in the staging table into sat_blacklist_record.
--
-- Returns the number of rows inserted, updated and skipped-as-duplicate, so the
-- importer can report them without a second round of counting queries.
--
-- Idempotency: `source_hash` is the conflict target, so re-running an unchanged
-- import inserts 0 and updates 0. Rows that repeat *within* one staging batch
-- (the source file contains 32 such exact duplicates) are collapsed by the
-- DISTINCT ON before the upsert ever sees them -- without it, Postgres would
-- raise "ON CONFLICT DO UPDATE command cannot affect row a second time".
CREATE OR REPLACE FUNCTION sat_blacklist_merge_staging()
RETURNS TABLE (inserted bigint, updated bigint, duplicates_collapsed bigint)
LANGUAGE plpgsql
AS $$
DECLARE
    staged_total   bigint;
    staged_distinct bigint;
BEGIN
    SELECT count(*)                     INTO staged_total    FROM sat_blacklist_staging;
    SELECT count(DISTINCT source_hash)  INTO staged_distinct FROM sat_blacklist_staging;

    RETURN QUERY
    WITH deduplicated AS (
        SELECT DISTINCT ON (source_hash) *
        FROM sat_blacklist_staging
        ORDER BY source_hash, source_row_number
    ), merged AS (
        INSERT INTO sat_blacklist_record AS target (
            source_row_number, rfc, rfc_normalized, name, name_normalized, name_core,
            situacion, is_cleared, is_redacted,
            presuncion_sat_oficio,  presuncion_sat_publicacion,
            presuncion_dof_oficio,  presuncion_dof_publicacion,
            desvirtuado_sat_oficio, desvirtuado_sat_publicacion,
            desvirtuado_dof_oficio, desvirtuado_dof_publicacion,
            definitivo_sat_oficio,  definitivo_sat_publicacion,
            definitivo_dof_oficio,  definitivo_dof_publicacion,
            sentencia_sat_oficio,   sentencia_sat_publicacion,
            sentencia_dof_oficio,   sentencia_dof_publicacion,
            source_hash
        )
        SELECT
            source_row_number, rfc, rfc_normalized, name, name_normalized, name_core,
            situacion, is_cleared, is_redacted,
            presuncion_sat_oficio,  presuncion_sat_publicacion,
            presuncion_dof_oficio,  presuncion_dof_publicacion,
            desvirtuado_sat_oficio, desvirtuado_sat_publicacion,
            desvirtuado_dof_oficio, desvirtuado_dof_publicacion,
            definitivo_sat_oficio,  definitivo_sat_publicacion,
            definitivo_dof_oficio,  definitivo_dof_publicacion,
            sentencia_sat_oficio,   sentencia_sat_publicacion,
            sentencia_dof_oficio,   sentencia_dof_publicacion,
            source_hash
        FROM deduplicated
        ON CONFLICT ON CONSTRAINT sat_blacklist_record_source_hash_key DO UPDATE
        SET source_row_number = EXCLUDED.source_row_number
        -- Only counts as an update when the listing actually moved the row;
        -- an unchanged re-import leaves updated_at alone.
        WHERE target.source_row_number IS DISTINCT FROM EXCLUDED.source_row_number
        RETURNING (xmax = 0) AS was_inserted
    )
    SELECT
        count(*) FILTER (WHERE was_inserted),
        count(*) FILTER (WHERE NOT was_inserted),
        staged_total - staged_distinct
    FROM merged;
END;
$$;
