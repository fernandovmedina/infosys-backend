# Estate generator collaboration contract

This package produces the public SQLite estate consumed by the Forensic
Auditor. It must remain independent of FastAPI, PostgreSQL, live SAT lookups,
and network access.

## Ownership

The assigned **builder** owns generator implementation and its focused tests:

- `normal_business.py`, `accounting.py`, `scenarios.py`, `exporter.py`, and
  `cli.py`;
- `tests/test_estate_generator/` tests that exercise those modules.

The **orchestrator** owns package boundaries, configuration, challenge-contract
access, repository integration, and final verification. Reviewers are
read-only: they report evidence-backed issues and proposed tests rather than
editing implementation files.

Only change a file outside the owned list after explicitly coordinating with
the orchestrator. Do not restructure the SAT feature while working on the
generator.

## Public-versus-private boundary

- `app/estate_generator/` may contain only public generation controls and code
  needed to render a public estate.
- Private causal attribution, planted-scheme answers, held-out manifests, and
  evaluator expectations belong under `evaluation/estate_generator/` or a
  generated private sidecar, never in application imports.
- The deployed investigator must receive only the public SQLite estate. Do not
  make public record values, IDs, ordering, or wording encode scenario labels.

## Implementation invariants

1. The authoritative public contract is `public/material/estate_schema.sql`.
   Read it through `challenge_contract.py`; do not silently maintain a diverging
   SQL copy.
2. Use a seed-local deterministic random source. The same configuration must
   make an identical canonical estate offline.
3. Store money as integer centavos or exact decimals internally. Never use
   binary floating point as the source of truth; convert only when exporting
   SQLite `REAL` fields.
4. One business event is the source for all of its invoice, ledger, and payment
   projections. Do not patch arbitrary rows after rendering.
5. Every normal and scenario event has explicit dates, participants, and
   balances. Accounting entries balance at the event level.
6. Every generated estate must include normal activity. A suspicious entity may
   also have legitimate business activity.
7. Do not assert fraud from an EFOS/69-B match alone. SAT status is reference
   context, not a complete causal label.

## First implementation slice

Build only enough to establish a sound vertical slice:

- normal vendors, employees, contracts, POs, invoices, ledger postings, and
  full/partial payments;
- exact public SQLite export;
- deterministic CLI and focused unit/integration tests.

Only after this slice passes its checks may scenario work begin: implement all
five required scheme families as event-level interventions, each with a
public-record-supported innocent counterpart. The private evaluator harness,
broad decoy library, and optional empirical calibration follow that scenario
milestone. Do not substitute row count or model complexity for these invariants.

## Definition of done for a change

- New behavior has focused tests that do not require PostgreSQL.
- Tests verify both public records and relevant invariants.
- Generated artifacts are written only below `generated/` and remain ignored.
- No code under `app/estate_generator/` imports `evaluation`.
- Run the available formatting, type, and test commands; report unavailable
  tools accurately instead of claiming they ran.
