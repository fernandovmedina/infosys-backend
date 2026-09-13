-- =============================================================================
-- infosys-backend — schema migrations
-- =============================================================================
-- PURPOSE
--
-- database/database.sql describes the schema as it was first designed and is
-- treated as immutable history. Every schema change made *after* that initial
-- design lands here instead, appended in chronological order.
--
-- Keeping the two apart means a database created before a change and one
-- created today converge on the same structure: database/exec.sql runs
-- database.sql first and then this file. Editing database.sql in place would
-- silently skip the change on databases that already exist.
--
-- RULES
--
--   1. Append only. Never edit or delete a migration that has already shipped;
--      correct it with a new one at the end of the file.
--   2. Never duplicate anything from database.sql here.
--   3. Every statement must be idempotent (IF EXISTS / IF NOT EXISTS, or
--      CREATE OR REPLACE) so the file can be replayed safely.
--   4. Head each migration with the date and a one-line reason.
--   5. Guard destructive changes (DROP COLUMN, type narrowing) with an explicit
--      note about the deploy ordering they require.
--
-- FORMAT
--
--   -- 2026-10-01 — Track the SAT publication each snapshot came from.
--   ALTER TABLE sat_blacklist_record
--       ADD COLUMN IF NOT EXISTS snapshot_published_on date;
--
-- LIKELY NEAR-TERM MIGRATIONS
--
--   * A `sat_blacklist_snapshot` table, once the dataset is refreshed
--     automatically, to record when each import ran and which file it read.
--   * A partial index on `situacion` if status filtering becomes a hot path;
--     it is not indexed today because the current endpoint never filters on it.
--
-- =============================================================================

-- 2026-09-12 — Basic email/password auth: accounts, email verification codes,
-- and session tokens for the frontend's login/register flow.

-- ---- app_user ---------------------------------------------------------------
-- One row per account. `email_normalized` (trimmed, lowercased) is the unique
-- key and the column every lookup filters on; `email` keeps the address as the
-- user typed it, for display and for sending mail.
CREATE TABLE IF NOT EXISTS app_user (
    id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    name                text        NOT NULL,
    email               text        NOT NULL,
    email_normalized    text        NOT NULL,
    password_hash       text        NOT NULL,

    -- False until the first email_verification_code for this user is confirmed.
    -- Login is refused while this is false.
    is_email_verified   boolean     NOT NULL DEFAULT false,

    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT app_user_email_normalized_key UNIQUE (email_normalized),
    CONSTRAINT app_user_name_not_blank  CHECK (length(btrim(name)) > 0),
    CONSTRAINT app_user_email_not_blank CHECK (length(btrim(email_normalized)) > 0)
);

COMMENT ON TABLE app_user IS
    'Accounts for the basic email/password auth flow.';

CREATE OR REPLACE FUNCTION app_user_touch_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS app_user_touch_updated_at ON app_user;
CREATE TRIGGER app_user_touch_updated_at
    BEFORE UPDATE ON app_user
    FOR EACH ROW
    EXECUTE FUNCTION app_user_touch_updated_at();


