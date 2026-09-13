"""Run-directory and CSV artifact helpers for the command-line generator."""

from __future__ import annotations

import csv
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path

from app.estate_generator.checks import validate_public_estate
from app.estate_generator.config import ObservationProfile
from app.estate_generator.exporter import export_sqlite
from app.estate_generator.models import GeneratedEstate

OUTPUT_ROOT = Path(__file__).resolve().parent / "output"

CSV_HEADERS: dict[str, tuple[str, ...]] = {
    "vendors": (
        "rfc",
        "legal_name",
        "registered_date",
        "address",
        "bank_clabe",
        "category",
        "contact_email",
    ),
    "invoices": (
        "uuid",
        "issuer_rfc",
        "receiver_rfc",
        "issue_date",
        "subtotal",
        "iva",
        "total",
        "concepto_text",
        "uso_cfdi",
        "forma_pago",
        "metodo_pago",
        "status",
    ),
    "ledger": (
        "entry_id",
        "date",
        "account_code",
        "account_name",
        "debit",
        "credit",
        "description",
        "invoice_uuid",
        "cost_center",
        "approver",
    ),
    "bank_txns": ("txn_id", "date", "from_clabe", "to_clabe", "amount", "reference", "channel"),
    "purchase_orders": (
        "po_id",
        "vendor_rfc",
        "date",
        "amount",
        "requester",
        "approver",
        "description",
    ),
    "contracts": ("contract_id", "vendor_rfc", "start_date", "value", "scope_text"),
    "employees": ("emp_id", "name", "role", "bank_clabe", "hire_date"),
    "efos_list": ("rfc", "legal_name", "status", "publication_date"),
}


def create_run_directory(
    seed: int,
    *,
    root: Path = OUTPUT_ROOT,
    now: datetime | None = None,
) -> Path:
    """Create a unique ``seed<seed>_<date>_<time>`` run directory."""
    timestamp = (now or datetime.now()).strftime("%Y%m%d_%H%M%S")
    root.mkdir(parents=True, exist_ok=True)
    candidate = root / f"seed{seed}_{timestamp}"
    suffix = 1
    while candidate.exists():
        suffix += 1
        candidate = root / f"seed{seed}_{timestamp}_{suffix}"
    candidate.mkdir()
    return candidate


def export_csv(
    estate: GeneratedEstate,
    output_directory: Path,
    *,
    observation_profile: ObservationProfile,
    overwrite: bool = False,
) -> dict[str, Path]:
    """Export the eight challenge tables as UTF-8 CSV files."""
    validate_public_estate(estate)
    output_directory.mkdir(parents=True, exist_ok=True)
    rows = _table_rows(estate, observation_profile)
    paths: dict[str, Path] = {}
    for table, table_rows in rows.items():
        path = output_directory / f"{table}.csv"
        if path.exists() and not overwrite:
            raise FileExistsError(f"refusing to overwrite existing CSV: {path}")
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle, lineterminator="\n")
            writer.writerow(CSV_HEADERS[table])
            writer.writerows(table_rows)
        paths[table] = path
    return paths


def export_run(
    estate: GeneratedEstate,
    *,
    seed: int,
    observation_profile: ObservationProfile,
    sqlite_only: bool = False,
    root: Path = OUTPUT_ROOT,
    now: datetime | None = None,
    overwrite: bool = False,
) -> tuple[Path, dict[str, Path]]:
    """Create a timestamped run directory and write CSVs or one SQLite file."""
    run_directory = create_run_directory(seed, root=root, now=now)
    if sqlite_only:
        database = run_directory / "estate.db"
        export_sqlite(
            estate,
            database,
            observation_profile=observation_profile,
            overwrite=overwrite,
        )
        return run_directory, {"sqlite": database}
    return run_directory, export_csv(
        estate,
        run_directory,
        observation_profile=observation_profile,
        overwrite=overwrite,
    )


def _table_rows(
    estate: GeneratedEstate, observation_profile: ObservationProfile
) -> dict[str, Iterable[tuple[object, ...]]]:
    transactions = estate.bank_transactions
    if observation_profile is ObservationProfile.COMPANY_ONLY:
        transactions = [
            item
            for item in transactions
            if estate.company_clabe in {item.from_clabe, item.to_clabe}
        ]
    return {
        "vendors": [
            (
                v.rfc,
                v.legal_name,
                v.registered_date,
                v.address,
                v.bank_clabe,
                v.category,
                v.contact_email,
            )
            for v in estate.vendors
        ],
        "invoices": [
            (
                i.uuid,
                i.issuer_rfc,
                i.receiver_rfc,
                i.issue_date,
                _peso(i.subtotal_centavos),
                _peso(i.iva_centavos),
                _peso(i.total_centavos),
                i.concepto_text,
                i.uso_cfdi,
                i.forma_pago,
                i.metodo_pago,
                i.status,
            )
            for i in estate.invoices
        ],
        "ledger": [
            (
                line.entry_id,
                line.date,
                line.account_code,
                line.account_name,
                _peso(line.debit_centavos),
                _peso(line.credit_centavos),
                line.description,
                line.invoice_uuid,
                line.cost_center,
                line.approver,
            )
            for line in estate.ledger
        ],
        "bank_txns": [
            (
                t.txn_id,
                t.date,
                t.from_clabe,
                t.to_clabe,
                _peso(t.amount_centavos),
                t.reference,
                t.channel,
            )
            for t in transactions
        ],
        "purchase_orders": [
            (
                p.po_id,
                p.vendor_rfc,
                p.date,
                _peso(p.amount_centavos),
                p.requester,
                p.approver,
                p.description,
            )
            for p in estate.purchase_orders
        ],
        "contracts": [
            (c.contract_id, c.vendor_rfc, c.start_date, _peso(c.value_centavos), c.scope_text)
            for c in estate.contracts
        ],
        "employees": [
            (e.emp_id, e.name, e.role, e.bank_clabe, e.hire_date) for e in estate.employees
        ],
        "efos_list": [
            (record.rfc, record.legal_name, record.status, record.publication_date)
            for record in estate.efos_records
        ],
    }


def _peso(centavos: int) -> str:
    return f"{centavos / 100:.2f}"
