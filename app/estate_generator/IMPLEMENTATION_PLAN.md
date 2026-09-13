# Agentic implementation plan

This is the active task contract for the synthetic estate generator. It turns
the research design into small reviewable changes and keeps public generator
code separate from private evaluation material.

**Implementation status:** Milestones A and B and the Milestone C fixture
harness are implemented. Focused tests cover deterministic schema projection,
accounting and chronology invariants, both observation profiles, all five
scenario families, matched decoys, private sidecars, and the supplied format
validator. Six seeds are reserved in the private held-out manifest. Empirical
calibration and held-out benchmark results remain future evaluation work; they
are not claimed by this implementation.

## Team roles

| Role | Owner | Authority |
|---|---|---|
| Builder | Generator implementation agent | Creates generator modules and focused tests within `app/estate_generator/` and `tests/test_estate_generator/` |
| Quality reviewer | Independent read-only agent | Audits schema, determinism, accounting, public evidence, and leakage; proposes failing tests/issues |
| Domain reviewer | Independent read-only agent | Audits business plausibility, evidence observability, decoys, SAT semantics, and shortcut risks |
| Orchestrator | Root agent | Owns contracts, sequencing, cross-boundary changes, integration, and final verification |

Reviewers do not edit builder-owned files. The builder does not modify
`evaluation/estate_generator/`. The orchestrator resolves disagreements before
the next task starts.

## Milestone A — normal-business core

**Builder-owned files:** `models.py`, `accounting.py`, `normal_business.py`,
`exporter.py`, `generator.py`, `checks.py`, `cli.py`, and focused tests.

1. Introduce typed internal records and an exact-cent money representation.
2. Generate one fictional company, employees, vendors, contracts, and POs.
3. Generate normal one-off and recurring purchases, invoices, ledger postings,
   complete/partial settlements, customer credit sales, and cancellation/reversal
   paths.
4. Project records through the supplied `estate_schema.sql` into standalone
   SQLite, with deterministic IDs and insertion order.
5. Provide an offline `estate-generate --seed …` CLI that writes timestamped
   CSV run folders, with an optional SQLite-only mode.

**Milestone A gates**

- Same seed/configuration yields logically identical canonical table contents.
- The exported database contains exactly the eight specified tables.
- Implied public links resolve: vendor RFCs, optional ledger invoice UUIDs,
  CLABEs, and employee names used as approvers/requesters.
- Every invoice satisfies `subtotal + iva = total` in centavos; every internal
  journal event balances; payment settlement never produces an unexplained
  negative payable/receivable.
- Causal dates are ordered except where an explicit cancellation/reversal
  event documents the variation.
- Generation runs without FastAPI, PostgreSQL, SAT queries, network access, or
  evaluator imports.

## Milestone B — scenarios and innocent counterparts

Add scenarios only through the normal-business event functions, never direct
SQL inserts. Each scenario must define an amount basis, visible evidence
bundle, and one matched innocent counterpart.

| Required type | First evidence-complete mechanism | Public counterexample |
|---|---|---|
| `phantom_vendor` | Paid unsupported invoice plus exact employee/vendor account linkage | Sparse new vendor with contract, PO, invoice, and payment |
| `kickback` | Paid vendor returns a proportion to PO approver account | Documented reimbursement or vendor refund to company |
| `round_tripping` | Time-respecting return chain to company account without reversal support | Refund connected to corrected/cancelled invoice and ledger reversal |
| `threshold_splitting` | Grouped near-limit POs for one visible aggregated scope | Independent recurring work packages with distinct public scope |
| `revenue_inflation` | Cancelled invoice whose revenue/AR/VAT postings remain unreversed | Cancelled invoice with complete reversing entries |

The challenge-profile observation model may show third-party transfers where
needed for kickback and cycle cases. Any such model must be documented; it is
not a universal claim about real company-bank visibility.

**Milestone B gates**

- Each scenario and counterexample yields at least three public, resolvable
  exhibits, including an amount-bearing record.
- `peso_amount` has a documented basis: principal is distinct from gross cycle
  volume; kickback benefit is distinct from vendor invoice value.
- A scenario is not identifiable from identifier shape, text template, amount
  support, row order, timestamp precision, channel, or EFOS membership.
- A zero-scheme estate, variable scheme counts, and a shared-entity case work
  after standalone cases pass.
- An innocent explanation is reconstructible from public rows, not private
  evaluator facts.

## Milestone C — private evaluation and tuning fixtures

The orchestrator implements the evaluator harness in the private boundary.
It records scenario attribution, expected evidence, decoy rationale, held-out
seed manifests, and distinct monetary measures. Public application code never
imports it.

The evaluator then runs the supplied format validator against known-valid
findings and estates. The final held-out suite uses at least five seeds not
used to tune prompts, thresholds, scenario parameters, or investigator logic.

**Status:** private fixture generation now exists under
`evaluation/estate_generator/`, including public/private sidecar separation,
both observation profiles, and supplied-validator fixture checks. It remains a
synthetic development tool; a six-seed manifest is frozen, while empirical
calibration and held-out reporting are still future work.

## Review checkpoints

1. **Before Milestone A merge:** quality reviewer checks the schema/output and
   accounting test plan; domain reviewer checks normal process variation.
2. **Before each scenario family:** domain reviewer confirms evidence is
   observable under the public schema; quality reviewer specifies invariants
   and counterfactual tests.
3. **Before Milestone B merge:** both reviewers inspect actual generated
   SQLite examples for leakage and unsupported claims.
4. **Before tuning:** orchestrator freezes the public/private boundary and
   held-out manifests.

## SAT policy

No live SAT download or real taxpayer allegation is part of generated estates.
A tiny fictional `efos_list` fixture may model `presunto` and `definitivo` as
screening context. `presunto` is never final proof; absence from the list is
never clearance; EFOS status is never a standalone fraud label.
