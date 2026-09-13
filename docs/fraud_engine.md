# Fraud-detection engine

The engine investigates one company's data estate (the eight tables of
`public/material/estate_schema.sql`) and produces the challenge deliverables: a
`submission.json` that passes the official validator and a self-contained HTML
case file. It is deterministic, with no LLM and no network access.

It was ported from the `motor-agente-forense` repository (TASK #3). It is now
native code of this backend and does not need that repository at runtime.

---

## Architecture

```text
app/fraud/
├── engine/                 ported from motor-agente-forense src/agente/ (Spanish identifiers kept)
│   ├── esquema.py          DDL of the 8 estate tables (DuckDB)
│   ├── ingesta.py          strict CSV → DuckDB load; every schema error at once (IngestaInvalida)
│   ├── runner.py           runs RULES, checks the Signal contract, isolates failing rules
│   ├── estate.py           read-only estate queries, logged as tool_calls_made
│   ├── entidades.py        resolves entity_id (RFC, CLABE → owner, approver → employee)
│   ├── ensamblador.py      clusters signals per scheme, then decides: accuse or close as a lead
│   ├── evidencia.py        citations, exhibits, money trail, peso_amount
│   ├── submission.py       self-checks + submission JSON
│   ├── narrativa.py        templated narrative (≤150 words)
│   ├── case_file.py        HTML case file (5 sections, inline SVG)
│   ├── validacion.py       official validator gate (runs on a temporary SQLite copy)
│   ├── validate_format.py  unmodified copy of public/material/validate_format.py
│   ├── catalogo.py         static tables: rule → scheme, evidence family, legal basis, ...
│   └── pipeline.py         auditar_conexion(con, seed) → ResultadoAuditoria
├── rules/                  ported from src/rules/<n>_<bloque>/ (one SQL detector per file)
│   ├── phantom_vendor/     1_proveedores_fantasma_efos_edos
│   ├── kickback/           2_kickback
│   ├── round_tripping/     3_round_tripping
│   ├── threshold_splitting/4_threshold_splitting
│   ├── revenue_inflation/  5_revenue_inflation
│   ├── data_integrity/     6_integridad_datos_capa_1
│   └── __init__.py         RULES, in the reference order (folders 1 → 6)
├── loader.py               tolerant DuckDB load of a run's stored tables
├── service.py              analyze_files / analyze_run_tables / rule_catalog / engine_health
├── repository.py           fraud_analysis + fraud_signal persistence
└── schemas.py              API models (Submission = official submission_schema.json)
app/api/v1/fraud.py         /fraud routes
app/runs/service.py         start_run / execute_run / get_result
```

### Execution flow

```text
POST /fraud/analyze (8 CSV parts)            POST /runs/{id}/start (dataset uploaded earlier)
  → temp dir, per-file size limit              → status running (202), background task:
  → ingesta.cargar_csvs (strict)               → loader.load_run_tables (tolerant)
            ╲                                   ╱
             in-memory DuckDB with the 8 tables
               → runner: every rule(con) → Signals (+ failures, isolated)
               → ensamblador: clusters per scheme → Findings / leads_not_pursued / data quality
               → submission + official validator (withheld if it fails)
               → case file HTML
             → FraudAnalysis                    → fraud_analysis + fraud_signal, status completed
```

**Rules** are pure functions `rule_<id>(con, <thresholds with defaults>) -> pandas.DataFrame`.
Each one runs SQL against DuckDB and returns a *Signal* with these columns, in this order:
`rule_id, source_table, entity_id, evidence_id, fecha_deteccion, severidad,
autosuficiencia, monto`. Extra context columns may follow. `evidence_id` is always the
primary key of one exact row of `source_table`. Rules don't depend on each other. A rule
that raises an exception or breaks the contract is skipped. It is reported in
`rule_failures` and `warnings`, and the other rules still run.

**Assembler** (`ensamblador.py`). It groups the entities that signals connect, one
union-find per scheme. A cluster is accused (becomes a `finding`) when either of these
holds:

- It is supported by at least **2 independent evidence families** (`FAMILIA`).
- It has a rule in `REGLAS_SUFICIENTES_SOLAS`: `EFOS_DIRECT_MATCH` or `PAYMENT_TO_EMPLOYEE_ACCOUNT`.

It also needs ≥3 exhibits and an amount. Everything else becomes a `leads_not_pursued`
entry with a templated reason: `senal_unica`, `materialidad`, `exhibits_insuficientes`,
`sin_monto`, `no_resuelta` or `solo_empresa`. `confidence` is `proven` when the cluster
has any `autosuficiente` signal, otherwise `probable`. Data-integrity rules never
accuse; they are reported as `data_quality`.

### Rules

These are the 24 implemented detectors. The severity values stay in Spanish on purpose
(`alta`/`media`/`baja`, `autosuficiente`/`presuntiva`). Thresholds are the defaults in
each function's signature. Each rule's docstring explains the indicator and its legal
basis, and `GET /fraud/rules` returns it as `description`.

| Package | rule_id | Scheme | Evidence family | Severity | Self-sufficiency | Tables | Thresholds |
|---|---|---|---|---|---|---|---|
| phantom_vendor | `EFOS_DIRECT_MATCH` ¹ | phantom_vendor | lista_sat | alta | presuntiva | invoices, efos_list | |
| phantom_vendor | `EFOS_PRESUNTO_MATCH` | phantom_vendor | lista_sat | media | presuntiva | invoices, efos_list | |
| phantom_vendor | `EFOS_POST_DATED` | phantom_vendor | lista_sat | media | presuntiva | invoices, efos_list | |
| phantom_vendor | `VENDOR_SHORT_LIFECYCLE` | phantom_vendor | alta_reciente | media | presuntiva | vendors, invoices | dias_umbral=30 |
| phantom_vendor | `INVOICE_NO_PO_NO_CONTRACT` | phantom_vendor | sin_materialidad | media | presuntiva | invoices, purchase_orders, contracts | monto_minimo=50000 |
| phantom_vendor | `SHARED_CLABE_MULTI_RFC` | phantom_vendor | cuenta_compartida | alta | presuntiva | vendors | |
| kickback | `PAYMENT_TO_EMPLOYEE_ACCOUNT` ¹ | kickback ² | pago_a_empleado | alta | autosuficiente | bank_txns, employees | |
| kickback | `APPROVER_VENDOR_CONCENTRATION` | kickback | concentracion_aprobador | media | presuntiva | ledger, invoices | min_operaciones=5, min_concentracion_relativa=2.0 |
| kickback | `NO_SEGREGATION_OF_DUTIES` | kickback | segregacion | alta | autosuficiente | purchase_orders | |
| kickback | `PRICE_OUTLIER_BY_CATEGORY` | kickback | sobreprecio | media | presuntiva | invoices, vendors | desviaciones=2.0, min_facturas_categoria=3 |
| round_tripping | `BANK_CYCLE_2NODE` | round_tripping | ciclo_bancario | alta | presuntiva | bank_txns | dias_ventana=30, tolerancia_pct=0.1 |
| round_tripping | `BANK_CYCLE_NNODE` | round_tripping | ciclo_bancario | alta | presuntiva | bank_txns | max_nodos=5, dias_ventana=60, tolerancia_pct=0.1 |
| round_tripping | `CYCLE_LEAKAGE_RATE` | round_tripping | comision_repetida | alta | presuntiva | bank_txns | max_nodos=5, dias_ventana=60, tolerancia_pct=0.1, min_ciclos=2, fuga_maxima=0.1 |
| round_tripping | `OUTBOUND_TO_SUSPECT_ENTITY` | phantom_vendor | — (derived) | alta/media | presuntiva | bank_txns, vendors, efos_list | |
| round_tripping | `INVOICE_BIDIRECTIONAL` | round_tripping | factura_espejo | media | presuntiva | invoices | dias_ventana=90, tolerancia_pct=0.2 |
| round_tripping | `BANK_TXN_NOT_IN_LEDGER` | round_tripping | sin_registro_contable | alta/media | presuntiva | bank_txns, ledger | dias_tolerancia=3, tolerancia_monto=0.01 |
| threshold_splitting | `SAME_APPROVER_SPLIT` | threshold_splitting | ordenes_fraccionadas | alta | autosuficiente | purchase_orders | dias_ventana=7, umbral_monto=50000 |
| threshold_splitting | `CONTRACT_SPLIT_INTO_POS` | threshold_splitting | contrato_fraccionado | alta | presuntiva | contracts, purchase_orders | dias_ventana=7, tolerancia_pct=0.02 |
| revenue_inflation | `INFLATE_AND_CANCEL` | revenue_inflation | cancelada_sin_reversion | media | presuntiva | invoices, ledger | tolerancia_monto=0.01 |
| revenue_inflation | `AR_AGING_EXCESSIVE` | revenue_inflation | cxc_sin_cobro | media | presuntiva | ledger, invoices | dias_umbral=90, tolerancia_monto=0.01 |
| data_integrity | `LEDGER_UNBALANCED_ENTRY` | — (data quality) | — | alta | autosuficiente | ledger | tolerancia=0.01 |
| data_integrity | `ORPHAN_INVOICE_UUID` | — (data quality) | — | alta | autosuficiente | ledger, invoices | |
| data_integrity | `MALFORMED_RFC` | — (data quality) | — | media | autosuficiente | vendors, invoices, efos_list | |
| data_integrity | `CLABE_INVALID_LENGTH` | — (data quality) | — | media | autosuficiente | vendors, employees | |

¹ Sufficient on its own to accuse. ² Counted as `phantom_vendor` when the destination
CLABE is registered to a vendor.

The catalog also lists rules that aren't implemented yet: `PO_NEAR_THRESHOLD`,
`PO_WINDOW_SUM_SPLIT`, `BANK_TXN_WINDOW_SPLIT`, `BENFORD_DEVIATION_*`,
`INVOICE_NO_COLLECTION`, `PERIOD_END_SPIKE`, `RECEIVER_NO_PAYMENT_HISTORY` and
`RECEIVER_IN_EFOS`. `GET /fraud/rules` reports them with `implemented: false`, the same
as the reference. The folder READMEs under `app/fraud/rules/*/` explain each rule in
detail.

---

## API

All routes are under `/api/v1`. Errors use the project envelope
`{"error": {"code", "message", "details"}}`.

### `POST /fraud/analyze`

Runs synchronously. It requires the session cookie, and nothing is persisted.

**Request.** Send `multipart/form-data` with one file field per table: `vendors`,
`invoices`, `ledger`, `bank_txns`, `purchase_orders`, `contracts`, `employees` and
`efos_list`. Each must be a UTF-8 CSV whose header has **exactly** the schema columns,
in any order. The optional `seed` form field (int, default 0) is copied to
`submission.seed`.

```bash
curl -b cookies.txt -F seed=1301 \
  $(for t in vendors invoices ledger bank_txns purchase_orders contracts employees efos_list; do
      printf -- '-F %s=@tests/fixtures/fraud/seed1301/%s.csv ' $t $t; done) \
  http://127.0.0.1:8000/api/v1/fraud/analyze
```

**Response `200`: `FraudAnalysis`**

```json
{
  "status": "completed",
  "engine_version": "0.1.0",
  "seed": 1301,
  "rules_evaluated": 24,
  "rules_triggered": 14,
  "findings_count": 5,
  "total_exposure": 555475.73,
  "submission": { "seed": 1301, "findings": [...], "leads_not_pursued": [...], "run_metadata": {...} },
  "signals": [
    {
      "rule_id": "EFOS_DIRECT_MATCH", "scheme_type": "phantom_vendor", "evidence_family": "lista_sat",
      "source_table": "invoices", "entity_id": "HRG820921GTE", "evidence_id": "INV-00358",
      "detected_on": "2026-03-05", "severity": "alta", "self_sufficiency": "presuntiva",
      "amount": 37007.48,
      "context": { "efos_status": "definitivo", "efos_publication_date": "2026-01-01" }
    }
  ],
  "signals_per_rule": { "rule_efos_direct_match": 2, "...": 0 },
  "data_quality": { "MALFORMED_RFC": 0 },
  "rule_failures": [ { "rule": "rule_x", "status": "error", "error": "RuntimeError: ..." } ],
  "warnings": [],
  "rows_per_table": { "vendors": 40, "invoices": 700, "...": 0 },
  "case_file_html": "<!doctype html>..."
}
```

- `submission` follows the official `submission_schema.json`. Each finding explains
  itself with `narrative`, `rule_broken`, `exhibits` (the exact source rows) and
  `money_trail`.
- `signals` holds the raw, auditable detector output behind findings and leads.
- `amount` values come from `REAL` columns and are not rounded.

| Status | `code` | Cause |
|---|---|---|
| 401 | `not_authenticated` | No valid session cookie. |
| 413 | `file_too_large` | A CSV exceeds `FRAUD_MAX_BYTES_PER_FILE`. |
| 422 | `invalid_dataset` | A file is missing or unreadable, a column is missing, extra or duplicated, a value doesn't cast, or a table has more than `FRAUD_MAX_ROWS_PER_TABLE` rows. `details` lists `{file, column, message}` for every problem at once. |
| 500 | `engine_output_invalid` | The submission failed the official validator, so it is withheld. `details` holds the validator messages. |

### Investigation runs

These build on the existing dataset upload (`POST /runs`, `GET /runs/{id}/validation`).

- **`POST /runs/{run_id}/start` → `202 RunState` (`running`).** The optional JSON body
  `{"seed": 1301}` sets the seed. The audit runs in a background task:
  - On success, the run becomes `completed` and gets a `fraud_analysis`.
  - On failure, it becomes `failed`, with `error` set to `{code, message, details}`.
    The code is `engine_output_invalid`, `investigation_failed` or `database_unavailable`.

  A `failed` run can be started again. The endpoint returns `409 validation_blocked` if
  the diagnostics have errors, or `409 invalid_state` if the run isn't `ready` or `failed`.
- **`GET /runs/{run_id}/result` → `FraudAnalysis`.** Returns
  `409 result_not_available` until the run is `completed`.
- **Poll `GET /runs/{run_id}`** to follow the status.

A run's dataset was already diagnosed at upload. Warnings the user accepted (a missing
optional table or column, a bad value) must not block the run afterwards, so runs load
their tables with `loader.py`:

