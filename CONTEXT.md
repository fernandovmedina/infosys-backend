# Project Context

> Single source of truth for this repository. Read this first.
> Written for developers and AI coding agents. Last verified against the repo and
> `/public/material/` on 2026-09-12 (HEAD `377d80b`).
>
> Labels used throughout:
> - **[OFFICIAL]** — stated in the challenge material. Cite the source file.
> - **[DECISION]** — a choice this project has made (visible in code or docs).
> - **[ASSUMPTION]** — an inference not stated anywhere. Verify before relying on it.

---

## TL;DR

- **Event:** HACKMTY 2026. **Challenge provider:** Infosys. **Track name:** *Forensic Auditor*.
- **Build:** an AI agent that investigates an unseen company "data estate" (vendors,
  invoices, ledger, bank transactions, POs, contracts, employees, SAT EFOS list), finds
  planted invoice-fraud schemes, **proves** them with cited records and a reconciled peso
  amount, and **declines** to accuse honest decoys, with a written reason for each.
- **Outputs:** a machine-checked `submission` JSON **and** a human-readable case file
  (HTML/PDF/Markdown) with a **rendered money-trail diagram**.
- **Scoring pillars:** Results, Judgment, Feasibility, Clarity. False accusations weigh
  **at least as much** as recall.
