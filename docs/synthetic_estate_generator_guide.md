# Synthetic estate generator guide

This guide is the operational reference for generating training, tuning, and
evaluation fixtures for the Forensic Auditor challenge.

The generator is offline and deterministic. It creates fictional records that
match the judges' supplied `public/material/estate_schema.sql`. It does not
query SAT, PostgreSQL, the network, or the API. It is a synthetic fixture
generator, not a calibrated model of a real company.

## 1. Prerequisites

Run commands from the backend repository root:

```bash
cd /home/ferlr/Code/hackmty/infosys-backend
uv sync --all-groups
```

The project requires Python 3.14 and uses `uv` for the environment. The
`estate-generate` command is installed by the project package; rerun `uv sync`
after pulling changes to `pyproject.toml` or `uv.lock`.

## 2. Public normal-business estate

Generate an estate containing ordinary commercial activity:

```bash
uv run estate-generate --seed 7
```

The command creates a new directory below:

```text
app/estate_generator/output/seed7_<YYYYMMDD>_<HHMMSS>/
```

CSV is the default output. The directory contains one file for every required
schema table:

```text
vendors.csv
invoices.csv
ledger.csv
bank_txns.csv
purchase_orders.csv
contracts.csv
employees.csv
efos_list.csv
```

Amounts are written with two decimal places. CSV files are UTF-8 and include a
header matching the SQLite schema column order.

To produce only a SQLite database in the run directory:

```bash
uv run estate-generate --seed 7 --sqlite
```

This creates:

```text
app/estate_generator/output/seed7_<YYYYMMDD>_<HHMMSS>/estate.db
```

Every invocation creates a new timestamped directory. If the same seed is run
twice within one second, a numeric suffix is added to avoid overwriting the
first run.

### Public CLI options

```text
--seed INTEGER                 Required reproducibility seed
--sqlite                       Write only estate.db instead of CSV files
--start-date YYYY-MM-DD        Inclusive observation-window start
--end-date YYYY-MM-DD          Inclusive observation-window end
--vendor-count INTEGER         Number of ordinary vendors (default 50)
--employee-count INTEGER       Number of employees (default 10)
--normal-event-count INTEGER   Number of ordinary invoices/events (default 360)
--observation-profile PROFILE  challenge_wide or company_only
```

Example compact estate:

```bash
uv run estate-generate \
  --seed 101 \
  --vendor-count 12 \
  --employee-count 5 \
  --normal-event-count 60
```

The public command never plants fraud scenarios. It is useful as a clean
baseline or as the normal-business substrate for private fixtures.

## 3. Private scenario fixture

The private command adds scenario interventions, matched innocent decoys, and
the evaluator-only answer key. It is intentionally not installed as a public
project script:

```bash
uv run python -m evaluation.estate_generator.cli \
  --seed 7 \
  --all-five \
  --decoy-count 5
```

It uses the same timestamped output root and creates:

```text
app/estate_generator/output/seed7_<YYYYMMDD>_<HHMMSS>/
├── vendors.csv ... efos_list.csv
└── private/
    ├── seed7_<timestamp>.ground_truth.json
    └── seed7_<timestamp>.provenance.json
```

With `--sqlite`, the public directory contains only `estate.db` instead of the
eight CSV files; the private sidecars are still written for evaluation.

## 4. Selecting fraud schemes

The five supported scheme types are:

```text
phantom_vendor
kickback
round_tripping
threshold_splitting
revenue_inflation
```

Generate all five:

```bash
uv run python -m evaluation.estate_generator.cli \
  --seed 7 --all-five --decoy-count 5
```

Select one named scheme:

```bash
uv run python -m evaluation.estate_generator.cli \
  --seed 7 --scheme-type kickback --decoy-count 0
```

Select several named schemes, preserving the order supplied:

```bash
uv run python -m evaluation.estate_generator.cli \
  --seed 7 \
  --schemes kickback,round_tripping \
  --decoy-count 2
```

The equivalent repeatable form is:

```bash
--scheme-type kickback --scheme-type round_tripping
```

Use a variable seed-determined mix with `--scheme-count`:

```bash
uv run python -m evaluation.estate_generator.cli \
  --seed 7 --scheme-count 1 --decoy-count 3
```

Create a normal-only private fixture:

```bash
uv run python -m evaluation.estate_generator.cli \
  --seed 7 --scheme-count 0 --decoy-count 0
```

Selection modes are mutually exclusive. Do not combine `--all-five`,
`--scheme-count`, `--scheme-type`, or `--schemes`. Unknown and duplicate names
are rejected.

## 5. Observation profiles

`challenge_wide` exports all simulated bank transactions, including
counterparty-to-counterparty legs needed to inspect complete money trails.

