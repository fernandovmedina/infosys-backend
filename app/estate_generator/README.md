# Synthetic estate generator

This package will generate deterministic, offline SQLite estates matching
`public/material/estate_schema.sql`. It is a library and CLI concern, not an
API route: the deployed investigator must be able to consume an estate without
being able to reach generator internals or evaluation data.

## Boundaries

| Area | Responsibility | Must not depend on |
|---|---|---|
| `config.py` | Public, seed-based generation controls | evaluator truth or hidden actor roles |
| `challenge_contract.py` | One read-only path to supplied format material | FastAPI, PostgreSQL, or network access |
| `normal_business.py` | Ordinary events, obligations, documents, and payments | fraud-only rendering paths |
| `scenarios.py` | Event-level scenario interventions and innocent counterparts | direct SQLite row patching |
| `accounting.py` | Exact-cent postings and settlement state | floating-point source-of-truth arithmetic |
| `exporter.py` | Projection into the eight public SQLite tables | evaluator-only provenance |
| `checks.py` | Public-estate invariants and leakage smoke checks | private causal facts as evidence |
| `cli.py` | Reproducible offline generation command | FastAPI application startup |

Only `config.py` and `challenge_contract.py` exist in this structural change.
The remaining modules will be added with their tests as generator behavior is
implemented. Listing the boundaries now establishes ownership without shipping
placeholder logic or a command that appears functional but generates no estate.

## Artifact separation

The generator will write public SQLite estates below `generated/`, which is
ignored by Git. Private evaluation sidecars are owned by
`evaluation/estate_generator/`; the application package must never import them.
The investigator receives the public database only.

The challenge materials under `public/material/` are format specifications.
They are not generated output and must remain unchanged.
