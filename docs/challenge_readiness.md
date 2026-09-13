# Challenge readiness and deferred work

This document records the current delivery decisions for the Forensic Auditor
challenge. It distinguishes implemented safeguards from intentional backlog so
the demo never overstates what the system does.

## Current judge-facing flow

Judges upload the eight CSV estate tables through the frontend. The backend
validates and analyzes that upload; it is not relying on a hardcoded estate
path. The strict fraud endpoint requires all eight official table names and
headers, while the run-upload flow retains its existing diagnostics behavior.

Every published finding passes the supplied format validator. In addition, the
engine now performs semantic entity coverage: every RFC/company must have a
role-bearing exhibit linked by exact RFC or CLABE; every employee must have its
employee record and a separately cited payment, approval, or request. A
candidate without that support becomes a documented declined lead rather than
an accusation.

## Evaluation and ground-truth boundary

Private answer keys and scoring live only under `evaluation/`; production
`app/` code must never import them. The deployable investigator receives only
the public CSV directory. Evaluation output uses separate `public/` and
`private/` roots, never a `private/` sibling inside the investigator input.

Run the evaluator with:

```bash
uv run python -m evaluation.fraud_evaluator.cli --mode heldout \
  --output-root generated/evaluation/<frozen-engine-version>
```

Held-out mode uses exactly the six reserved cases in
`evaluation/estate_generator/heldout_manifest.json`. Tuning mode requires a
matrix manifest and rejects those reserved seed IDs:

```bash
uv run python -m evaluation.fraud_evaluator.cli --mode tuning \
  --manifest generated/matrix/matrix_manifest.json \
  --output-root generated/evaluation/tuning-run
```

For iterative diagnostics, tuning mode also supports `--start-at` and
`--max-cases`; held-out mode intentionally rejects both switches.

The evaluator invokes the production fraud engine with public CSV paths only.
It matches findings to planted schemes one-to-one when the scheme type and at
least one exact entity ID match. A decoy counts as accused only if its exact
entity ID appears in a published finding. It writes the official Results-table
columns and recomputes totals from aggregate counts. It also writes
`false_positive_diagnostics.csv` and `false_positive_summary.csv`; use these
only on tuning fixtures to select targeted exculpatory checks before freezing
the engine for held-out reporting.

Private fixtures keep every decoy entity disjoint from every planted-scheme
entity in the same estate. In particular, a normal cancelled-sale decoy is not
generated when the audited company is also planted with revenue inflation; it
would otherwise make entity-level false-accusation scoring ambiguous.

## Deferred backlog

The following are intentionally not part of the current implementation:

- Final frontend case-file presentation and correction of legacy HTML export
  wording.
- Immutable audit dossier and constrained local/offline LLM Q&A for judge
  questions.
- Adversarial reviewer/challenger stage.
- Decoy-driven threshold calibration and other false-positive reduction work.
- Independent adversarial benchmark fixtures and stricter evaluation metrics.
  The current generator/engine alignment is a self-consistency check, not
  evidence of real-world robustness. Add hard decoys with multiple suspicious
  signals, noisy/partial evidence, near-threshold values, and stricter
  entity/evidence/amount matching before making quality claims.
- Supported offline replay CLI and immutable artifact caching for stable
  wall-clock metadata.
- Production hardening: durable jobs/recovery, concurrency control, data
  retention/security, enterprise identity, observability, deployment image,
  and detector-degradation alerts.
