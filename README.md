# infosys-backend

Backend de infosys. FastAPI + PostgreSQL.

Currently implements the **SAT blacklist check**: an endpoint that tells you
whether one or many Mexican taxpayers appear in the SAT *Artículo 69-B del CFF*
listing, searching by RFC, by company name, or both.

It also contains the foundation for the **synthetic estate generator** used by
the Forensic Auditor project. The generator is intentionally a separate,
offline Python package: it will export challenge-compatible SQLite estates and
must not require the API, PostgreSQL, a live SAT lookup, or network access.

See [app/estate_generator/README.md](app/estate_generator/README.md) for its
module boundaries and [evaluation/estate_generator/README.md](evaluation/estate_generator/README.md)
for the separation between public estates and private evaluation material.

Generate a public normal-business estate with:

```bash
uv run estate-generate --seed 7 --output generated/estate_7.db
```

Generate a private training/evaluation fixture, including the five synthetic
scheme families and paired decoys, with:

```bash
uv run python -m evaluation.estate_generator.cli \
  --seed 7 --output generated/fixture_7.db --all-five --decoy-count 5
```

Only the SQLite file is public. Keep `evaluation/` and the generated
`private/*.ground_truth.json` and `private/*.provenance.json` sidecars out of
the investigator deployment.

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

## The endpoint

### `POST /api/v1/sat/blacklist/check`

Checks up to `BLACKLIST_MAX_COMPANIES_PER_REQUEST` companies (default 500) in a
single request, resolved with **one** database query.

**Request** — each entry needs `rfc`, `name`, or both:

```json
{
  "companies": [
    { "rfc": "AAA080808HL8" },
    { "name": "INGENIOS SANTOS, S.A. DE C.V." },
    { "rfc": "CACL7806172Y1", "name": "CARMONA CÁRDENAS LINO" }
  ]
}
```

**Response** — one result per requested company, in request order:

```json
{
  "results": [
    {
      "query": { "rfc": "AAA080808HL8", "name": null },
      "blacklisted": true,
      "match_type": "rfc",
      "similarity": null,
      "effective_situacion": "Sentencia Favorable",
      "cleared": true,
      "match": {
        "id": 1,
        "rfc": "AAA080808HL8",
        "name": "ASESORES EN AVALÚOS Y ACTIVOS, S.A. DE C.V.",
        "situacion": "Sentencia Favorable",
        "is_cleared": true,
        "presuncion_sat_oficio": "500-05-2018-16632 de fecha 01 de junio de 2018",
        "presuncion_sat_publicacion": "2018-06-01",
        "...": "all eight oficio/publication pairs are preserved"
      },
      "matches": ["..."],
      "match_count": 1
    }
  ]
}
```

### Reading the response

| Field | Meaning |
| --- | --- |
| `blacklisted` | The taxpayer appears in the listing **at all**. |
| `effective_situacion` | Most severe status across all matches: `Definitivo` > `Presunto` > `Desvirtuado` > `Sentencia Favorable`. |
| `cleared` | Every match is `Desvirtuado` or `Sentencia Favorable` — the taxpayer rebutted the presumption. |
| `match` | The most severe matching record. |
| `matches` | **All** matching records (capped at 20). |
| `match_type` | Which strategy matched: `rfc`, `rfc_and_name`, `name_exact`, `name_fuzzy`. |
| `similarity` | Trigram score, only for `name_fuzzy`. |

> **`blacklisted: true` is not the same as "guilty".** A taxpayer with
> `Sentencia Favorable` or `Desvirtuado` is published in the listing but has
> cleared the presumption. Use `effective_situacion` / `cleared` to tell an open
> procedure from a resolved one.

> **One RFC can hold several procedures.** In the reference dataset 78 RFCs
> occupy 322 rows — the same taxpayer can be `Presunto` in one case and
> `Definitivo` in another. `match` gives the most severe; `matches` gives all.

### Errors

Every failure uses one envelope:

```json
{ "error": { "code": "validation_error", "message": "...", "details": [] } }
```