- A missing optional table is created empty.
- A missing column is loaded as `NULL`.
- A value that doesn't cast becomes `NULL`. Thousands separators are stripped from
  numeric columns first.

A clean dataset produces exactly the same output as strict ingestion; the tests check this.

### `GET /fraud/rules` and `GET /fraud/health`

Both are public. `rules` returns the catalog: `rule_id`, `scheme_type`,
`evidence_family`, `family_description`, `data_quality`, `implemented` and
`description`. `health` returns `{status: ok|degraded, engine_version, rules_loaded,
rule_load_errors}`.

---

## Database

The changes are in `database/alter.sql` (the migration dated 2026-09-13). Apply them with
`psql "$DATABASE_URL" -f database/exec.sql`.

| Table | Contents |
|---|---|
| `fraud_analysis` | One row per completed run (`run_id` PK → `investigation_run` ON DELETE CASCADE). It holds the summary counters, the validated `submission` (jsonb), per-rule counts, data quality, failures, warnings, rows per table and `case_file_html`. Re-running a run replaces its row. |
| `fraud_signal` | Every detector row behind an analysis. PK `(run_id, ordinal)`, where `ordinal` keeps the engine's order. FK → `fraud_analysis` ON DELETE CASCADE. It has CHECK constraints on `severity` and `self_sufficiency`, and indexes `(run_id, rule_id)` and `(run_id, entity_id)` for drill-down. Signals are written with a single `COPY`. |

