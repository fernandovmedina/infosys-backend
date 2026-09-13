"""Internal, public-safe records for the estate projection.

Amounts are centavos throughout this module.  SQLite ``REAL`` values are only
created by :mod:`app.estate_generator.exporter` at the public boundary.
"""

from __future__ import annotations

from dataclasses import dataclass, field

Centavos = int


@dataclass(frozen=True, slots=True)
class Vendor:
    rfc: str
    legal_name: str
    registered_date: str
    address: str
    bank_clabe: str
    category: str
    contact_email: str


@dataclass(frozen=True, slots=True)
class Employee:
    emp_id: str
    name: str
    role: str
    bank_clabe: str
    hire_date: str


@dataclass(frozen=True, slots=True)
class Contract:
    contract_id: str
    vendor_rfc: str
    start_date: str
    value_centavos: Centavos
    scope_text: str


@dataclass(frozen=True, slots=True)
class PurchaseOrder:
    po_id: str
    vendor_rfc: str
    date: str
    amount_centavos: Centavos
    requester: str
    approver: str
    description: str


@dataclass(frozen=True, slots=True)
class Invoice:
    uuid: str
    issuer_rfc: str
    receiver_rfc: str
    issue_date: str
    subtotal_centavos: Centavos
    iva_centavos: Centavos
    total_centavos: Centavos
    concepto_text: str
    uso_cfdi: str
    forma_pago: str
    metodo_pago: str
    status: str


@dataclass(frozen=True, slots=True)
class LedgerLine:
    entry_id: int
    event_id: str
    date: str
    account_code: str
    account_name: str
    debit_centavos: Centavos
    credit_centavos: Centavos
    description: str
    invoice_uuid: str | None
    cost_center: str
    approver: str


@dataclass(frozen=True, slots=True)
class BankTransaction:
    txn_id: str
    date: str
    from_clabe: str
    to_clabe: str
    amount_centavos: Centavos
    reference: str
    channel: str


@dataclass(frozen=True, slots=True)
class EfosRecord:
    rfc: str
    legal_name: str
    status: str
    publication_date: str


@dataclass(frozen=True, slots=True)
class Account:
    """An account known to the simulator and its observable holder category.

    The category supports a later observation-profile projection.  It is not a
    fraud role and is intentionally used for both ordinary and future scenario
    activity.
    """

    clabe: str
    holder_kind: str
    holder_id: str


@dataclass(slots=True)
class GeneratedEstate:
    """A public estate plus ephemeral checks needed before export.

    This deliberately contains no planted-scenario attribution or evaluator
    data. ``payable_balances`` and ``receivable_balances`` are derived normal
    accounting state, not hidden facts made available in SQLite.
    """

    company_rfc: str
    company_clabe: str
    vendors: list[Vendor] = field(default_factory=list)
    employees: list[Employee] = field(default_factory=list)
    contracts: list[Contract] = field(default_factory=list)
    purchase_orders: list[PurchaseOrder] = field(default_factory=list)
    invoices: list[Invoice] = field(default_factory=list)
    ledger: list[LedgerLine] = field(default_factory=list)
    bank_transactions: list[BankTransaction] = field(default_factory=list)
    efos_records: list[EfosRecord] = field(default_factory=list)
    accounts: dict[str, Account] = field(default_factory=dict)
    account_links: dict[str, set[str]] = field(default_factory=dict)
    account_balances: dict[str, Centavos] = field(default_factory=dict)
    purchase_order_contracts: dict[str, str] = field(default_factory=dict)
    cancellation_reversals: dict[str, str] = field(default_factory=dict)
    payable_balances: dict[str, Centavos] = field(default_factory=dict)
    receivable_balances: dict[str, Centavos] = field(default_factory=dict)
    refunded_balances: dict[str, Centavos] = field(default_factory=dict)
    known_clabes: set[str] = field(default_factory=set)
