# Synthetic estate generator

This package generates deterministic, offline SQLite estates that match
`public/material/estate_schema.sql`. It is a library and CLI concern, not an
API route, and has no dependency on FastAPI, PostgreSQL, live SAT data, or the
private evaluator.

## Public generation

After `uv sync --all-groups`, generate a normal-business estate with:

```bash
uv run estate-generate \
  --seed 7 \
  --output generated/estate_7.db
```

Useful controls include `--start-date`, `--end-date`, `--vendor-count`,
`--employee-count`, `--normal-event-count`, `--observation-profile`, and
`--force`. Existing files are never replaced without `--force`.

The generator creates vendors, employees, contracts, purchase orders,
purchase and sales invoices, exact-cent double-entry postings, complete and
partial settlements, and cancellation/reversal paths. Before export it checks
identifier/link integrity, invoice arithmetic, journal balance, CLABE shape
and checksum, causal dates, and chronological account funding.

`challenge_wide` retains simulated third-party bank legs so complete kickback
and cycle evidence can be tested. `company_only` exports only transfers with a
company-account endpoint. In that restricted profile, the kickback fixture
uses a visible vendor/approver account conflict and is capped at `probable`;
round-tripping is likewise capped because its intermediary leg is hidden.

## Package boundaries

| Module | Responsibility |
|---|---|
| `config.py` | Public seed, date, volume, and observation controls |
| `challenge_contract.py` | Read-only access to the supplied schema |
| `models.py` | Typed exact-cent internal records |
| `normal_business.py` | Ordinary event, accounting, settlement, and refund APIs |
| `accounting.py` | IVA and journal-balance helpers |
| `checks.py` | Public-estate invariants |
| `exporter.py` | Projection into the eight supplied SQLite tables |
| `generator.py` | Public generation facade |
| `cli.py` | Reproducible offline command |

Scenario attribution, decoy rationale, and answer keys live under
`evaluation/estate_generator/`; no module in `app/estate_generator/` imports
that boundary. Deploy the investigator with only the public database and
application code—not `evaluation/` or generated `private/` sidecars
(`*.ground_truth.json` and `*.provenance.json`).

## Scope and caveat

This is a strong hackathon fixture generator, not an empirically calibrated
digital twin. Its entities and EFOS rows are fictional. EFOS status is context,
never standalone proof, and no real SAT taxpayer allegation is copied into an
estate. Use multiple seeds and both observation profiles for tuning, then keep
separate seeds held out for evaluation.

See [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) for the implementation and
review contract.