The estate itself is never stored in PostgreSQL. The engine runs over an in-memory
DuckDB. The rule catalog isn't stored either: it's static code, so it can't drift from
the rules it describes, and nothing needs seeding in `exec.sql`.

## Configuration

| Variable | Default | Reference equivalent |
|---|---|---|
| `FRAUD_MAX_BYTES_PER_FILE` | 52428800 (50 MB) | `MOTOR_MAX_BYTES_ARCHIVO` |
| `FRAUD_MAX_ROWS_PER_TABLE` | 1000000 | `MOTOR_MAX_FILAS` |

The reference's `MOTOR_API_KEY` is gone; authentication is this API's session cookie.
Runs also use the existing `RUNS_STORAGE_DIR` and `RUNS_MAX_UPLOAD_BYTES`. The only
added dependency is `pandas` (≥3.0.5; the reference pins 3.0.5). DuckDB was already a
dependency.

---

## Adding a rule

1. Read the rule catalog and conventions in
   `motor-agente-forense/spec_reglas_deteccion_fraude.md` and the READMEs in
   `app/fraud/rules/*/`.
2. Create `app/fraud/rules/<scheme>/<rule_name>.py` with
   `def rule_<rule_id_lowercase>(con: duckdb.DuckDBPyConnection, <thresholds with defaults>) -> pd.DataFrame`.
   Follow these conventions:
   - Return the 8 contract columns first, then any context columns.
   - Use `UPPER(TRIM(...))` on RFCs.
   - Use `TRY_CAST(... AS DATE)` on `TEXT` dates.
   - Use `CAST(... AS DOUBLE)` before arithmetic on `REAL` amounts.
   - Pass values with `?` placeholders.
   - Don't write to the estate, and don't use global state.
   - Write a docstring that states the indicator and its legal basis.
