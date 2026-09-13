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
./evaluation/estate_generator/generate.sh
```

The script uses distinct seed ranges for each case and prints the label and
output path for every fixture. Set `SKIP_UV_SYNC=1` when the environment is
already synchronized. It writes CSV estates and private sidecars under a
discoverable category tree:

```text
app/estate_generator/output/fixture_matrix/
├── clean/no_schemes/
├── clean/with_decoys/
├── isolated/{phantom_vendor,kickback,round_tripping,
│             threshold_splitting,revenue_inflation}/
├── mixed/{seed_driven,three_schemes_with_decoys}/
└── all_five/with_decoys/
```

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
