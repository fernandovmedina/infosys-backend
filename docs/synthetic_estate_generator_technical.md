# Synthetic Data Generator (SDG): technical and study-case documentation

## 1. Purpose and scope

The Synthetic Data Generator (SDG) creates fictional but internally coherent
financial estates for the Forensic Auditor project. An estate is the collection
of records an investigator receives about one audited company: suppliers,
employees, contracts, purchase orders, invoices, accounting entries, bank
transfers, and EFOS screening context.

The SDG is designed for a hackathon, so its primary goals are reproducibility,
causal ground truth, forensic traceability, and fast iteration. It is not a
statistical model of the Mexican economy, a generator of real taxpayer data, or
a claim about the prevalence of any fraud type.

The generator has an explicit public/private boundary:

```text
app/estate_generator/
    public normal-business model, validation, and exporters

evaluation/estate_generator/
    private fraud interventions, decoys, ground truth, and provenance
```

The public layer never imports scenario labels or answer keys. The evaluation
layer composes scenarios by calling public business-event APIs, which keeps the
fraud records valid members of the same accounting system as ordinary records.

## 2. Study case represented by an estate

The simulated case is a six-month forensic review of one Mexican company:

- Observation window: 1 January–30 June 2026 by default.
- The company has a fictional RFC and a company CLABE.
- Employees participate in procurement, finance, operations, internal control,
  and management roles.
- The company buys maintenance, consulting, logistics, supplies, and technology
  services from vendors.
- It records CFDI-like invoices, purchase orders, contracts, ledger postings,
  and settlement transfers.
- It also records two ordinary credit sales and their customer receipts.
- A small amount of EFOS/SAT screening context is present so blacklist status is
  a signal to investigate, not an automatic finding.

The intended forensic question is:

> Which apparent irregularities represent one of the planted fraud schemes,
> which are innocent business explanations, and how much money can be supported
> by the available evidence?

The public estate deliberately contains enough routine activity to create
linkage and noise. A detector must join records across tables and time rather
than match a single keyword.

## 3. Configuration and reproducibility

`EstateGeneratorConfig` contains public controls:

| Parameter | Default | Effect |
|---|---:|---|
| `seed` | required | Determines all deterministic choices and IDs |
| `start_date` | `2026-01-01` | Inclusive observation start |
| `end_date` | `2026-06-30` | Inclusive observation end |
| `vendor_count` | 50 | Ordinary vendors before scenario additions |
| `employee_count` | 10 | Employees and employee bank accounts |
| `normal_event_count` | 360 | Normal invoice/event volume |
| `observation_profile` | `challenge_wide` | Which transfers are visible publicly |

The generator uses seeded Python PRNG instances. The same configuration and
seed produce the same in-memory estate and the same causal relationships. The
matrix generator assigns distinct seeds across categories, variants, and
tuning/report splits to prevent seed-keyed evaluator collisions.

Amounts remain integer centavos inside the model. Decimal peso strings are
created only at the CSV/SQLite boundary, avoiding floating-point arithmetic for
invoice totals, VAT, balances, and transfer amounts.

## 4. Normal-business generation pipeline

The public `EstateEventBuilder` is the single path for creating ordinary and
scenario records. It registers accounts, updates balances, creates linked
records, and enforces event-date and accounting rules.

### 4.1 Company, employees, and accounts

The builder creates one company account, then employees with deterministic IDs,
roles, hire dates, and valid 18-digit CLABEs. Every account is registered with a
holder kind (`company`, `employee`, `vendor`, `customer`, or `counterparty`) and
an owner ID. This internal ownership map allows the validator to reject
transfers involving unknown or malformed accounts.

### 4.2 Ordinary vendors

Vendors cycle through five categories: maintenance, consulting, logistics,
supplies, and technology. Each receives a fictional RFC, legal name, address,
email, registration date, and bank CLABE. Vendor accounts are registered before
any payment is recorded.

### 4.3 Recurring purchases

The first three vendors receive monthly recurring purchases throughout the
observation window. Each recurring vendor has a contract whose committed value
equals the monthly amount multiplied by the number of months. Each month creates
a purchase order, invoice, balanced ledger posting, and settlement transfer.
This provides legitimate repeated activity and contract-to-invoice joins.

### 4.4 One-off purchases

The remaining normal-event budget is distributed across the other vendors at
deterministic dates and amounts. Each ordinary purchase normally creates:

1. A purchase order with requester and approver.
2. A vendor-issued invoice received by the company.
3. Three balanced ledger lines (expense, VAT, and accounts payable).
4. A settlement posting and bank transfer.

The exact table row counts are therefore related but not identical. For example,
the default 360-event estate has 360 invoices, roughly 358 purchase orders,
hundreds of bank transactions, and roughly five ledger rows per invoice/event.

### 4.5 Cancellation and ordinary sales

One purchase invoice is cancelled and fully reversed, providing a legitimate
negative/control example. Two company credit-sale invoices are issued and
settled by a customer. These records ensure that cancellation, reversal, and
inbound receipt logic are not inherently suspicious.

## 5. Accounting and integrity model

Every invoice satisfies:

```text
total = subtotal + IVA
IVA = 16% of subtotal (centavo-rounded)
```

Each ledger event is balanced: total debits equal total credits. Payable and
receivable balances cannot become negative. Bank transfers require registered
accounts, valid CLABE checksums, positive amounts, and sufficient chronological
funds. Dates cannot place a posting or payment before its invoice.

The public validator also checks uniqueness and referential integrity for RFCs,
employee IDs, invoice UUIDs, purchase orders, contracts, ledger entries, bank
transactions, and cross-table foreign-key-like references.