3. Add the function to `RULES` in that package's `__init__.py`. A rule that isn't in `RULES` never runs.
4. If it is evidence of a scheme, add it to `RULE_TO_SCHEME` and `FAMILIA` in
   `app/fraud/engine/catalogo.py`. A data-quality rule goes in `REGLAS_INTEGRIDAD`
   instead. If its `entity_id` isn't an RFC, check entity resolution in
   `entidades.py` and citations in `evidencia.py`.
5. Add a positive and a negative test with synthetic rows in `tests/test_fraud/test_rules.py`, using the `con` and `insertar` fixtures.
6. If the change is intentional and alters the seed 1301 output, regenerate
   `tests/fixtures/fraud/seed_1301.json` without `run_metadata.wall_clock_seconds`.

Never read ground-truth or private files from `app/`. `tests/test_fraud` greps
`app/fraud` for that the same way the judges do.

---

## Equivalence with the reference

- `tests/test_fraud/test_rules.py` and `test_pipeline.py` are 1:1 ports of the reference
  tests. They check the per-rule positive and negative cases, the signal contract on
  empty and real estates, and that the seed 1301 submission is **identical** to the
  reference's `tests/esperado/seed_1301.json`. They also check determinism, ingestion
  errors, and that the validator copy is byte-identical.
