# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Worker panes: delegate to save tokens

**Two worker agents (Codex and/or Claude) run in other cmux/tmux panes and are available to take tasks.** Delegate to them so this session spends fewer tokens and less of its usage limit. Act as the orchestrator: plan, split the work, hand off, then check the results.

`scripts/detect.sh` is the only interface to the workers. It auto-detects cmux (preferred) or tmux; set `MUX=tmux` or `MUX=cmux` to force one.

```bash
scripts/detect.sh status                 # multiplexer, my pane, every pane + the agent running in it
scripts/detect.sh workers                # just the codex/claude panes that aren't me  -> "<target>\t<agent>"
scripts/detect.sh send  <target> "<task>"  # type the prompt and press Enter
scripts/detect.sh wait  <target> [timeout] [idle]   # block until the pane stops changing
scripts/detect.sh read  <target> [lines]            # tail of the pane (scrollback included)
scripts/detect.sh ask   <target> "<task>" [timeout] # send + wait + read in one call
scripts/detect.sh key   <target> escape|ctrl+c|enter
```

Targets are `surface:N` in cmux or `session:window.pane` in tmux. **Pane refs change between sessions, so run `workers` at the start instead of hardcoding them.**

How to delegate:
- Good fits for workers: mechanical or bulk edits, writing focused tests, running and triaging `ruff`/`mypy`/`pytest`, generating fixtures, and reading large files (CSVs, `CONTEXT.md`, `p.md`, `TODO.md`) to report a summary. Keep architecture decisions, cross-module changes and final verification in this session.
- Make each prompt self-contained: goal, exact files the worker owns, constraints from this file, and the expected report (e.g. "reply with a short summary of changed files and test results"). Workers don't share this conversation's context.
- Give each worker a separate set of files so their edits don't collide. Run both in parallel when the tasks are independent.
- Read only the tail of a pane (`read <target> 40`), not the full scrollback, and check the resulting diff with `git diff` rather than trusting the pane output.
- If `workers` returns nothing, fall back to doing the work here and tell the user.

## Commands

Requires Python 3.14, `uv`, and Docker.

```bash
uv sync --all-groups
cp .env.example .env
docker compose up -d                                        # Postgres 17 on localhost:5433
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f database/exec.sql # schema + migrations + blacklist import (idempotent)
uv run uvicorn app.main:app --reload                        # http://127.0.0.1:8000/docs

uv run ruff format .
uv run ruff check .
uv run mypy app main.py tests                               # strict mode
uv run pytest
uv run pytest tests/test_normalization.py::test_normalize_rfc -q  # single test
uv run pytest tests/test_estate_generator                   # generator suite, no DB needed

uv run sat-blacklist-import [--csv file.csv] [--dry-run]
uv run estate-generate --seed 7 [--sqlite]                  # public estate
uv run python -m evaluation.estate_generator.cli --seed 7 --all-five --decoy-count 5   # private fixture + answer keys
./evaluation/estate_generator/generate.sh                   # full fixture matrix
uv run pytest tests/test_fraud                              # fraud engine (golden seed 1301 + API)
```

DB-backed tests use `requires_database` from `tests/conftest.py`. They are **skipped, not failed**, when no seeded Postgres is reachable, so a green run without Docker doesn't cover the auth, runs or fraud endpoints. The probe checks that `sat_blacklist_record` is seeded.

## Architecture

The repo holds two independent halves: an online FastAPI + asyncpg API and an offline synthetic-estate generator for the Forensic Auditor challenge.

### API (`app/`)

