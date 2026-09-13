"""Invariant checks for a generated public estate before SQLite export."""

from __future__ import annotations

from collections import defaultdict
from datetime import date

from app.estate_generator.accounting import assert_balanced
from app.estate_generator.models import GeneratedEstate, LedgerLine

REQUIRED_TABLES = frozenset(
    {
        "vendors",
        "invoices",
        "ledger",
        "bank_txns",
        "purchase_orders",
        "contracts",
        "employees",
        "efos_list",
    }
)


def validate_public_estate(estate: GeneratedEstate) -> None:
    """Raise ``ValueError`` when public business or accounting invariants fail."""
    vendor_rfcs = {vendor.rfc for vendor in estate.vendors}
    employee_names = {employee.name for employee in estate.employees}
    invoices = {invoice.uuid: invoice for invoice in estate.invoices}
    _unique("vendor RFC", vendor_rfcs, len(estate.vendors))
    _unique(
        "employee id", {employee.emp_id for employee in estate.employees}, len(estate.employees)
    )
    _unique("invoice UUID", set(invoices), len(estate.invoices))
    _unique(
        "purchase order",
        {order.po_id for order in estate.purchase_orders},
        len(estate.purchase_orders),
    )
    _unique(
        "contract", {contract.contract_id for contract in estate.contracts}, len(estate.contracts)
    )
    _unique("ledger entry", {line.entry_id for line in estate.ledger}, len(estate.ledger))
    _unique(
        "bank transaction",
        {txn.txn_id for txn in estate.bank_transactions},
        len(estate.bank_transactions),
    )

    for invoice in estate.invoices:
        if invoice.subtotal_centavos + invoice.iva_centavos != invoice.total_centavos:
            raise ValueError(f"invoice arithmetic fails for {invoice.uuid}")
        if invoice.status not in {"vigente", "cancelado"}:
            raise ValueError(f"invalid invoice status for {invoice.uuid}")
        if invoice.issuer_rfc != estate.company_rfc and invoice.issuer_rfc not in vendor_rfcs:
            raise ValueError(f"unknown invoice issuer for {invoice.uuid}")

    for contract in estate.contracts:
        if contract.vendor_rfc not in vendor_rfcs:
            raise ValueError(f"unknown contract vendor {contract.contract_id}")
    for order in estate.purchase_orders:
        if order.vendor_rfc not in vendor_rfcs:
            raise ValueError(f"unknown purchase order vendor {order.po_id}")
        if order.requester not in employee_names or order.approver not in employee_names:
            raise ValueError(f"unknown employee on {order.po_id}")

    by_event: dict[str, list[LedgerLine]] = defaultdict(list)
    for line in estate.ledger:
        if line.invoice_uuid not in invoices:
            raise ValueError(f"ledger row {line.entry_id} references unknown invoice")
        if line.approver not in employee_names:
            raise ValueError(f"ledger row {line.entry_id} has unknown approver")
        by_event[line.event_id].append(line)
    for lines in by_event.values():
        assert_balanced(lines)

    for txn in estate.bank_transactions:
        if txn.amount_centavos <= 0:
            raise ValueError(f"non-positive bank transaction {txn.txn_id}")
        if txn.from_clabe not in estate.known_clabes or txn.to_clabe not in estate.known_clabes:
            raise ValueError(f"unresolved CLABE on {txn.txn_id}")
        if len(txn.from_clabe) != 18 or len(txn.to_clabe) != 18:
            raise ValueError(f"invalid CLABE length on {txn.txn_id}")
        if not _valid_clabe(txn.from_clabe) or not _valid_clabe(txn.to_clabe):
            raise ValueError(f"invalid CLABE checksum on {txn.txn_id}")
        if txn.from_clabe not in estate.accounts or txn.to_clabe not in estate.accounts:
            raise ValueError(f"unowned CLABE on {txn.txn_id}")

    if any(balance < 0 for balance in estate.payable_balances.values()):
        raise ValueError("negative payable balance")
    if any(balance < 0 for balance in estate.receivable_balances.values()):
        raise ValueError("negative receivable balance")
    for po_id, contract_id in estate.purchase_order_contracts.items():
        if po_id not in {order.po_id for order in estate.purchase_orders}:
            raise ValueError(f"unknown grouped-obligation purchase order {po_id}")
        if contract_id not in {contract.contract_id for contract in estate.contracts}:
            raise ValueError(f"unknown grouped-obligation contract {contract_id}")
    for invoice_id in estate.cancellation_reversals:
        if invoices[invoice_id].status != "cancelado":
            raise ValueError(f"reversal registered for non-cancelled invoice {invoice_id}")
    _validate_dates(estate)
    _validate_bank_balances(estate)


def _unique(label: str, values: set[str] | set[int], expected_count: int) -> None:
    if len(values) != expected_count:
        raise ValueError(f"duplicate {label}")


def _validate_dates(estate: GeneratedEstate) -> None:
    invoices = {invoice.uuid: invoice for invoice in estate.invoices}
    for line in estate.ledger:
        if line.invoice_uuid is None:
            continue
        if date.fromisoformat(line.date) < date.fromisoformat(
            invoices[line.invoice_uuid].issue_date
        ):
            raise ValueError(f"ledger date precedes invoice for {line.invoice_uuid}")
    for txn in estate.bank_transactions:
        if txn.reference.startswith("Invoice payment "):
            invoice_id = txn.reference.removeprefix("Invoice payment ")
            if date.fromisoformat(txn.date) < date.fromisoformat(invoices[invoice_id].issue_date):
                raise ValueError(f"payment date precedes invoice for {invoice_id}")


def _validate_bank_balances(estate: GeneratedEstate) -> None:
    balances = {
        clabe: 100_000_000_00 if account.holder_kind in {"company", "customer"} else 0
        for clabe, account in estate.accounts.items()
    }
    for transaction in sorted(estate.bank_transactions, key=lambda item: (item.date, item.txn_id)):
        if balances[transaction.from_clabe] < transaction.amount_centavos:
            raise ValueError(f"insufficient chronological funds on {transaction.txn_id}")
        balances[transaction.from_clabe] -= transaction.amount_centavos
        balances[transaction.to_clabe] += transaction.amount_centavos


def _valid_clabe(clabe: str) -> bool:
    weights = (3, 7, 1) * 5 + (3, 7)
    expected = (
        10
        - sum(int(digit) * weight for digit, weight in zip(clabe[:17], weights, strict=True)) % 10
    ) % 10
    return int(clabe[-1]) == expected