| Status | `code` | Cause |
| --- | --- | --- |
| 422 | `validation_error` | Empty `companies`, entry with neither RFC nor name, malformed RFC, unknown field, batch over the limit. |
| 503 | `database_unavailable` | The database could not be reached or the query failed. |
| 500 | `internal_error` | Anything unexpected. |

---

## Search strategy

The task allowed several approaches; this is what was chosen and why.

Normalization happens **in Python**, in `app/sat/normalization.py`, and the
normalized forms are stored as their own columns. Both the importer and the API
call the same functions, so a query is a plain equality test against an indexed
column. Normalizing in SQL instead (`unaccent(upper(name))`) would wrap the
column in a function call and force either an expression index or a sequential
scan.

Three stages run in one query, each only considering inputs the previous stage
left unresolved:

| Stage | `match_type` | Column | Index |
| --- | --- | --- | --- |
| 1 | `rfc` / `rfc_and_name` | `rfc_normalized` | B-tree |
| 2 | `name_exact` | `name_normalized`, `name_core` | B-tree |
| 3 | `name_fuzzy` | `name_core` | GIN trigram (`pg_trgm`) |

* **RFC** — uppercased with separators stripped, so `aaa-080808-hl8` finds
  `AAA080808HL8`. Exact match only; an RFC is an identifier, not prose.
* **Name** — accent-folded, uppercased, punctuation-stripped,
  whitespace-collapsed. `name_core` additionally drops trailing corporate
  suffixes, so `INGENIOS SANTOS` finds `INGENIOS SANTOS, S.A. DE C.V.`. Periods
  are deleted rather than spaced so `S.A.` becomes `SA`, not `S A`.
* **Fuzzy** — `pg_trgm` similarity against `name_core`, using the `%` operator
  so the GIN index serves it. The threshold
  (`BLACKLIST_NAME_SIMILARITY_THRESHOLD`, default `0.45`) is pinned per
  connection at pool setup, keeping the search to one round trip.

**Why trigram over full-text search:** company names are short proper nouns, not
prose. FTS stems and tokenizes for natural language and would not help with the
real failure mode here — typos and truncations (`INGENIOS SANTO`). Trigram
similarity handles those directly. Exact matching still runs first, so the
cheaper B-tree path serves the common case and trigram only picks up the
remainder.

### Performance

No stage ever scans the table. The four search indexes are **partial**
(`WHERE NOT is_redacted`), so the suppressed rows are not even in them. Batches
are passed as arrays and expanded with `unnest`, so N companies cost one query —
never N. Duplicate companies within a request are collapsed before the query and
expanded afterwards.

Measured on the 14,729-row dataset (local Docker Postgres 17, median of 7):

| Request | Latency |
| --- | --- |
| 1 RFC | 3.1 ms |
| 100 RFCs | 4.7 ms |
| 500 RFCs (max batch) | 14.9 ms |
| 500 exact names | 18.8 ms |
| 100 fuzzy names | 50.9 ms |

Fuzzy is the expensive path (~0.5 ms per input) because it sorts trigram
candidates; it only runs for inputs that matched nothing exactly.

`tests/test_search_performance.py` asserts on `EXPLAIN ANALYZE` output that each
index is used and that no `Seq Scan` appears, so a future change to the query
cannot silently regress into a table scan.

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
* **Normalization** — applied at import with the same functions the search uses.
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
  listing, but excluded from every index and every search, so querying the
  placeholder can never produce a false positive.

To refresh the dataset later, drop a new snapshot in place and re-run the
importer. Nothing in the endpoint changes.

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
├── main.py               # app factory, lifespan, pool wiring
├── api/
│   ├── router.py         # /api/v1
│   └── v1/sat.py         # the endpoint
├── core/
│   ├── config.py         # settings
│   ├── database.py       # asyncpg pool
│   └── errors.py         # error envelope + handlers
└── sat/
    ├── normalization.py  # shared by importer and search
    ├── importer.py       # CSV -> staging -> merge
    ├── repository.py     # the single bulk query
    ├── service.py        # batching, dedup, result assembly
    └── schemas.py        # request/response models
```