These checks are important for forensic realism: an investigator should be
challenged by suspicious relationships, not by corrupted fixture data.

## 6. Fraud study interventions

The private scenario builder first creates a complete normal estate, then adds
one or more interventions through the same event APIs. Scenario attribution is
never stored in public tables.

### Phantom vendor

A new consulting vendor is created with an EFOS `presunto` record and a bank
account shared with an employee. It receives an invoice for services but no
purchase order, creating a combination of weak documentation, EFOS context, and
account ownership linkage.

The planted evidence is the vendor, invoice, employee account relationship, and
related ledger/payment records. The detector should distinguish this from a
new-but-documented vendor.

### Kickback

A maintenance vendor receives a company payment, and approximately ten percent
returns from the vendor to the approving employee. The employee is both
requester and approver, adding a control conflict.

Under `challenge_wide`, the return transfer is visible. Under `company_only`,
the vendor account is projected to the employee account so the external return
transfer is not visible; the remaining signal is the shared account and
invoice/control pattern. The provenance file records this confidence ceiling.

### Round-tripping

A company payment goes from the vendor to an intermediary account and then back
to the company, with a small deduction on the return. The principal invoice
payment, both transfer legs, timing, and references form the money trail.

The reported scheme amount is the principal paid, not the sum of every repeated
appearance of that money.

### Threshold splitting

Three invoices for one vendor are issued close together, each near but below an
approval threshold. They share a consolidated contract and business scope, and
the same employee requests and approves them. The planted pattern is the
aggregate obligation and the avoidance of joint approval.

This tests aggregation over time and across documents rather than single-
invoice threshold checks.

### Revenue inflation

Three company sales are invoiced on credit and cancelled without the normal
reversal of revenue, VAT, and receivables. The apparent revenue remains in the
ledger while the invoices are cancelled, creating unsupported gross exposure.

This scenario is intentionally different from the ordinary cancelled sale,
which has a complete reversal.

## 7. Decoys and adversarial calibration

Decoys are not planted fraud. They are realistic patterns that resemble a
scheme but have a documented innocent explanation. They are stored separately
from `schemes` in ground truth so false accusations can be scored.

Standard decoy families include a new vendor with an EFOS signal but complete
documentation, a vendor-to-company refund rather than a vendor-to-employee
benefit, a cancelled invoice with a visible reversal, near-threshold purchases
backed by independent contracts, and cancelled revenue with complete reversal.

The adversarial matrix adds harder innocent cases that intentionally satisfy
multiple suspicious rules: a recent presumed-EFOS vendor with noisy but complete
documentation; independent near-threshold obligations sharing an approver; and
an urgent service with valid invoice/payment but no available PO attachment.
These fixtures are calibration data for false-positive behavior and should not
be mixed into a final held-out report set unless explicitly intended.

## 8. Observation profiles

The same causal estate can be exported under two observation profiles:

- `challenge_wide`: all registered bank transfers are visible, including
  counterparty legs useful for tracing round-tripping and kickbacks.
- `company_only`: only transfers where the company CLABE is an endpoint are
  visible. External vendor/intermediary legs may be hidden, forcing weaker or
  indirect conclusions.

The profile changes the public projection, not the private causal construction.
Provenance records hidden and visible transaction IDs and the maximum confidence
expected from the available evidence.

## 9. Canonicalization and anti-leakage design

After scenario composition, the evaluator canonicalizes invoice, transaction,
purchase-order, and contract IDs and shuffles rows. Ledger descriptions and
foreign-key references are updated consistently. Vendors, employees, EFOS rows,
and ledger rows are also shuffled.

This prevents a detector from learning that the last vendor or highest invoice
ID is fraudulent. Sidecars contain the post-canonicalization IDs cited by public
records. The public package contains no scenario labels, answer-key imports, or
ground-truth references.

## 10. Outputs

Each estate contains eight UTF-8 CSV tables in schema-defined column order:

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

An optional SQLite export contains the same eight tables. Evaluation fixtures
also contain:

- `private/*.ground_truth.json`: planted scheme types, entities, supporting
  invoices/transactions, amounts, and decoys with `why_innocent` explanations.
- `private/*.provenance.json`: observation profile, visible/hidden evidence,
  confidence ceilings, amount basis, and illicit-benefit metadata.
- `matrix_manifest.json`: case ID, split, seed, category, variant, and sidecar
  paths.

Ground truth and provenance are evaluator metadata. They must never be supplied
to the investigator or loaded by the production detector.

## 11. Matrix design and train/report separation

The matrix has two independent dimensions:

1. Scenario family: clean, isolated scheme, mixed, or all-five.
2. Decoy variant: without decoys or with five decoys.

The `tuning` split is the development/training set: rules, thresholds, prompts,
and assembly logic may be changed after reviewing its results. The `report`
split is held out: freeze the detector before running it and do not inspect its
private answer keys during tuning.

The generator assigns globally unique seeds across both splits and all variants.
This is compatible with evaluators that name databases by seed. The manifest
provides a stable case-level index in addition to the numeric seed.

For robust experiments, compare clean estates, each isolated scheme, mixed and
all-five cases, both decoy variants, and both observation profiles when claiming
confidence calibration.

## 12. Limitations and appropriate use

The SDG uses hand-authored distributions, templates, and scenario mechanisms.
It does not model real vendor populations, tax records, bank latency, legal
outcomes, seasonal economics, or adversary adaptation. Its EFOS rows are
fictional screening context and are not real SAT data.

It is best used to test data plumbing, joins, accounting reconciliation,
explainable evidence selection, false-positive controls, and detector
regressions. Claims about real-world performance require independent,
appropriately governed data.
