# infosys-backend

Backend de infosys. FastAPI + PostgreSQL.

It implements a basic **email/password auth flow** (register, login, session
cookie) for the frontend — see [Auth](#auth) — and keeps a normalized copy of the
SAT *Artículo 69-B del CFF* listing in PostgreSQL, loaded by the
`sat-blacklist-import` importer (see [Importing the dataset](#importing-the-dataset)).
The HTTP endpoint that searched it was removed because nothing used it.

It also contains the foundation for the **synthetic estate generator** used by
the Forensic Auditor project. The generator is intentionally a separate,
offline Python package: it will export challenge-compatible CSV estates (or
SQLite on request) and
must not require the API, PostgreSQL, a live SAT lookup, or network access.

It also runs the **fraud-detection engine** (ported from `motor-agente-forense`):
24 deterministic SQL detectors over a company's estate, an assembler that turns
their signals into findings or declined leads, the official format validator,
and an HTML case file. See [Fraud detection](#fraud-detection).

See [app/estate_generator/README.md](app/estate_generator/README.md) for its
module boundaries and [evaluation/estate_generator/README.md](evaluation/estate_generator/README.md)
for the separation between public estates and private evaluation material.
Current challenge readiness, evaluation commands, and explicitly deferred work
are documented in [docs/challenge_readiness.md](docs/challenge_readiness.md).

For the complete generator workflow, see the
[Synthetic estate generator guide](docs/synthetic_estate_generator_guide.md).

Generate a public normal-business estate with:

```bash
uv run estate-generate --seed 7
```

Generate a private training/evaluation fixture, including the five synthetic
scheme families and paired decoys, with:

```bash
uv run python -m evaluation.estate_generator.cli \
  --seed 7 --all-five --decoy-count 5
```

Both commands create timestamped folders under `app/estate_generator/output/`.
CSV tables are the default; pass `--sqlite` to write only `estate.db`. Keep
`evaluation/` and generated private ground-truth/provenance sidecars out of the
investigator deployment.

Replay a CSV estate locally, without the API, database, authentication, or network:

```bash
uv run fraud-replay --input-dir <csv-directory> --seed 7 --output-dir <new-artifact-directory>
```

The output directory is created once and contains `submission.json`,
`case-file.html`, and `audit-log.json` with input and deterministic-result checksums.

---

## Getting started

Requires Python 3.14, [uv](https://docs.astral.sh/uv/), and Docker.

```bash
uv sync --all-groups          # install dependencies
cp .env.example .env          # configuration
docker compose up -d          # PostgreSQL 17 on localhost:5433
```

Create the schema and seed the blacklist:

```bash
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f database/exec.sql
```

`exec.sql` applies the schema, applies any migrations, shells out to the
importer, refreshes planner statistics and prints a summary. If `psql` is not
installed locally, do the same two steps by hand:

```bash
docker compose exec -T postgres psql -U infosys -d infosys < database/database.sql
docker compose exec -T postgres psql -U infosys -d infosys < database/alter.sql
uv run sat-blacklist-import
```

Run the API:

```bash
uv run uvicorn app.main:app --reload    # docs at http://127.0.0.1:8000/docs
```

---

## Project structure

The online API and offline estate generator share the repository but keep
their dependencies separate:

| Path | Responsibility |
| --- | --- |
| `app/api/` | FastAPI routes, request dependencies, and HTTP response handling. |
| `app/auth/` | Authentication entities, business rules, security, and persistence. |
| `app/sat/` | SAT listing normalization and CSV importing. |
| `app/runs/` | Dataset upload, diagnostics, and investigation-run lifecycle. |
| `app/fraud/` | Fraud-detection engine (`engine/`, `rules/`), its service, and persistence. |
| `app/core/` | Runtime configuration and database lifecycle. |
| `app/estate_generator/` | Public, deterministic, offline estate generation. |
| `evaluation/` | Private scenario generation and evaluation harnesses. |
| `database/` | PostgreSQL schema and migrations. |
| `tests/` | Unit, contract, and optional PostgreSQL integration tests. |

Route modules translate HTTP input and output; services own business behavior;
repositories are the only feature modules that issue database queries. This
keeps transport models and raw database records out of the service layer.

---

## Auth

A basic email/password flow for the frontend: register, sign in, and a
session cookie for everything after that. Postgres is the store for all of
this (`app_user`, `auth_session`); DuckDB is unrelated to auth — it's there
for the fraud-detection side of the project.

There is no email verification: registering logs the account in immediately,
the same way signing in does.

| Endpoint | What it does |
| --- | --- |
| `POST /api/v1/auth/register` | Create an account (`name`, `email`, `password`) and start a session right away. |
| `POST /api/v1/auth/login` | `{email, password}`. |
| `POST /api/v1/auth/logout` | Revoke the current session. |
| `GET /api/v1/auth/me` | The signed-in user, or `not_authenticated`. |

The session is an httpOnly, `SameSite=Lax` cookie (`infosys_session` by
default); only its SHA-256 hash is stored server-side. Passwords are hashed
with PBKDF2-HMAC-SHA256 (stdlib `hashlib`, 600k iterations) — no new
dependency for that.

Because the frontend and API run on different ports in development, the API
sends CORS headers (`CORS_ALLOWED_ORIGINS`, credentials allowed) so the
browser will both send and store the session cookie across `localhost:3000` →
`localhost:8000` calls.

---

## Fraud detection

Full reference: [docs/fraud_engine.md](docs/fraud_engine.md) (architecture, rule
table, request/response schemas, how to add a rule, behavior vs. the reference).

| Endpoint | What it does |
| --- | --- |
| `POST /api/v1/fraud/analyze` | Multipart, one CSV per estate table (`vendors`, `invoices`, `ledger`, `bank_txns`, `purchase_orders`, `contracts`, `employees`, `efos_list`) + optional `seed`. Runs the engine synchronously and returns the validated `submission`, every detector `signal` with its evidence, data-quality counts, rule failures and the `case_file_html`. Session required; nothing is stored. |
| `POST /api/v1/runs/{run_id}/start` | Audits an uploaded run's dataset in the background (`202`, status `running` → `completed` / `failed`). Optional body `{"seed": n}`. |
| `GET /api/v1/runs/{run_id}/result` | The stored analysis of a `completed` run. |
| `GET /api/v1/fraud/rules` | Rule catalog: scheme, evidence family, implemented, description. |
| `GET /api/v1/fraud/health` | Engine status and rules loaded. |

The engine loads the tables into an in-memory DuckDB, runs every rule (a failing
rule is reported and skipped, the rest continue), clusters signals per scheme and
accuses only with two independent evidence families or a rule sufficient on its
own; everything else is a declined lead with a reason. Results are persisted in
`fraud_analysis` and `fraud_signal` (`database/alter.sql`). Limits:
`FRAUD_MAX_BYTES_PER_FILE`, `FRAUD_MAX_ROWS_PER_TABLE`.

---

## Importing the dataset

```bash
uv run sat-blacklist-import                   # default: ./black_list.csv
uv run sat-blacklist-import --csv other.csv   # a newer snapshot
uv run sat-blacklist-import --dry-run         # parse and report, write nothing
```

```
SAT blacklist import report
--------------------------------------
  rows parsed          :  14761
  inserted             :  14729
  updated              :      0
  unchanged (skipped)  :      0
  duplicates collapsed :     32
  redacted (unsearch.) :    238
  failed rows          :      0
```

How it handles the source file:

* **Encoding** — the published CSV is **cp1252**, not UTF-8.
* **Preamble** — two lines of legal notice precede the header. The header is
  found by looking for the `RFC` column, not by a hard-coded line number.
* **Normalization** — RFCs and names are stored in normalized columns (`app/sat/normalization.py`): RFC uppercased without separators; names accent-folded, uppercased, punctuation-stripped, and `name_core` without corporate suffixes.
* **Duplicates** — `source_hash` (SHA-256 of the row minus its sequence number,
  which SAT renumbers each publication) is the conflict key. Re-running an
  unchanged import inserts 0. The 32 exact duplicates in the source collapse to
  one row each.
* **Bulk loading** — rows are `COPY`d into an unlogged staging table and merged
  by `sat_blacklist_merge_staging()` in one set-based statement. Never one
  INSERT per row. A full import takes ~1.3 s.
* **Malformed rows** — a bad row is counted and reported with its line number
  and reason; the run continues. Blank trailing lines are ignored.
* **Redacted rows** — 238 rows carry `RFC = XXXXXXXXXXXX` and the name
  *"Información suprimida en cumplimiento a la declaratoria..."*. They are
  stored with `is_redacted = true` so the table reconciles with the published
  listing, but excluded from the (partial) indexes.

To refresh the dataset later, drop a new snapshot in place and re-run the
importer.

---

## Database

```
database/
├── database.sql   # complete schema: table, indexes, staging, merge function
├── exec.sql       # initialize + seed a database from scratch (idempotent)
└── alter.sql      # future migrations, appended in order
```

`database.sql` is treated as immutable history; every later schema change goes
into `alter.sql` so that existing and freshly created databases converge.
`exec.sql` runs both, in that order.

The table is `sat_blacklist_record` — **one row per published procedure, not per
taxpayer**. RFC is deliberately *not* unique; `source_hash` is the idempotency
key. `situacion` is free text rather than an ENUM or CHECK constraint so that an
automated refresh does not fail wholesale if SAT introduces a new status value;
unknown statuses fail safe by counting as *not* cleared.

`alter.sql` also carries the auth schema (`app_user`, `auth_session`), investigation
runs (`investigation_run`) and fraud-engine results (`fraud_analysis`, `fraud_signal`).

---

## Development

```bash
uv run ruff format .          # formatter
uv run ruff check .           # linter
uv run mypy app main.py tests # type checker
uv run pytest                 # tests
```

Tests that need the database are skipped, not failed, when none is reachable, so
the pure-Python suite still runs without Docker.

---

## Layout

```
app/
├── main.py               # app factory, lifespan, pool wiring, CORS
├── api/
│   ├── router.py         # /api/v1
│   └── v1/
│       ├── auth.py       # register/login/verify/logout/me
│       ├── runs.py       # dataset upload + investigation runs
│       └── fraud.py      # fraud engine: analyze, rules, health
├── core/
│   ├── config.py         # settings
│   ├── database.py       # asyncpg pool
│   ├── session.py        # session-cookie dependency
│   └── errors.py         # error envelope + handlers
├── auth/
│   ├── security.py       # password hashing, codes, session tokens
│   ├── repository.py     # app_user / auth_session queries
│   ├── service.py        # register/login/verify/session business logic
│   └── schemas.py        # request/response models
├── runs/                 # upload ingest, diagnostics, run lifecycle
├── fraud/                # fraud engine (see docs/fraud_engine.md)
└── sat/
    ├── normalization.py  # RFC / name normalization used by the importer
    └── importer.py       # CSV -> staging -> merge
```
