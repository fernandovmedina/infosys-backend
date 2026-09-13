# Estate CSV — Field Shape Example

One row per file, showing the exact column names and value formats your CSV loader
must handle. This mirrors the layout inside the `estate_csv.zip` judges hand you.

**This is not a dataset.** The values are placeholders, the rows do not all join to
each other, and there is no fraud planted here. Use it to check that your loader
reads the right columns with the right types — nothing more.

| File | Key column | Amount column |
|---|---|---|
| `vendors.csv` | `rfc` | — |
| `invoices.csv` | `uuid` | `total` |
| `ledger.csv` | `entry_id` | `debit` / `credit` |
| `bank_txns.csv` | `txn_id` | `amount` |
| `purchase_orders.csv` | `po_id` | `amount` |
| `contracts.csv` | `contract_id` | `value` |
| `employees.csv` | `emp_id` | — |
| `efos_list.csv` | `rfc` | — |

Notes on the formats:

- **Encoding is UTF-8.** Names and `concepto_text` carry Spanish accents in a real estate.
- **Dates are ISO 8601** (`YYYY-MM-DD`), as plain strings.
- **CLABEs are 18-digit strings with leading zeros.** Parse them as text — reading
  them as integers silently destroys the leading zero and breaks every CLABE join,
  which is how kickback and round-tripping schemes are traced.
- **RFCs are 12–13 characters.** In a submission they carry a type prefix
  (`RFC:AAAA010101AA1`); in the estate tables they do not.
- **Fields containing commas are quoted**, per RFC 4180. Your parser must handle
  quoted fields — see `address` in `vendors.csv`.
- `status` in `invoices.csv` is `vigente` or `cancelado`; `status` in
  `efos_list.csv` is `definitivo` or `presunto`. Different columns, different enums.

The authoritative column list is `../estate_schema.sql`.