`company_only` exports only transfers where the company account is the sender
or recipient. This intentionally tests incomplete evidence:

- Kickback uses a visible vendor/approver shared-account conflict and is capped
  at `probable`; the hidden vendor-to-employee return is not exported.
- Round-tripping retains the company payment and return but hides the
  intermediary-to-vendor leg, so it is capped at `probable`.
- Other scenarios retain their public documentary evidence.

Choose a profile explicitly:

```bash
uv run python -m evaluation.estate_generator.cli \
  --seed 7 --all-five --observation-profile company_only
```

## 6. Ground truth and provenance

The public CSV files or `estate.db` are the only artifacts supplied to an
investigator. The private sidecars must never be placed in that workspace.

`*.ground_truth.json` follows the judges' `ground_truth_schema.json` shape. It
contains the seed/company, planted schemes, evidence IDs, monetary basis, and
innocent decoys. The explanations are deterministic evaluator metadata
authored together with each decoy's public event path. They are not LLM-
generated and are not copied from real taxpayers. The corresponding public
documents and accounting rows are generated through the same normal-business
APIs and are tested for consistency.

`*.provenance.json` records observation profile, confidence ceilings, amount
bases, visible/hidden transaction IDs, and decoy explanations. It is for the
evaluation harness, not for the investigator.

## 7. Programmatic use

The public library can generate and validate an in-memory estate:

```python
from app.estate_generator import EstateGeneratorConfig
from app.estate_generator.generator import generate_estate
from app.estate_generator.output import export_run

config = EstateGeneratorConfig(seed=7, normal_event_count=60)
estate = generate_estate(config)
run_directory, artifacts = export_run(
    estate,
    seed=config.seed,
    observation_profile=config.observation_profile,
)
print(run_directory, artifacts)
```

For legacy integrations that already own a destination path,
`generate_sqlite_estate()` and `export_sqlite()` remain available. The CLI and
recommended workflow use timestamped run directories instead.

Private scenario composition is available only from the evaluator boundary:

```python
from evaluation.estate_generator.scenarios import build_scenario_run

run = build_scenario_run(
    config,
    scheme_types=("kickback", "round_tripping"),
    decoy_count=2,
)
```

## 8. Validation and tests

The generator validates before export:

- exactly the eight supplied tables
- unique IDs and resolvable RFC/employee/CLABE links
- `subtotal + IVA = total`
- balanced journal events
- non-negative payable/receivable state
- valid 18-digit CLABE checksums
- invoice, ledger, and payment chronology
- chronological account funding
- observation-profile filtering

Run the focused generator suite:

```bash
uv run pytest -q --confcutdir=tests/test_estate_generator tests/test_estate_generator
```

Run static checks:

```bash
uv run ruff check app/estate_generator evaluation/estate_generator tests/test_estate_generator
uv run mypy app/estate_generator evaluation/estate_generator
```

The supplied submission-format validator can check a finding file against a
generated SQLite estate:

```bash
python public/material/validate_format.py \
  --submission submission.json \
  --estate path/to/estate.db
```

The validator checks format and exhibit reconciliation only; it does not judge
whether a finding is substantively correct.

## 9. Reproducibility and held-out evaluation

The same seed and configuration produce byte-identical public artifacts and
sidecars. Use different seeds for training and tuning. The reserved private
manifest is:

```text
evaluation/estate_generator/heldout_manifest.json
```

Do not generate or inspect its private sidecars while tuning prompts,
thresholds, or investigator logic. Held-out results should be reported only
after the detector is frozen.

## 10. Deployment and safety

The `app/estate_generator` package contains only public generation logic. The
`evaluation/estate_generator` package contains answer-key logic and must not be
included in the investigator image or tool allowlist. Exclude both
`evaluation/` and any `private/` output directories from the investigator's
filesystem. Keeping them in one development repository is convenient but is
not a security boundary.

All records are fictional. The generator does not use live SAT downloads or
make allegations about real taxpayers. EFOS status is screening context only,
never proof of fraud or clearance.

## 11. Troubleshooting

### `uv run estate-generate: No such file or directory`

Synchronize the project so the package entry point is installed:

```bash
uv sync --all-groups
uv run estate-generate --seed 7
```

The fallback that bypasses the installed entry point is:

```bash
uv run python -m app.estate_generator.cli --seed 7
```

### Existing output files

The CLI does not overwrite a prior run. It creates a new timestamped directory
on every invocation, adding a suffix if necessary.

### Full repository tests wait for PostgreSQL

The backend's global test configuration probes a seeded PostgreSQL instance.
The generator tests are independent and can be run with the focused command in
section 8. Start the backend's Docker PostgreSQL environment only when running
database-dependent SAT tests.
