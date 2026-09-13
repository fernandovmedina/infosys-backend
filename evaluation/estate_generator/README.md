# Private estate-generator evaluation boundary

This directory contains evaluator-only scenario composition, causal truth,
decoy rationale, and provenance. It is deliberately outside `app/`; the public
generator never imports it.

Generate a challenge fixture from the repository root with:

```bash
uv run python -m evaluation.estate_generator.cli \
  --seed 7 \
  --all-five \
  --decoy-count 5 \
  --observation-profile challenge_wide
```

For a ready-made matrix covering a clean baseline, clean data with decoys, each
scheme in isolation, mixed scheme counts, and all five schemes together, run:

```bash
uv run python -m evaluation.estate_generator.generate_matrix
```

Generate adversarial *tuning* fixtures—innocent lookalikes with multiple
suspicious signals, partial procurement evidence, and near-threshold purchase
patterns—with:

```bash
uv run python -m evaluation.estate_generator.generate_adversarial_matrix \
  --output-root generated/adversarial-tuning \
  --replicates 10 \
  --include-fraud
```

Evaluate that manifest with `evaluation.fraud_evaluator.cli --mode tuning`.
With `--include-fraud`, alternating cases contain all five planted schemes so
the same run measures difficult-case recall and false accusations. The partial
procurement decoy remains an expected lead, not an accusation. These fixtures
are for diagnosing and calibrating only. Freeze a separate seed range before
reporting independent adversarial results.

`adversarial_heldout_manifest.json` reserves that separate seed range. Do not
generate or inspect it during tuning; evaluate it only with:

```bash
uv run python -m evaluation.fraud_evaluator.cli --mode heldout \
  --heldout-manifest evaluation/estate_generator/adversarial_heldout_manifest.json \
  --output-root generated/evaluation/adversarial-heldout
```

`adversarial_mixed_heldout_manifest.json` similarly reserves mixed fraud and
lookalike cases for one final strict-recall and false-accusation measurement.

The implementation is a configurable Python CLI:

```bash
uv run python -m evaluation.estate_generator.generate_matrix \
  --replicates 5 \
  --report-replicates 1 \
  --first-seed 2001
```

The script uses distinct seed ranges for each case and prints the label and
output path for every fixture. Set `SKIP_UV_SYNC=1` when the environment is
already synchronized. It writes CSV estates and private sidecars under a
discoverable category tree:

```text
tuning/
└── <category>/<variant>/seed<seed>_<timestamp>/
report/
└── <category>/<variant>/seed<seed>_<timestamp>/
```

The default is five tuning replicas and one report replica per category/variant.
Use `--replicates` and `--report-replicates` to change those counts. Every case
gets a globally unique seed, avoiding collisions in seed-keyed evaluators.

Without `--all-five`, the default deterministic mix contains 0–5 schemes and
0–10 decoys. `--scheme-count` and `--decoy-count` override that mix. To choose
specific families, use `--scheme-type kickback --scheme-type round_tripping`
or the equivalent `--schemes kickback,round_tripping`. These selection forms
are mutually exclusive with `--all-five` and `--scheme-count`. The five
supported scheme families are phantom vendor, kickback, round-tripping,
threshold splitting, and revenue inflation. Each has an innocent, publicly
explainable counterpart.

The command creates `app/estate_generator/output/seed7_<YYYYMMDD>_<HHMMSS>/`
and writes:

- CSV mode (default): one CSV per public schema table; this is the only public
  artifact supplied to the investigator.
- `--sqlite`: only `estate.db` is written as the public artifact.
- `private/<run-name>.ground_truth.json`: scheme labels, entities, evidence IDs, amounts,
  and decoys.
- `private/<run-name>.provenance.json`: observation limits, confidence ceilings,
  amount bases, and visible/hidden evidence attribution.

The private command is intentionally not installed as a project script.
Repository layout alone is not a security boundary: the investigator
workspace/container must exclude this directory and all `private/` sidecars.

Fixtures are deterministic, fictional, and offline. They are designed for
hackathon training and regression testing; they are not calibrated estimates
of real fraud prevalence or taxpayer behavior. Freeze a held-out seed set
before tuning and do not inspect its private sidecars during development.

[`heldout_manifest.json`](heldout_manifest.json) reserves six seeds—three per
observation profile—for the final evaluation. Do not generate or inspect their
private sidecars during prompt or detector tuning.

See the repository's [complete usage guide](../../docs/synthetic_estate_generator_guide.md)
for public CSV/SQLite output, explicit scheme selection, validation, and
deployment instructions.