- **Repo today:** a FastAPI + PostgreSQL backend with **one feature**: a bulk SAT
  Art. 69-B blacklist check endpoint (TASK #1). The agent, estate generator, detectors,
  case-file renderer and evaluation harness **do not exist yet**.

---

## Hackathon

- **HACKMTY 2026** (Monterrey, Mexico). Source: `TODO.md` (TASK #2 brief).
- Deliverables are judged through working code plus a **3-minute live demo**.
  Source: `/public/material/challengue.md`.

## Challenge Provider

- **Infosys.** The material frames this as "the forensic work Infosys does at scale".
  Source: `/public/material/challengue.md`.

---

## Problem Statement

[OFFICIAL] Source: `/public/material/challengue.md` (English and Spanish versions; they match).

Invoice fraud in Mexico is hidden inside a real company's books, not a neat list of
flagged rows. Typical forms:

- a **fake supplier** billing for work never done;
- a **kickback** routed through a **shell company**;
- **sales faked** to inflate the numbers.

SAT (Mexico's tax authority) publishes a blacklist of fake-invoice companies under
**Artículo 69-B** (the EFOS list), but by the time a supplier appears on it, the company
has already claimed the deductions and is liable. Existing tools flag odd items one at a
time and leave humans to connect them; nobody follows the money end-to-end, nobody builds
the proof, and **honest suppliers who merely look odd get accused too**.

**The question:** *Given a company's books and only the hint that something is wrong, can
an AI agent find the fraud, follow the money, and prove it, without accusing anyone it
cannot back up?*

## Challenge Objectives

[OFFICIAL] Sources: `challengue.md`, `README.md`.

1. **Find** hidden fraud in records the agent has never seen.
2. **Follow the money** across ledger, invoices and bank records.
3. **Prove** each accusation: a clear rule broken, a peso amount and an evidence trail.
4. **Refuse** to accuse suppliers it cannot back up (decoys).
5. **Explain** leads it chose not to chase, and why.
6. **Defend** its reasoning when a judge asks a surprise question.

## Business Context

[OFFICIAL] Source: `challengue.md`.

- Every peso lost to fake invoices is taken from an honest business and the public purse.
- Every supplier wrongly accused **loses a customer for no reason**.
- An agent that investigates and proves (rather than flags) is the difference between "a
  report that falls apart" and "a case a company can act on".
- "Proving before accusing is what separates a real auditor from a guesser."
- Target user (implied by the Feasibility criterion): a **real finance or audit team**.

## Fraud Detection Context

[OFFICIAL] Sources: `challengue.md`, `README.md`, `submission_schema.json`.

### The five scheme types (fixed enum)

`phantom_vendor` · `kickback` · `round_tripping` · `threshold_splitting` · `revenue_inflation`

What the material actually says about each (nothing more is specified):

| `scheme_type` | Description in the material |
|---|---|
| `phantom_vendor` | "a fake supplier billing for work never done" (`challengue.md`) |
| `kickback` | "a kickback routed through a shell company"; AMLSim produces "shell-company patterns behind kickbacks" (`challengue.md`) |
| `round_tripping` | "money that moves in a circle"; AMLSim produces "money-flow rings… round-tripping" (`challengue.md`) |
| `threshold_splitting` | **No description.** Only indirect hint: `purchase_orders.approver` comment "the approval-limit trail lives here" (`estate_schema.sql`) |
| `revenue_inflation` | "sales faked to inflate the numbers" (`challengue.md`) |

### Suggested approaches (not mandatory)

[OFFICIAL] Source: `challengue.md`.

1. **Investigate step by step:** start from a theory, search ledger/invoices/bank records,
   follow a lead, change course on dead ends.
2. **Simple detectors** to point the agent at what's worth digging into. Examples given:
   **blacklisted suppliers**, **payments that do not match invoices**, **money that moves
   in a circle**.
3. **Evidence trail for every accusation**; refuse to name a supplier without **a clear
   rule broken and a peso amount**.

### Judge-run estates

[OFFICIAL] Source: `README.md`.

- Judges run the system on **estates you have never seen**, generated to
  `estate_schema.sql`, with a mix of **planted schemes and decoys**.
- Scheme and decoy counts vary; the maximum is **all five scheme types with ten decoys in
  one estate**.
- Schemes may be **entangled**: two schemes share an entity, so a money trail crosses
  scheme boundaries.
- **Decoys** are "honest entities that trip a detector and check out on inspection.
  Accusing one is a false accusation." (`ground_truth_schema.json`)
- In the live demo, judges **hide a fresh scheme** in the data; the agent traces the money
  on screen, then answers **one surprise question** about its reasoning (`challengue.md`).

---

## Expected Solution

[OFFICIAL] Source: `challengue.md`.

A **forensic agent** that investigates records it has never seen and hands in a **case
file** containing:

- the scheme,
- the suppliers involved,
- the evidence trail,
- the peso amount,
- a short list of **leads it chose not to chase and why**.

Plus **working code** and a **3-minute live demo**.

## Functional Requirements

[OFFICIAL] unless marked. Sources in brackets.

| # | Requirement | Source |
|---|---|---|
| F1 | Accept an estate **at a path given at run time**. Hardcoded paths fail. | `README.md` |
| F2 | Estate follows `estate_schema.sql` table/column names exactly (CFDI 4.0 names: `uso_cfdi`, `forma_pago`, `metodo_pago`, RFC, UUID, CLABE). | `estate_schema.sql` |
| F3 | Emit a `submission` JSON conforming to `submission_schema.json`. | `submission_schema.json` |
| F4 | Emit a human-readable **case file** following `case_file_structure.md`. "Emit both." | `submission_schema.json`, `case_file_structure.md` |
| F5 | `findings` contains **validated accusations only**. An empty list is legitimate. | `submission_schema.json` |
| F6 | Every accusation **validates before it is printed**: every cited `record_id` exists; `peso_amount` reconciles within **2%**. | `README.md` |
| F7 | Every entity in a finding has ≥1 exhibit supporting its involvement. | `submission_schema.json` |
| F8 | `rule_broken` names a **specific rule or article** (e.g. `SAT Articulo 69-B`), not a statistical pattern. | `submission_schema.json`, `case_file_structure.md` |
| F9 | Each declined lead has a **specific** reason naming evidence examined. Generic text ("insufficient evidence") is scored as generic. | `submission_schema.json`, `README.md` |
| F10 | Report run cost: **LLM call count, MXN cost, wall-clock seconds**. | `README.md` |
| F11 | Answer judge questions **from a log/page in under ten seconds**, without re-running. | `README.md` |
| F12 | Build/maintain your own **ground truth** for evaluation, isolated from the agent. | `README.md`, `ground_truth_schema.json` |
| F13 | Produce a **Results table** over ≥5 held-out seeds. | `README.md`, `results_table_template.csv` |

## Technical Requirements

[OFFICIAL]

- **Determinism:** the same seed must produce the same case file; judges may run a seed
  twice. Source: `README.md`, `submission_schema.json` (`seed`, `run_metadata.deterministic`).
- **Offline replay:** reproduce a completed run with **connectivity disabled**; the case
  file must be producible **without a network call**. Sources: `README.md`,
  `case_file_structure.md`.
- **Ground-truth isolation:** ground truth is written to a separate file the agent's tools
  can never open, referenced **only** from the evaluation harness, never from the agent,
  its tools, or anything they import. Judges may run
  `grep -r 'ground_truth' your_project/src/ --include='*.py'`. Sources: `README.md`,
  `ground_truth_schema.json`.
- **Format validation:** `validate_format.py` "exits non-zero on a format error. Wire it
  into your build." Source: `README.md`.
- **LLM tooling note:** the track makes many AI calls per investigation, so a **local model
  (Ollama) with caching** is "safer than the Gemini free tier alone, which can hit daily
  limits". This is advice, not a requirement. Source: `challengue.md`.

## Constraints

[OFFICIAL]

- Five scheme types only, fixed enum. Source: `submission_schema.json`.
- `source_table` enum: `ledger`, `invoices`, `bank_txns`, `vendors`, `efos_list`,
  `purchase_orders`, `contracts`, `employees`.
- `confidence` enum: `proven`, `probable`.
- `closed_by` enum: `investigator`, `challenger`, `validator`.
- `narrative` ≤ **150 words**. `exhibits` ≥ **3** per finding. `peso_amount` > 0.
- Entity ids **must be prefixed**: `RFC:AAAA010101AA1` (vendor/company), `EMP:0001`
  (employee). Judges match on these strings.
- Tuning seeds and reporting seeds **must be disjoint**, and both must be named in the pitch.
- If ground truth appears to leak into reasoning (e.g. naming a scheme type *before*
  investigating), **Results caps at 2** regardless of the numbers.
- A prose-only money trail **caps Clarity at 3**.
- Fewer than 5 unseen seeds "caps you lower" on Results. Source: `results_table_template.csv`.

## Evaluation Criteria

[OFFICIAL] Sources: `challengue.md` (criteria), `README.md` (scoring rules).

| Criterion | Question judges ask |
|---|---|
| **Results** | On records it has never seen, how much hidden fraud does the agent find and correctly prove? |
| **Judgment** | Does it refuse to accuse suppliers it cannot back up, and can it defend a finding when asked? |
| **Feasibility** | Could a real finance or audit team trust and use this? ("We don't know" on cost numbers scores low.) |
| **Clarity** | Is the case file easy to follow, with a clear money trail? (Scored on whether a **non-technical** reader follows it unaided.) |

Scoring rules (`README.md`):

- **"Recall is half the measure."** False accusations against decoys are weighted **at
  least as heavily**. Accusing every vendor gives perfect recall and scores badly.
- Report **recall AND false-accusation rate**, as a table, across **≥5 held-out seeds**.
- Machine checks on the JSON: recall, false-accusation rate, peso reconciliation.

Questions judges ask (`README.md`), verbatim:

- "What happens if I change this input?"
- "Why should I trust this number?"
- "What does it do when it's wrong, or when there's nothing to find?"
- "Could a real audit team run this tomorrow?"
- "What did you cut, and why?"
- "Why didn't you flag vendor X?"
- "How confident are you in finding 2?"
- "What if the employee just happens to bank at the same institution?"

"Answering from a log in under ten seconds is itself scored."

## Expected Deliverables

[OFFICIAL]

1. **Working code**: agent + tools, accepting an estate path at run time. (`challengue.md`, `README.md`)
2. **Submission JSON** per run (`submission_schema.json`).
3. **Case file** per run: HTML, PDF or Markdown, openable without your laptop, with a
   rendered money-trail diagram (`case_file_structure.md`).
4. **Results table** (one slide) from ≥5 held-out seeds (`results_table_template.csv`).
5. **Pitch** naming tuning seeds vs reporting seeds (`README.md`).
6. **3-minute live demo** with a judge-hidden scheme and one surprise question (`challengue.md`).
7. **Cost figures ready:** LLM calls, MXN cost, wall-clock seconds (`README.md`).

Implied but not named as a deliverable: an **estate generator** (or adapted dataset) and
an **evaluation harness** with ground truth. "You build your own data estate." (`README.md`)

---

## Available Materials

All files under `/public/material/` (plus `.DS_Store` files, which are macOS metadata and
irrelevant). The folder "contains no dataset" (`README.md`).

| Path | Kind | What it provides / why it matters |
|---|---|---|
| `/public/material/challengue.md` | Challenge brief (EN + ES) | **Primary source.** Problem, big question, suggested approaches, resources (SAT 69-B, CFDI 4.0, IBM AMLSim, IEEE-CIS), Ollama note, what to build, why it matters, the four judging criteria. Note the filename typo: `challengue`, not `challenge`. |
| `/public/material/README.md` | Rules | Index of the other files; validator usage; **what judges run** (unseen estates, schemes + decoys, entanglement, ≤5 schemes + 10 decoys); **scoring rules** (recall vs false accusations, held-out seeds, ground-truth isolation + grep, 2% reconciliation per table, declined leads in body, three numbers, determinism, offline replay); judge questions. |
| `/public/material/estate_schema.sql` | Input contract | The 8 estate tables and their CFDI 4.0 / accounting column names. Rows are field-shape placeholders only. See [Dataset / Data Sources](#dataset--data-sources). |
| `/public/material/submission_schema.json` | Output contract | JSON shape of findings, leads, run metadata; all enums; entity-id prefix rule; peso reconciliation rule. |
| `/public/material/submission_example.json` | Output example | Field shape only, "not a worked solution". One `phantom_vendor` finding (139,200.0 = 92,800 + 46,400 from two invoices), one declined lead, zeroed metadata. |
| `/public/material/ground_truth_schema.json` | Eval contract | Shape of an answer key: `seed`, `company_rfc`, `schemes[]` (id, type, entities, supporting invoices/txns, peso amount, difficulty `easy/medium/hard`), `decoys[]` (entity, signal, why_innocent, invoices). Isolation requirement. |
| `/public/material/case_file_structure.md` | Report contract | Required case-file sections, in order, and the per-finding elements. See [Case file](#case-file-required-structure). |
| `/public/material/validate_format.py` | Tool (stdlib Python) | Structural validator + optional estate check against a **SQLite** `.db`. See [Validator behaviour](#validator-behaviour). |
| `/public/material/results_table_template.csv` | Report template | Columns for the Results slide. See [Results table](#results-table). |

### External resources named (not in the repo)

[OFFICIAL] Source: `challengue.md`. None are downloaded or vendored here except the SAT list.

- **SAT Artículo 69-B list (EFOS)**: official, downloadable. A snapshot is at repo root as
  `black_list.csv`.
- **CFDI 4.0 invoice schemas** (SAT).
- **IBM AMLSim** (open source): money-flow rings and shell-company patterns (kickbacks,
  round-tripping).
- **IEEE-CIS fraud dataset (Kaggle)**: baselines for anomaly checks.
- **Ollama** (local LLM) and **Gemini free tier** mentioned as tooling options.

---

## Dataset / Data Sources

### 1. Estate schema (input the agent investigates)

[OFFICIAL] Source: `/public/material/estate_schema.sql`. SQLite-style types (`TEXT`,
`REAL`, `INTEGER`). Keep column names: "Judges read these column names directly… every
Finding exhibit cites a `source_table` value from this schema by name."

| Table | PK (= `record_id` column) | Columns | Notable comments |
|---|---|---|---|
| `vendors` | `rfc` | `legal_name`, `registered_date` (ISO 8601), `address`, `bank_clabe` (18 digits), `category`, `contact_email` | RFC is 12–13 chars |
| `invoices` | `uuid` | `issuer_rfc`, `receiver_rfc`, `issue_date`, `subtotal`, `iva` (16% VAT), `total`, `concepto_text`, `uso_cfdi` (e.g. `G03`), `forma_pago` (e.g. `03`), `metodo_pago` (`PUE`\|`PPD`), `status` (`vigente`\|`cancelado`) | `total` is cited for reconciliation; own id scheme acceptable (e.g. `INV-00001`) |
| `ledger` | `entry_id` (INTEGER) | `date`, `account_code`, `account_name`, `debit`, `credit`, `description`, `invoice_uuid` (nullable link), `cost_center`, `approver` | `approver`: "who signed off, or evidence that nobody did" |
| `bank_txns` | `txn_id` | `date`, `from_clabe`, `to_clabe`, `amount`, `reference`, `channel` (`SPEI`\|`cheque`\|`efectivo`) | `amount` cited for reconciliation |
| `purchase_orders` | `po_id` | `vendor_rfc`, `date`, `amount`, `requester`, `approver`, `description` | "the approval-limit trail lives here" |
| `contracts` | `contract_id` | `vendor_rfc`, `start_date`, `value`, `scope_text` | |
| `employees` | `emp_id` (e.g. `EMP:0001`) | `name`, `role`, `bank_clabe`, `hire_date` | `bank_clabe` "required for any employee-linkage scheme" |
| `efos_list` | `rfc` | `legal_name`, `status` (`definitivo`\|`presunto`), `publication_date` | Mirrors SAT 69-B list; `XAXX010101000` is the well-known generic placeholder RFC |

Example amounts in the placeholders: subtotal 80,000 + IVA 12,800 = total 92,800; 40,000 +
6,400 = 46,400. Placeholder company RFC `EMP920101AB1`.

Join keys implied by the schema: `invoices.issuer_rfc/receiver_rfc` ↔ `vendors.rfc`;
`ledger.invoice_uuid` ↔ `invoices.uuid`; `bank_txns.from_clabe/to_clabe` ↔
`vendors.bank_clabe` / `employees.bank_clabe`; `purchase_orders.vendor_rfc`,
`contracts.vendor_rfc` ↔ `vendors.rfc`; `efos_list.rfc` ↔ `vendors.rfc`.

### 2. `black_list.csv` (repo root): real SAT Art. 69-B snapshot

Facts verified by reading the file and `README.md`:

- Encoding **cp1252**. Two preamble lines ("Información actualizada al **31 de julio de
  2026**…", "Listado completo de contribuyentes (Artículo 69-B del CFF)"), then a header.
- **20 columns:** `No`, `RFC`, `Nombre del Contribuyente`, `Situación del contribuyente`,
  then 8 (oficio, publication-date) pairs for presunción / desvirtuado / definitivo /
  sentencia favorable, each for SAT page and DOF.
- **14,761 data rows**. `Situación` counts: Definitivo 11,917 · Sentencia Favorable 1,666 ·
  Presunto 838 · Desvirtuado 340.
- After import: 14,729 rows (32 exact duplicates collapsed), **238 redacted rows**
  (`RFC = XXXXXXXXXXXX`, name "Información suprimida…").
- **RFC is not unique:** 78 RFCs occupy 322 rows (one RFC can hold several procedures).

### 3. Ground truth and seeds

Not present in the repo. Must be generated per seed alongside each estate (see
`ground_truth_schema.json`) and kept out of the agent's reach.

---

## Contract Details

### Submission JSON

[OFFICIAL] Source: `submission_schema.json`.

```text
submission (required: seed, findings, leads_not_pursued, run_metadata)
├── seed: int                          same seed → same output
├── findings[]                         validated accusations only; [] is valid
│   ├── scheme_type*   enum(5)
│   ├── entities*      [str] minItems 1, prefixed ("RFC:…", "EMP:…")
│   ├── narrative*     str, ≤150 words, non-technical
│   ├── rule_broken*   str, specific rule/article
│   ├── peso_amount*   number > 0, reconciles to exhibits
│   ├── confidence*    proven | probable
│   ├── money_trail    [{from, to, amount, date, exhibit_id}] ordered; each step's `to` is the next step's `from`
│   └── exhibits*      [{exhibit_id, source_table enum(8), record_id, note}] minItems 3
├── leads_not_pursued[]
│   ├── entity*, signal*, reason*
│   ├── tool_calls_made [str]
│   └── closed_by      investigator | challenger | validator
└── run_metadata (required: llm_calls:int, mxn_cost, wall_clock_seconds)
    ├── cost_by_role: object
    └── deterministic: bool
```
`*` = required.

**Peso reconciliation rule:** `peso_amount` must equal the sum of cited exhibit amounts
within **2%**. Amounts are summed **per table** and reconciled against the
**best-matching table**, so citing an invoice *and* the bank transfer that settled it is
not double-counted.

### Validator behaviour

[OFFICIAL] Source: `validate_format.py` (stdlib only).

```bash
python3 public/material/validate_format.py --submission my_findings.json
python3 public/material/validate_format.py --submission my_findings.json --estate my_estate.db
```

- Constants: `MIN_EXHIBITS = 3`, `MAX_NARRATIVE_WORDS = 150` (whitespace split),
  `PESO_TOLERANCE = 0.02`.
- Record-id columns: `ledger.entry_id`, `invoices.uuid`, `bank_txns.txn_id`, `vendors.rfc`,
  `efos_list.rfc`, `purchase_orders.po_id`, `contracts.contract_id`, `employees.emp_id`.
- **Amount-bearing tables** (only these count toward reconciliation): `invoices.total`,
  `bank_txns.amount`, `purchase_orders.amount`, `contracts.value`. **`ledger` is not
  amount-bearing** for the validator. A finding citing no amount-bearing table fails.
- Reconciliation check: `abs(claimed - best) > 0.02 * max(best, 1)` → error, where `best` is
  the per-table sum closest to `peso_amount`.
- Treats a **missing `money_trail` as an error**, and each step's `exhibit_id` must match an
  exhibit in the same finding. Duplicate `exhibit_id`s within a finding are errors.
- Entity prefix check only tests that `:` is present.
- Does **not** check trail connectivity, word count semantics, or correctness.
- `--estate` opens the file with **`sqlite3`**.

### Case file required structure

[OFFICIAL] Source: `case_file_structure.md`. Sections **in this order**:

1. **Header**: company name, audit period, estate seed, LLM call count, MXN cost,
   wall-clock seconds, whether the run is deterministic.
2. **Executive summary**: plain language, few sentences, plus a table with *Findings*
   (count, with confidence levels), *Total exposure* (pesos), *Leads investigated and
   closed* (count). Reading only this section should convey the result.
3. **One section per finding**, elements in order:
   **Heading** (entity name + id, scheme type) → **Rule broken** → **Amount and confidence**
   (`proven`/`probable`) → **What happened** (<150 words) → **Money trail** (**rendered
   diagram**, every step cites an exhibit id) → **Exhibits table** (exhibit id, source
   table, record id, one sentence each) → **Reconciliation** (arithmetic).
   If an adversarial review runs, include what it argued and why the finding survived.
4. **Leads not pursued** (in the body, **not** an appendix): entity named; detector/check
   that pointed there; specific closing reason referencing evidence; tools called; who
   closed it (investigator, adversarial reviewer, or validator).
5. **Method and limits**: architecture in a few sentences; what was out of scope; what the
   system **cannot** detect; how to regenerate the file.

### Results table

[OFFICIAL] Source: `results_table_template.csv`. One table, one slide, held-out seeds.
Columns, exactly:

```
seed,schemes_planted,schemes_found,recall_pct,decoys_planted,decoys_accused,false_accusation_rate_pct,peso_claimed,peso_actual,peso_reconciles,llm_calls,mxn_cost,wall_clock_s
```

Five seed rows plus a `TOTAL` row. Delete the template's comment block when filling it in.

---

## Important Domain Concepts

| Term | Meaning (as used in the material / this repo) |
|---|---|
| **SAT** | *Servicio de Administración Tributaria*, Mexico's tax authority. |
| **Artículo 69-B CFF** | Article of the *Código Fiscal de la Federación* under which SAT publishes taxpayers presumed to issue invoices for non-existent operations. |
| **EFOS** | *Empresas que Facturan Operaciones Simuladas*: companies that issue fake invoices (the 69-B list). |
| **Situación** | Status in the 69-B list. Real CSV values: `Presunto` (presumed), `Definitivo` (confirmed), `Desvirtuado` (taxpayer rebutted), `Sentencia Favorable` (won in court). |
| **DOF** | *Diario Oficial de la Federación*, the official gazette where oficios are also published. |
| **Oficio** | Official SAT notice; the CSV carries its number and date per stage. |
| **RFC** | Mexican tax id. 12 chars for a company (*persona moral*), 13 for an individual (*persona física*): 3–4 letters, YYMMDD, 3-char homoclave. `XAXX010101000` is the generic placeholder. |
| **CFDI 4.0** | Mexico's electronic invoice standard. Field names used in the estate: `uuid`, `uso_cfdi`, `forma_pago`, `metodo_pago`. |
| **UUID** | CFDI fiscal folio (invoice id). |
| **IVA** | Mexican VAT, **16%** in the estate schema. |
| **PUE / PPD** | `metodo_pago`: *Pago en Una sola Exhibición* / *Pago en Parcialidades o Diferido*. |
| **vigente / cancelado** | Invoice status: valid / cancelled. |
| **CLABE** | 18-digit Mexican interbank account number. |
| **SPEI** | Mexican interbank electronic transfer system (a `bank_txns.channel` value, alongside `cheque`, `efectivo`). |
| **Estate** | The synthetic company data set (8 tables) an investigation runs on. |
| **Seed** | Integer that deterministically generates an estate and its ground truth. |
| **Decoy** | Honest entity that trips a detector but is cleared on inspection. |
| **Entangled schemes** | Two schemes sharing an entity; money trails cross scheme boundaries. |
| **Exhibit** | A cited record (`source_table` + `record_id`) with a one-sentence note on what it proves. |
| **Money trail** | Ordered, connected `from → to` steps, each citing an exhibit. |
| **Challenger** | `closed_by` value; corresponds to the "adversarial reviewer" in `case_file_structure.md`. |
| **Moche** | Spanish (MX) colloquial term for kickback (`challengue.md`, ES version). |

---

## Existing Project Architecture

[DECISION] Sources: `README.md`, `pyproject.toml`, source code.

- **Language/runtime:** Python **3.14** (`.python-version`), managed with **uv**.
- **Web:** FastAPI (`fastapi>=0.141.1`), uvicorn.
- **Database:** **PostgreSQL 17** via Docker Compose (`postgres:17-alpine`, host port
  **5433**, user/password/db `infosys`), accessed with **asyncpg** (no ORM). Extensions:
  `pg_trgm`, `unaccent`.
- **Config:** `pydantic-settings`, env vars / `.env` (`DATABASE_URL`,
  `DATABASE_POOL_MIN_SIZE`, `DATABASE_POOL_MAX_SIZE`,
  `BLACKLIST_MAX_COMPANIES_PER_REQUEST`=500, `BLACKLIST_NAME_SIMILARITY_THRESHOLD`=0.45).
- **Tooling:** ruff (line length 100), mypy **strict**, pytest + pytest-asyncio + httpx.
- **Layering:** `api/v1` routes → `sat/service` (batching, dedup, result assembly) →
  `sat/repository` (single SQL query) ; `sat/normalization` shared by importer and search;
  `core/` for config, pool, error envelope.
- **Error envelope** (all errors): `{"error": {"code", "message", "details"}}`; codes
  `validation_error` (422), `database_unavailable` (503), `http_error`, `internal_error` (500).
- **Schema management:** `database/database.sql` (immutable initial schema) +
  `database/alter.sql` (append-only idempotent migrations) + `database/exec.sql`
  (apply both, run importer, `ANALYZE`, print summary).

## Current Implementation

### Implemented: SAT blacklist check (TASK #1, commit `377d80b`)

`POST /api/v1/sat/blacklist/check`. Also `GET /health`.

- Input: `{"companies": [{"rfc"?, "name"?}, …]}`, 1..500 entries; each needs RFC or name;
  RFC validated against `^[A-ZÑ&]{3,4}[0-9]{6}[A-Z0-9]{3}$` after normalization; unknown
  fields rejected.
- **One DB query per request** regardless of batch size (`unnest` over parallel arrays);
  duplicates collapsed then re-expanded.
- Three match stages, each only for inputs still unresolved:
  1. `rfc` / `rfc_and_name`: B-tree on `rfc_normalized`;
  2. `name_exact`: B-tree on `name_normalized` or `name_core` (corporate suffix stripped);
  3. `name_fuzzy`: GIN trigram on `name_core`, threshold 0.45.
- Response per company: `blacklisted`, `match_type`, `similarity`, `effective_situacion`
  (severity `Definitivo > Presunto > Desvirtuado > Sentencia Favorable`), `cleared` (all
  matches Desvirtuado/Sentencia Favorable), `match` (most severe), `matches` (≤20),
  `match_count`. All 8 oficio/date pairs preserved.
- `blacklisted: true` ≠ guilty: cleared taxpayers are still listed.
- Redacted rows stored but excluded from all (partial) indexes and searches.
- Importer CLI `sat-blacklist-import` (`--csv`, `--dry-run`): cp1252, header detection,
  normalization, SHA-256 `source_hash` idempotency key (excludes `No`), COPY into unlogged
  staging + `sat_blacklist_merge_staging()` set-based upsert, per-row failure reporting.
- Measured latency (README): 1 RFC 3.1 ms; 500 RFCs 14.9 ms; 100 fuzzy names 50.9 ms.
- Tests: 57 test functions (normalization, importer, endpoint, `EXPLAIN ANALYZE` index-usage
  checks). DB tests **skip** when no database is reachable.

### How it relates to the challenge

- It is a building block for suggested approach #2, detector "**blacklisted suppliers**",
  and could back the estate's `efos_list` table. [ASSUMPTION: intended future use; nothing
  in the repo wires it to an estate or agent yet.]
- `cleared`/`effective_situacion` map naturally onto the decoy problem: a vendor present
  in 69-B but `Desvirtuado`/`Sentencia Favorable` should not be accused on that basis
  alone. [ASSUMPTION]

### Not implemented (core challenge deliverables)

- Estate generator (8 tables, seeded, with planted schemes + decoys + entanglement).
- Ground-truth writer and isolated evaluation harness; Results table producer.
- Estate loader accepting a runtime path.
- Detectors beyond the blacklist (payment/invoice mismatch, circular money flows,
  threshold splitting, etc.).
- Investigation agent loop, LLM integration (Ollama or other), caching, cost accounting.
- Adversarial reviewer ("challenger") and pre-print validator.
- Submission JSON serializer; case-file renderer with money-trail diagram.
- Integration of `validate_format.py` into the build.
- Determinism / offline replay mechanism.

## Important Files and Directories

| Path | Purpose |
|---|---|
| `CONTEXT.md` | This file. |
| `TODO.md` | Task briefs given to agents: TASK #1 (blacklist endpoint, done), TASK #2 (this document). |
| `README.md` | Detailed docs for setup, endpoint, search strategy, import, DB. |
| `CLAUDE.md`, `AGENTS.md` | Present but **empty**. |
| `Dockerfile` | Present but **empty**. |
| `docker-compose.yml` | Local PostgreSQL 17 on port 5433. |
| `pyproject.toml`, `uv.lock`, `.python-version` | Dependencies, tool config, Python 3.14. |
| `.env.example` | Config template. `.env` exists locally (gitignored). |
| `main.py` | Dev entry: `python main.py` → uvicorn on 127.0.0.1:8000. |
| `app/main.py` | App factory, lifespan (pool open/close), `/health`. |
| `app/api/router.py`, `app/api/v1/sat.py` | `/api/v1` router and the blacklist endpoint. |
| `app/core/{config,database,errors}.py` | Settings, asyncpg pool (sets `pg_trgm.similarity_threshold` per connection), error envelope. |
| `app/sat/normalization.py` | RFC/name normalization, suffix stripping, cleared/redacted rules. Changing it requires a re-import. |
| `app/sat/importer.py` | CSV → staging → merge; `sat-blacklist-import` CLI. |
| `app/sat/repository.py` | The single bulk search SQL. |
| `app/sat/service.py` | Dedup, ranking, result assembly. |
| `app/sat/schemas.py` | Pydantic request/response models and validation. |
| `database/database.sql` | Table `sat_blacklist_record`, partial indexes, trigger, staging table, merge function. |
| `database/exec.sql` | Init + seed (shells out to `uv run sat-blacklist-import`). |
| `database/alter.sql` | Append-only migrations; none yet. |
| `tests/` | `conftest.py`, `test_normalization.py`, `test_importer.py`, `test_blacklist_endpoint.py`, `test_search_performance.py`. |
| `black_list.csv` | SAT 69-B snapshot (31 Jul 2026). |
| `public/material/` | Official challenge material (untracked in git as of this writing). |
| `scripts/` | Gitignored local dir; contains an empty `detect.sh`. |

Commands:

```bash
uv sync --all-groups && cp .env.example .env && docker compose up -d
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f database/exec.sql
uv run uvicorn app.main:app --reload            # http://127.0.0.1:8000/docs
uv run ruff format . && uv run ruff check . && uv run mypy app main.py tests && uv run pytest
```

## Key Technical Decisions

[DECISION] All from the existing implementation (`README.md`, `database/*.sql`, code).

1. **PostgreSQL + asyncpg, no ORM** for the backend.
2. **Normalize in Python, store normalized columns**, query with plain equality so indexes
   are used (no function-wrapped columns).
3. **Trigram (pg_trgm) over full-text search** for names: short proper nouns, typos and
   truncations matter more than stemming. Exact stages run first.
4. **One row per procedure**, not per taxpayer; `source_hash` (not RFC) is the unique key.
5. **`situacion` as free text** (no ENUM/CHECK) so a new SAT status doesn't break refresh;
   unknown statuses count as *not cleared* (fail-safe).
6. **Redacted rows kept but unsearchable** via partial indexes.
7. **Single query per batch**, request cap 500, max 20 matches per company.
8. **Immutable base schema + append-only `alter.sql`.**
9. **DB tests skip** without a database.

No decisions have yet been made about the agent, LLM provider, estate storage format,
case-file format, or diagram technology.

## Assumptions

[ASSUMPTION] Not stated in the material; revisit if contradicted.

- The existing FastAPI/Postgres backend is meant to become part of (or a service for) the
  forensic agent, rather than being a separate product.
- Estates will be stored/delivered as **SQLite** files, because `estate_schema.sql` uses
  SQLite types and `validate_format.py --estate` opens `sqlite3`.
- The `efos_list` table in generated estates can be derived from `black_list.csv`
  (mapping `Situación` to `definitivo`/`presunto`), with synthetic vendor RFCs planted
  into it where a scheme needs it.
- Scheme behaviour beyond the one-line descriptions (e.g. what exactly constitutes
  `threshold_splitting`) is ours to define in the generator, as long as the enum and
  schema are respected.
- Monetary amounts are MXN (pesos) throughout.

## Conflicts and Inconsistencies in the Material

Documented, not resolved.

1. **Filename:** TASK #2 refers to `/public/material/challenge.md`; the actual file is
   `/public/material/challengue.md`.
2. **EFOS status values:** `estate_schema.sql` gives `efos_list.status` as
   `definitivo | presunto` (lowercase, 2 values). The real SAT CSV has **4** values
   (`Presunto`, `Definitivo`, `Desvirtuado`, `Sentencia Favorable`), capitalized.
3. **EFOS uniqueness:** `efos_list.rfc` is `PRIMARY KEY`, but in the real list one RFC can
   have several procedures (78 RFCs → 322 rows). The real list also has 8 oficio/date
   pairs vs the single `publication_date` column.
4. **Database engine:** the estate contract and validator are SQLite; the existing backend
   is PostgreSQL.
5. **`money_trail` requiredness:** not in the finding's `required` list in
   `submission_schema.json`, but `validate_format.py` reports its absence as an error.
6. **Trail connectivity:** schema says each step's destination must be the next step's
   source; the validator doesn't check it.
7. **Ledger amounts:** `ledger` is an allowed `source_table` with `debit`/`credit`, but the
   validator does not count it toward reconciliation.
8. **Case-file header vs JSON:** the case file requires company name and audit period;
   `submission_schema.json` has no such fields (ground truth has `company_rfc`).
9. **Grep path:** judges grep `your_project/src/`; this repo has no `src/` (code is in
   `app/`). Safest reading: keep the string `ground_truth` out of all agent code.
10. **`closed_by` naming:** `challenger` in the JSON vs "adversarial reviewer" in
    `case_file_structure.md` (same concept).
11. **`maxWords`** in `submission_schema.json` is not a standard JSON Schema keyword; the
    validator enforces it by whitespace word count.

## Open Questions

1. Should the forensic agent live in this repo (e.g. a new `app/` package or `src/`), or
   in a separate project that calls this backend?
2. Estate storage: SQLite files (matching the validator), PostgreSQL, or both (generate
   SQLite, load into Postgres)?
3. Which LLM: local Ollama model (recommended by the material), Gemini, Claude, or a mix?
   How are calls cached for determinism/offline replay, and how is MXN cost computed for a
   local model?
4. How will judges deliver unseen estates (a `.db` path? a generator + seed?). The material
   says "at a path given at run time" but not the file format.
5. What exactly defines `threshold_splitting` and `revenue_inflation` in our generator, and
   which `rule_broken` article does each cite? Only `SAT Articulo 69-B` is given as an
   example rule.
6. How to map the real 69-B statuses onto `efos_list.status`: drop `Desvirtuado` /
   `Sentencia Favorable`, or keep them (as likely decoy material)?
7. Criteria for `proven` vs `probable` confidence are not defined in the material.
8. Case-file format (HTML/PDF/Markdown) and diagram technology (e.g. Mermaid, Graphviz)
   that renders offline.
9. Which seeds are tuning vs reporting seeds.
10. Should `CLAUDE.md` / `AGENTS.md` be populated (e.g. pointing to this file)?
11. Is `Dockerfile` (empty) expected for the demo/deployment?

## Current Project Status

As of 2026-09-12:

| Area | Status |
|---|---|
| Challenge material collected | Done (`public/material/`, untracked in git) |
| Project context (`CONTEXT.md`) | Done (this file) |
| SAT 69-B blacklist import + bulk check endpoint | **Done**, tested, documented (commit `377d80b`) |
| Estate generator + ground truth | Not started |
| Detectors (beyond blacklist) | Not started |
| Investigation agent + LLM integration | Not started |
| Challenger / validator stages | Not started |
| Submission JSON + case file renderer | Not started |
| Evaluation harness + Results table | Not started |
| Determinism / offline replay | Not started |
| Demo & pitch | Not started |

Git: branch `main`; 3 commits (`6661852` initial, `5c87846` untrack scripts,
`377d80b` blacklist endpoint). Uncommitted: `TODO.md` (TASK #2 added), `CONTEXT.md`,
`public/`.
