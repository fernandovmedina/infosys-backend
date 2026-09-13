"""Projection of internal exact-cent records into the challenge SQLite schema."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from app.estate_generator.challenge_contract import load_estate_schema
from app.estate_generator.checks import validate_public_estate
from app.estate_generator.config import ObservationProfile
from app.estate_generator.models import BankTransaction, Centavos, GeneratedEstate


def export_sqlite(
    estate: GeneratedEstate,
    output_path: Path,
    *,
    observation_profile: ObservationProfile,
    overwrite: bool = False,
) -> Path:
    """Write a standalone public SQLite estate using the supplied SQL schema."""
    validate_public_estate(estate)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        if not overwrite:
            raise FileExistsError(f"refusing to overwrite existing estate: {output_path}")
        output_path.unlink()
    with sqlite3.connect(output_path) as connection:
        connection.executescript(load_estate_schema())
        connection.executemany(
            "INSERT INTO vendors VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
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
        )
        connection.executemany(
            "INSERT INTO employees VALUES (?, ?, ?, ?, ?)",
            [(e.emp_id, e.name, e.role, e.bank_clabe, e.hire_date) for e in estate.employees],
        )
        connection.executemany(
            "INSERT INTO contracts VALUES (?, ?, ?, ?, ?)",
            [
                (c.contract_id, c.vendor_rfc, c.start_date, _pesos(c.value_centavos), c.scope_text)
                for c in estate.contracts
            ],
        )
        connection.executemany(
            "INSERT INTO purchase_orders VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    p.po_id,
                    p.vendor_rfc,
                    p.date,
                    _pesos(p.amount_centavos),
                    p.requester,
                    p.approver,
                    p.description,
                )
                for p in estate.purchase_orders
            ],
        )
        connection.executemany(
            "INSERT INTO invoices VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    i.uuid,
                    i.issuer_rfc,
                    i.receiver_rfc,
                    i.issue_date,
                    _pesos(i.subtotal_centavos),
                    _pesos(i.iva_centavos),
                    _pesos(i.total_centavos),
                    i.concepto_text,
                    i.uso_cfdi,
                    i.forma_pago,
                    i.metodo_pago,
                    i.status,
                )
                for i in estate.invoices
            ],
        )
        connection.executemany(
            "INSERT INTO ledger VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    line.entry_id,
                    line.date,
                    line.account_code,
                    line.account_name,
                    _pesos(line.debit_centavos),
                    _pesos(line.credit_centavos),
                    line.description,
                    line.invoice_uuid,
                    line.cost_center,
                    line.approver,
                )
                for line in estate.ledger
            ],
        )
        connection.executemany(
            "INSERT INTO bank_txns VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    t.txn_id,
                    t.date,
                    t.from_clabe,
                    t.to_clabe,
                    _pesos(t.amount_centavos),
                    t.reference,
                    t.channel,
                )
                for t in _observed_transactions(estate, observation_profile)
            ],
        )
        connection.executemany(
            "INSERT INTO efos_list VALUES (?, ?, ?, ?)",
            [
                (record.rfc, record.legal_name, record.status, record.publication_date)
                for record in estate.efos_records
            ],
        )
    return output_path


def _pesos(centavos: Centavos) -> float:
    return centavos / 100


def _observed_transactions(
    estate: GeneratedEstate, observation_profile: ObservationProfile
) -> list[BankTransaction]:
    if observation_profile is ObservationProfile.CHALLENGE_WIDE:
        return estate.bank_transactions
    return [
        transaction
        for transaction in estate.bank_transactions
        if transaction.from_clabe == estate.company_clabe
        or transaction.to_clabe == estate.company_clabe
    ]
