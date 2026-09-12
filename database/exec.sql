-- =============================================================================
-- infosys-backend — initialize and seed the database
-- =============================================================================
-- Brings an empty database to the state the project needs in order to start:
-- schema + the SAT blacklist dataset loaded from black_list.csv.
--
-- Run from the repository root with:
--
--     psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f database/exec.sql
--
-- Safe to run repeatedly: the schema is created with IF NOT EXISTS and the
-- seeding step upserts on `source_hash`, so a second run inserts nothing.
-- =============================================================================

\set ON_ERROR_STOP on
\timing on

-- -----------------------------------------------------------------------------
-- 1. Schema
-- -----------------------------------------------------------------------------
\echo '==> Applying schema (database/database.sql)'
\i database/database.sql

-- -----------------------------------------------------------------------------
-- 2. Migrations applied on top of the base schema
-- -----------------------------------------------------------------------------
\echo '==> Applying migrations (database/alter.sql)'
\i database/alter.sql

-- -----------------------------------------------------------------------------
-- 3. Seed data
-- -----------------------------------------------------------------------------
-- The ~15,000 blacklist records are deliberately NOT inlined here. They are
-- loaded by the reusable importer, which parses black_list.csv (cp1252), applies
-- the same normalization the search uses, COPYs the result into
-- sat_blacklist_staging and calls sat_blacklist_merge_staging().
--
-- Run it separately:
--
--     uv run sat-blacklist-import                  # default: ./black_list.csv
--     uv run sat-blacklist-import --csv path.csv   # any other snapshot
--     uv run sat-blacklist-import --dry-run        # parse + report, write nothing
--
-- `\!` shells out, so it only works when psql runs on the same machine as the
-- project checkout. Comment it out and run the importer by hand otherwise.
\echo '==> Seeding SAT blacklist from black_list.csv'
\! uv run sat-blacklist-import

-- -----------------------------------------------------------------------------
-- 4. Seeding guard
-- -----------------------------------------------------------------------------
-- `\!` reports a failing shell command but does NOT abort the script, even
-- under ON_ERROR_STOP. Without this check a failed seeding step (no `uv` on
-- PATH, unreadable CSV, ...) would leave an empty table and still print
-- "Done." -- so fail loudly instead.
DO $$
BEGIN
    IF (SELECT count(*) FROM sat_blacklist_record) = 0 THEN
        RAISE EXCEPTION
            'Seeding produced no rows. Run the importer manually from the '
            'project root: uv run sat-blacklist-import';
    END IF;
END;
$$;

-- -----------------------------------------------------------------------------
-- 5. Planner statistics
-- -----------------------------------------------------------------------------
-- Without this the planner has no statistics for a freshly loaded table and may
-- choose a sequential scan over the RFC/name indexes.
\echo '==> Refreshing planner statistics'
ANALYZE sat_blacklist_record;

-- -----------------------------------------------------------------------------
-- 6. Verification
-- -----------------------------------------------------------------------------
\echo '==> Loaded dataset summary'
SELECT
    count(*)                                        AS total_records,
    count(*) FILTER (WHERE NOT is_redacted)         AS searchable_records,
    count(*) FILTER (WHERE is_redacted)             AS redacted_records,
    count(DISTINCT rfc_normalized)
        FILTER (WHERE NOT is_redacted)              AS distinct_rfcs,
    count(*) FILTER (WHERE is_cleared)              AS cleared_records
FROM sat_blacklist_record;

SELECT situacion, count(*) AS records
FROM sat_blacklist_record
GROUP BY situacion
ORDER BY records DESC;

\echo '==> Done.'