-- ---- email_verification_code -------------------------------------------------
-- One row per code sent. Codes are 6 digits, stored only as a SHA-256 hash
-- (they are short-lived and attempt-limited, so a slow KDF buys nothing), and
-- expire after Settings.auth_verification_code_ttl_minutes. `attempts` caps
-- brute-forcing the 10^6 code space; the service voids a code once it is
-- reached (Settings.auth_verification_code_max_attempts).
CREATE TABLE IF NOT EXISTS email_verification_code (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id       bigint      NOT NULL REFERENCES app_user (id) ON DELETE CASCADE,

    code_hash     text        NOT NULL,
    attempts      integer     NOT NULL DEFAULT 0,
    expires_at    timestamptz NOT NULL,
    consumed_at   timestamptz,

    created_at    timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE email_verification_code IS
    'Email verification codes for app_user. Latest row per user_id is authoritative.';

-- The service only ever asks for "the latest code for this user".
CREATE INDEX IF NOT EXISTS email_verification_code_user_id_created_at_idx
    ON email_verification_code (user_id, created_at DESC);


-- ---- auth_session -------------------------------------------------------------
-- One row per issued session cookie. The cookie carries an opaque token;
-- only its SHA-256 hash is stored, so a table leak does not hand out live
-- sessions. A session is valid while revoked_at IS NULL AND expires_at > now().
CREATE TABLE IF NOT EXISTS auth_session (
    id            bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id       bigint      NOT NULL REFERENCES app_user (id) ON DELETE CASCADE,

    token_hash    text        NOT NULL,
    expires_at    timestamptz NOT NULL,
    revoked_at    timestamptz,

    created_at    timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT auth_session_token_hash_key UNIQUE (token_hash)
);

COMMENT ON TABLE auth_session IS
    'Session tokens issued on login/verify. token_hash is looked up on every request.';

CREATE INDEX IF NOT EXISTS auth_session_user_id_idx ON auth_session (user_id);


-- 2026-09-13 — Drop email verification: registration now logs the account in
-- directly, so the code table and the verified flag on app_user are dead.
DROP TABLE IF EXISTS email_verification_code;

ALTER TABLE app_user DROP COLUMN IF EXISTS is_email_verified;

COMMENT ON TABLE auth_session IS
    'Session tokens issued on login/register. token_hash is looked up on every request.';


-- 2026-09-13 — Investigation runs: one row per uploaded dataset (a .zip or a
-- set of CSVs). The normalized tables live on disk under Settings.runs_storage_dir;
-- this row holds ownership, lifecycle and the validation diagnostics.
CREATE TABLE IF NOT EXISTS investigation_run (
    id            text        PRIMARY KEY,
    user_id       bigint      NOT NULL REFERENCES app_user (id) ON DELETE CASCADE,

    status        text        NOT NULL,
    filename      text        NOT NULL,
    format        text        NOT NULL,
    sha256        text        NOT NULL,
    -- ValidationResult minus run_id/status: tables, column_warnings, ignored_files.
    validation    jsonb       NOT NULL,
    -- ApiErrorBody when status = 'failed'.
    error         jsonb,

    created_at    timestamptz NOT NULL DEFAULT now(),
    started_at    timestamptz,
    finished_at   timestamptz,

    CONSTRAINT investigation_run_status_check
        CHECK (status IN ('validating', 'ready', 'running', 'completed', 'failed')),
    CONSTRAINT investigation_run_format_check CHECK (format IN ('zip', 'csv'))
);

COMMENT ON TABLE investigation_run IS
    'Investigation runs. Dataset tables are stored on disk, keyed by id.';

-- The history page lists a user's runs newest first.
CREATE INDEX IF NOT EXISTS investigation_run_user_id_created_at_idx
    ON investigation_run (user_id, created_at DESC);


-- 2026-09-13 — Fraud-detection engine results (TASK #3). The engine runs over a
-- run's stored dataset in an in-memory DuckDB; PostgreSQL keeps what it
-- concluded, one row per completed run. The rule catalog is not stored: it is
-- static code (app/fraud/engine/catalogo.py) and served by GET /fraud/rules.
CREATE TABLE IF NOT EXISTS fraud_analysis (
    run_id            text             PRIMARY KEY
                                       REFERENCES investigation_run (id) ON DELETE CASCADE,
    engine_version    text             NOT NULL,
    seed              integer          NOT NULL,

    rules_evaluated   integer          NOT NULL,
    rules_triggered   integer          NOT NULL,
    findings_count    integer          NOT NULL,
    total_exposure    double precision NOT NULL,

    -- The official submission_schema.json document, as validated.
    submission        jsonb            NOT NULL,
    signals_per_rule  jsonb            NOT NULL,
    data_quality      jsonb            NOT NULL,
    -- [{rule, status, error}] for detectors skipped because they failed.
    rule_failures     jsonb            NOT NULL,
    warnings          jsonb            NOT NULL,
    rows_per_table    jsonb            NOT NULL,
    case_file_html    text             NOT NULL,

    created_at        timestamptz      NOT NULL DEFAULT now()
);

COMMENT ON TABLE fraud_analysis IS
    'Fraud-engine result of a completed investigation run (submission + case file).';

-- Every row a detector returned, kept so each finding and lead can be audited
-- back to the exact source record. `ordinal` preserves the engine's output order.
CREATE TABLE IF NOT EXISTS fraud_signal (
    run_id            text             NOT NULL
                                       REFERENCES fraud_analysis (run_id) ON DELETE CASCADE,
    ordinal           integer          NOT NULL,

    rule_id           text             NOT NULL,
    scheme_type       text,
    evidence_family   text,
    source_table      text             NOT NULL,
    entity_id         text,
    evidence_id       text,
    detected_on       text,
    severity          text             NOT NULL,
    self_sufficiency  text             NOT NULL,
    amount            double precision,
    context           jsonb,

    PRIMARY KEY (run_id, ordinal),
    CONSTRAINT fraud_signal_severity_check CHECK (severity IN ('alta', 'media', 'baja')),
    CONSTRAINT fraud_signal_self_sufficiency_check
        CHECK (self_sufficiency IN ('autosuficiente', 'presuntiva'))
);

COMMENT ON TABLE fraud_signal IS
    'Detector output (signals) behind a fraud_analysis, one row per cited source record.';

-- Drill-down: signals of one rule, or about one entity, within a run.
CREATE INDEX IF NOT EXISTS fraud_signal_run_id_rule_id_idx ON fraud_signal (run_id, rule_id);
CREATE INDEX IF NOT EXISTS fraud_signal_run_id_entity_id_idx ON fraud_signal (run_id, entity_id);


-- 2026-09-13 — Investigation log (TASK #4). Every step of a run -- dataset load,
-- each detector's result, findings, declined leads, validation, the outcome --
-- is one ordered event. The frontend replays it as the live progress feed
-- (SSE, resumable by `seq`), the full log and the "why?" search. A retry
-- clears the previous attempt's events, so `seq` restarts at 1.
CREATE TABLE IF NOT EXISTS run_event (
    run_id   text        NOT NULL REFERENCES investigation_run (id) ON DELETE CASCADE,
    seq      integer     NOT NULL,
    ts       timestamptz NOT NULL DEFAULT now(),
    type     text        NOT NULL,
    role     text        NOT NULL,
    -- The rest of the event (message, detail, result, entities, counters, error...).
    payload  jsonb       NOT NULL,

    PRIMARY KEY (run_id, seq),
    CONSTRAINT run_event_type_check CHECK (type IN (
        'step', 'detector_result', 'finding_draft', 'challenge', 'validation',
        'lead_closed', 'warning', 'completed', 'failed'
    )),
    CONSTRAINT run_event_role_check CHECK (role IN (
        'system', 'detector', 'investigator', 'challenger', 'validator'
    ))
);

COMMENT ON TABLE run_event IS
    'Ordered investigation log of a run: live progress (SSE), full log and search.';

-- 2026-09-13 — The audited company of a completed run (TASK #4), identified the
-- way the engine does it, so the run history can name it without reloading the
-- dataset.
ALTER TABLE investigation_run ADD COLUMN IF NOT EXISTS company_rfc text;
ALTER TABLE investigation_run ADD COLUMN IF NOT EXISTS company_name text;
