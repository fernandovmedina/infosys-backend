"""The eight tables of the data estate, as `public/material/estate_schema.sql` defines them.

This is the single place that knows which columns each table carries, which of
them the investigation cannot do without, and what the user loses when a table
is absent. Ingestion and the validation diagnostics both read from here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

type SourceTable = Literal[
    "vendors",
    "invoices",
    "ledger",
    "bank_txns",
    "purchase_orders",
    "contracts",
    "employees",
    "efos_list",
]


@dataclass(frozen=True, slots=True)
class TableSpec:
    name: SourceTable
    columns: tuple[str, ...]
    # Without these the table is unusable (no key, no amount, no link to other tables).
    key_columns: tuple[str, ...]
    # The investigation cannot start without this table.
    required: bool
    # One sentence: what the investigation loses when the table is missing or unusable.
    capability_loss: str
    numeric_columns: tuple[str, ...] = ()
    date_columns: tuple[str, ...] = ()
    enum_columns: dict[str, tuple[str, ...]] = field(default_factory=dict)
    # File-name stems (already normalized) that also identify the table.
    aliases: tuple[str, ...] = ()


TABLE_SPECS: tuple[TableSpec, ...] = (
    TableSpec(
        name="vendors",
        columns=(
            "rfc",
            "legal_name",
            "registered_date",
            "address",
            "bank_clabe",
            "category",
            "contact_email",
        ),
        key_columns=("rfc", "bank_clabe"),
        required=False,
        capability_loss=(
            "without vendors, payment CLABEs cannot be linked to an RFC or phantom vendors detected"
        ),
        date_columns=("registered_date",),
        aliases=("vendor", "proveedores", "suppliers"),
    ),
    TableSpec(
        name="invoices",
        columns=(
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
        key_columns=("uuid", "issuer_rfc", "receiver_rfc", "issue_date", "total"),
        required=True,
        capability_loss="without invoices, there are no amounts to investigate or reconcile",
        numeric_columns=("subtotal", "iva", "total"),
        date_columns=("issue_date",),
        enum_columns={"metodo_pago": ("PUE", "PPD"), "status": ("vigente", "cancelado")},
        aliases=("invoice", "facturas", "cfdi", "cfdis"),
    ),
    TableSpec(
        name="ledger",
        columns=(
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
        key_columns=("entry_id", "date", "account_code", "debit", "credit"),
        required=False,
        capability_loss=(
            "without the ledger, accounting entries cannot be reconciled with invoices and payments"
        ),
        numeric_columns=("debit", "credit"),
        date_columns=("date",),
        aliases=("general_ledger", "gl", "journal", "polizas"),
    ),
    TableSpec(
        name="bank_txns",
        columns=("txn_id", "date", "from_clabe", "to_clabe", "amount", "reference", "channel"),
        key_columns=("txn_id", "date", "from_clabe", "to_clabe", "amount"),
        required=True,
        capability_loss="without bank transactions, the money trail cannot be followed",
        numeric_columns=("amount",),
        date_columns=("date",),
        enum_columns={"channel": ("SPEI", "cheque", "efectivo")},
        aliases=(
            "bank_txn",
            "bank_transactions",
            "bank_transaction",
            "transactions",
            "banco",
            "movimientos",
        ),
    ),
    TableSpec(
        name="purchase_orders",
        columns=("po_id", "vendor_rfc", "date", "amount", "requester", "approver", "description"),
        key_columns=("po_id", "vendor_rfc", "amount"),
        required=False,
        capability_loss=(
            "without purchase orders, approval limits and split payments cannot be verified"
        ),
        numeric_columns=("amount",),
        date_columns=("date",),
        aliases=("purchase_order", "pos", "po", "ordenes_compra", "ordenes_de_compra"),
    ),
    TableSpec(
        name="contracts",
        columns=("contract_id", "vendor_rfc", "start_date", "value", "scope_text"),
        key_columns=("contract_id", "vendor_rfc", "value"),
        required=False,
        capability_loss="without contracts, the scope of services cannot be verified",
        numeric_columns=("value",),
        date_columns=("start_date",),
        aliases=("contract", "contratos"),
    ),
    TableSpec(
        name="employees",
        columns=("emp_id", "name", "role", "bank_clabe", "hire_date"),
        key_columns=("emp_id", "name", "bank_clabe"),
        required=False,
        capability_loss="without employees, employee-vendor relationships cannot be detected",
        date_columns=("hire_date",),
        aliases=("employee", "empleados", "staff"),
    ),
    TableSpec(
        name="efos_list",
        columns=("rfc", "legal_name", "status", "publication_date"),
        key_columns=("rfc", "status"),
        required=False,
        capability_loss="without the EFOS list, the Article 69-B vendor detector cannot run",
        date_columns=("publication_date",),
        enum_columns={"status": ("definitivo", "presunto")},
        aliases=("efos", "lista_efos", "sat_69b", "69b", "blacklist", "black_list"),
    ),
)
