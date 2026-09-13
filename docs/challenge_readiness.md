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

The evaluator invokes the production fraud engine with public CSV paths only.
It matches findings to planted schemes one-to-one when the scheme type and at
least one exact entity ID match. A decoy counts as accused only if its exact
entity ID appears in a published finding. It writes the official Results-table
columns and recomputes totals from aggregate counts.

## Deferred backlog

The following are intentionally not part of the current implementation:

- Final frontend case-file presentation and correction of legacy HTML export
  wording.
- Immutable audit dossier and constrained local/offline LLM Q&A for judge
  questions.
- Adversarial reviewer/challenger stage.
- Decoy-driven threshold calibration and other false-positive reduction work.
- Supported offline replay CLI and immutable artifact caching for stable
  wall-clock metadata.
- Production hardening: durable jobs/recovery, concurrency control, data
  retention/security, enterprise identity, observability, deployment image,
  and detector-degradation alerts.