- `app/main.py` is the app factory. The lifespan opens one asyncpg pool on `app.state.pool`. `app/api/dependencies.py` exposes it as `PoolDependency`, alongside `SettingsDependency` and `SessionTokenDependency`.
- There are three layers per feature (`auth`, `runs`, `fraud`). Routes in `app/api/v1/` only translate HTTP. `service.py` owns the business logic. `repository.py` is the **only** place that issues SQL. Transport schemas and raw records don't leak into services.
- All errors go through `app/core/errors.py` and use one envelope: `{"error": {"code", "message", "details"}}`. Raise the typed errors defined there rather than `HTTPException`.
- Settings come from `app/core/config.py` (pydantic-settings, `.env`).
- **SAT listing** (`app/sat/`): only the importer and normalization remain (the `/sat/blacklist/check` endpoint was removed as unused). The importer reads cp1252 CSV, `COPY`s into staging, and merges on `source_hash` into `sat_blacklist_record`.
- **Auth**: Postgres tables `app_user`/`auth_session`. The session is an httpOnly cookie, and only its SHA-256 hash is stored. Passwords use stdlib PBKDF2.
- **Runs** (`app/runs/`): dataset upload → synchronous ingest/validation → tables written under `storage/runs` (gitignored) → `POST /runs/{id}/start` marks `running` and a FastAPI background task runs the fraud engine (`execute_run`) → `completed` (+ `fraud_analysis`/`fraud_signal` rows) or `failed` (retryable). Blocking diagnostics prevent start but not upload.

### Fraud engine (`app/fraud/`) — full doc: `docs/fraud_engine.md`

- Ported verbatim from the `motor-agente-forense` repo: `engine/` = its `src/agente/`, `rules/<scheme>/` = its numbered `src/rules/<n>_<bloque>/`. Identifiers, SQL, context columns and user-facing text stay in Spanish; treat them as a contract. **Never change thresholds, rule SQL, `catalogo.py` tables or assembler logic as a "cleanup"**: `tests/test_fraud/test_pipeline.py` asserts the seed 1301 submission is identical to the reference (`tests/fixtures/fraud/seed_1301.json`). Lint/mypy are relaxed for these two packages in `pyproject.toml` for that reason.
- Flow: estate CSVs → in-memory DuckDB (`engine/ingesta.cargar_csvs` strict for `/fraud/analyze`; `loader.load_run_tables` tolerant for runs) → `engine/pipeline.auditar_conexion` → `service.to_analysis` → `FraudAnalysis`. Rules are pure `rule_x(con) -> DataFrame` with the 8-column Signal contract; register new ones in the package `__init__.RULES` and in `engine/catalogo.py`.
- `engine/validate_format.py` must stay byte-identical to `public/material/validate_format.py` (tested). Nothing in `app/` may mention ground-truth files (tested with the judges' grep).

### Database (`database/`)

`database.sql` is immutable history. **Every schema change is appended to `alter.sql`.** `exec.sql` runs both, then imports the data.

### Estate generator (`app/estate_generator/`) and evaluation (`evaluation/`)

Read `app/estate_generator/AGENTS.md` before touching the generator. Its key invariants:
- It must not depend on FastAPI, Postgres, SAT lookups, or the network. **Nothing in `app/` may import `evaluation`.** Scheme labels, ground truth and provenance live only in `evaluation/estate_generator/` and in `private/*.ground_truth.json` / `*.provenance.json` sidecars, and must never be encoded in public record values, IDs or ordering.
- `public/material/estate_schema.sql` is the authoritative contract, read through `challenge_contract.py`. Don't keep a copy.
- Output must be deterministic for a given seed (seed-local RNG). Money is integer centavos or `Decimal`, never float, except when exporting SQLite `REAL`. One business event projects into all of its invoice/ledger/payment rows, and entries balance per event. Every estate includes normal activity.
- An EFOS/69-B match is context, never proof of fraud on its own.
- The five scheme families are phantom vendor, kickback, round-tripping, threshold splitting and revenue inflation. Each has an innocent decoy counterpart. Observation profiles are `challenge_wide` and `company_only`.
- Output goes to `app/estate_generator/output/<run>/` (CSV by default, `--sqlite` for `estate.db`). Generator tests must not require Postgres.

## Conventions

- Ruff (line length 100, py314 target) and mypy `--strict` (relaxed for `tests.*`). `asyncpg` is untyped.
- `CONTEXT.md`, `PROMPT.md`, `p.md` and `TODO.md` are large planning documents. Read them only when needed, or have a worker summarize them.
