# Private estate-generator evaluation boundary

This directory contains evaluator-only scenario composition, causal truth,
decoy rationale, and provenance. It is deliberately outside `app/`; the public
generator never imports it.

Generate a challenge fixture from the repository root with:

```bash
uv run python -m evaluation.estate_generator.cli \
  --seed 7 \
  --output generated/fixture_7.db \
  --all-five \
  --decoy-count 5 \
  --observation-profile challenge_wide \
  --force
```

Without `--all-five`, the default deterministic mix contains 0–5 schemes and
0–10 decoys. `--scheme-count` and `--decoy-count` override that mix. The five
supported scheme families are phantom vendor, kickback, round-tripping,
threshold splitting, and revenue inflation. Each has an innocent, publicly
explainable counterpart.

The command writes:

- `<output>.db`: the only artifact supplied to the investigator.
- `private/<stem>.truth.json`: scheme labels, entities, evidence IDs, amounts,
  and decoys.
- `private/<stem>.provenance.json`: observation limits, confidence ceilings,
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
