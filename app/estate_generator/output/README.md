# Synthetic estate collection

This directory is a self-contained collection of fictional company estates for
fraud-detection development and evaluation. Each estate is a timestamped
directory containing the same eight public data tables and, for evaluation
fixtures, a private answer key.

## Collection layout

```text
output/
├── tuning/
│   └── <category>/<variant>/seed<seed>_<timestamp>/
└── report/
    └── <category>/<variant>/seed<seed>_<timestamp>/
```

`tuning` contains cases that may be used while developing detection rules.
`report` contains held-out cases intended for final, unbiased measurement.
Cases in the two splits use different seeds. The numeric seed identifies the
deterministic estate contents; the timestamp makes each directory unique.

## Categories and variants

```text
clean/{without_decoys,with_decoys}/
isolated/<scheme>/{without_decoys,with_decoys}/
mixed/{seed_driven,three_schemes}/{without_decoys,with_decoys}/
all_five/{without_decoys,with_decoys}/
```

| Category | Planted schemes | Meaning |
|---|---:|---|
| `clean` | 0 | Ordinary activity only |
| `isolated/<scheme>` | 1 named scheme | Controlled single-scheme case |
| `mixed/seed_driven` | Deterministic 0–5 | Variable multi-scheme case |
| `mixed/three_schemes` | Exactly 3 | Controlled multi-scheme case |
| `all_five` | All 5 | Maximum scheme density |

Each category has two variants:

| Variant | Decoys | Interpretation |
|---|---:|---|
| `without_decoys` | 0 | Schemes, if any, are not accompanied by deliberate lookalikes |
| `with_decoys` | 5 | Includes suspicious-looking but legitimate patterns |

Decoys are not additional fraud. They are complete business patterns with an
innocent explanation, designed to measure false accusations. The five scheme
families are `phantom_vendor`, `kickback`, `round_tripping`,
`threshold_splitting`, and `revenue_inflation`.

## Public estate files

Every estate directory contains these UTF-8 CSV files:

```text
vendors.csv          Supplier identity, tax ID, address, and bank account
invoices.csv         CFDI-like purchase and sales invoices
ledger.csv           Balanced general-ledger entries
bank_txns.csv        Inter-account transfers and settlements
purchase_orders.csv  Purchase requests, approvals, and amounts
contracts.csv        Vendor contracts and committed values
employees.csv        Employee identity, role, and bank account
efos_list.csv        EFOS/SAT screening context
```

The files use the column names and types defined by the estate schema. Dates
are ISO 8601 strings, amounts have two decimal places, and CLABEs are kept as
18-digit text values so leading zeroes are preserved.

## Private evaluation sidecars

Evaluation estates also contain a `private/` directory:

```text
private/
├── *.ground_truth.json
└── *.provenance.json
```

`ground_truth.json` identifies planted schemes, entities, supporting evidence,
amounts, and decoys. `provenance.json` records observation limits, visible and
hidden evidence, confidence ceilings, and amount interpretation.

The private sidecars are evaluation metadata, not public estate data. They
must remain separate from any investigator or production detector input.

## Matrix manifest

At the collection root, `matrix_manifest.json` indexes generated cases by
split, case ID, seed, category, variant, and private-sidecar paths. It is useful
for locating cases without opening their data files.