- `tests/test_fraud/test_api.py` covers the endpoints and error handling. It also covers
  rule failure isolation, the validator gate, and run execution with persistence and
  retry. It checks that the run loader gives the same result as strict ingestion.
- A one-off comparison (2026-09-13, reference HEAD `06e60f3`) ran both implementations
  over all 200 synthetic estates in `motor-agente-forense/datasets/`: **200/200
  identical**. It compared the submission, validator result, warnings, data quality,
  signals per rule and case file, with the case file's wall-clock metric normalized.
  Neither side had an error.

## Behavior differences from the reference (intentional)

| Area | Reference | Here | Why |
|---|---|---|---|
| Auth | `X-API-Key` = `MOTOR_API_KEY` | Session cookie (`/fraud/analyze`, runs). `rules` and `health` are public. | Uses this API's auth model. |
| Routes | `/v1/auditorias`, `/v1/reglas`, `/v1/salud` | `/api/v1/fraud/analyze`, `/fraud/rules`, `/fraud/health` | Matches this API's URL convention. |
| Error format | `400 {detalle, errores:[{archivo,columna,mensaje}]}`, `413`, `500 {detalle, errores_validacion}` | Project envelope: `422 invalid_dataset` with details `{file,column,message}`, `413 file_too_large`, `500 engine_output_invalid` | One error shape across the API; 422 is what this API uses for unusable input. |
| Response envelope | `filas_por_tabla`, `calidad_datos`, `senales_por_regla`, `avisos` | `rows_per_table`, `data_quality`, `signals_per_rule`, `warnings`, plus `signals`, `rule_failures` and summary counters | English field names; the added fields expose the evidence the engine already computed. The submission's generated prose and legacy HTML export are English. |
| Rule loading | `importlib` over numbered folders | Explicit package registry, same order | The numbered folders couldn't be imported normally. |
| CLI / signals table | `python -m agente`, `agente.runner` writing a `signals` table to a `.duckdb` file | Removed; signals go to `fraud_signal` in PostgreSQL | The API is the entry point here. |
| Runs | — | Tolerant loader (see above) | Warnings accepted at upload must not become blocking. |

The detection rules, thresholds, scoring, family and sufficiency logic are unchanged.
Generated narratives and the legacy static HTML export have been translated to English.

## Known limitations

- Runs execute in-process, in a FastAPI background task. A run that is `running` when
  the process stops stays `running`, and there is no job queue or recovery.
- Rules from the catalog that aren't implemented in the reference aren't implemented
  here either (see [Rules](#rules)). Three files in the reference's
  `src/rules/2_kickback/` were deliberately not ported, because the reference never
  runs them:
  - `efos_definitive_match.py` duplicates `EFOS_DIRECT_MATCH`.
  - `efos_presunto_match.py` is empty.
  - `vendor_employee_name_similarity.py` needs text similarity, which is outside the SQL scope.
- The engine uses the `efos_list` table from the uploaded estate, not the real SAT
  69-B blacklist in PostgreSQL (`sat_blacklist_record`). Linking the two would change
  detection behavior and needs a product decision.
- The standalone HTML is a legacy static export. The report JSON endpoints are the
  canonical contract for the interactive frontend; a supported offline replay CLI
  remains deferred.
- The engine's calibration (the 2-family threshold, rules that are sufficient alone,
  materiality) was tuned on the reference's tuning seeds only.
