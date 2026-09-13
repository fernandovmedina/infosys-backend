"""Deterministic normal commercial events for the first generator slice."""

from __future__ import annotations

from datetime import date, timedelta
from random import Random

from app.estate_generator.accounting import (
    assert_balanced,
    assert_non_negative_amount,
    calculate_iva,
)
from app.estate_generator.config import EstateGeneratorConfig
from app.estate_generator.models import (
    Account,
    BankTransaction,
    Centavos,
    Contract,
    EfosRecord,
    Employee,
    GeneratedEstate,
    Invoice,
    LedgerLine,
    PurchaseOrder,
    Vendor,
)

_CATEGORIES = ("Mantenimiento", "Consultoria", "Logistica", "Insumos", "Tecnologia")
_SCOPES = {
    "Mantenimiento": "Mantenimiento preventivo de instalaciones",
    "Consultoria": "Servicios de consultoria operativa",
    "Logistica": "Servicios de logistica y entrega",
    "Insumos": "Suministro de insumos de produccion",
    "Tecnologia": "Soporte y licencias de tecnologia",
}
_NAMES = ("Ana Ruiz", "Bruno Garcia", "Carla Soto", "Diego Luna", "Elena Mora", "Fabian Rios")
_ROLES = ("Compras", "Finanzas", "Operaciones", "Contraloria", "Direccion")


class EstateEventBuilder:
    """Build public business events while preserving deterministic identifiers.

    Scenario code can use these methods after :meth:`build_normal_activity`
    instead of patching SQLite rows.  The builder never accepts scenario names,
    labels, or evaluator-only attribution.
    """

    def __init__(self, config: EstateGeneratorConfig) -> None:
        self.config = config
        self.random = Random(config.seed)
        self.start_date = config.start_date
        self.end_date = config.end_date
        if self.end_date < self.start_date:
            raise ValueError("end_date must not precede start_date")
        if config.vendor_count < 3 or config.employee_count < 2:
            raise ValueError("normal-business profile requires at least 3 vendors and 2 employees")
        if config.normal_event_count < 22:
            raise ValueError("normal_event_count must be at least 22")
        self._identity_code = config.seed % 100_000_000
        self.company_rfc = self._rfc(0)
        self.company_clabe = self._clabe(0)
        self.estate = GeneratedEstate(
            company_rfc=self.company_rfc,
            company_clabe=self.company_clabe,
        )
        self.add_account(self.company_clabe, holder_kind="company", holder_id=self.company_rfc)
        self._ledger_id = 1
        self._po_id = 1
        self._contract_id = 1
        self._invoice_id = 1
        self._transaction_id = 1

    def build_normal_activity(self) -> GeneratedEstate:
        self._add_employees()
        self._add_vendors()
        self._add_recurring_purchases()
        self._add_one_off_purchases()
        self._add_cancelled_purchase_with_reversal()
        self._add_credit_sales()
        return self.estate

    def add_account(
        self,
        clabe: str,
        *,
        holder_kind: str,
        holder_id: str,
        allow_shared: bool = False,
    ) -> Account:
        """Register an account before using it in an observed transfer."""
        if not _valid_clabe(clabe):
            raise ValueError("account CLABE must be an 18-digit valid string")
        if clabe in self.estate.accounts:
            if not allow_shared:
                raise ValueError(f"account CLABE already exists: {clabe}")
            self.estate.account_links[clabe].add(holder_id)
            return self.estate.accounts[clabe]
        account = Account(clabe=clabe, holder_kind=holder_kind, holder_id=holder_id)
        self.estate.accounts[clabe] = account
        self.estate.known_clabes.add(clabe)
        self.estate.account_links[clabe] = {holder_id}
        self.estate.account_balances[clabe] = (
            100_000_000_00 if holder_kind in {"company", "customer"} else 0
        )
        return account

    def add_vendor(
        self,
        *,
        category: str,
        legal_name: str | None = None,
        rfc: str | None = None,
        bank_clabe: str | None = None,
        allow_shared_account: bool = False,
    ) -> Vendor:
        """Add a normal vendor and its account through the shared identity path."""
        if category not in _SCOPES:
            raise ValueError(f"unsupported vendor category: {category}")
        index = len(self.estate.vendors) + 1
        vendor_rfc = rfc or self._rfc(index)
        if vendor_rfc in {vendor.rfc for vendor in self.estate.vendors}:
            raise ValueError(f"vendor RFC already exists: {vendor_rfc}")
        vendor_clabe = bank_clabe or self._clabe(index)
        vendor = Vendor(
            rfc=vendor_rfc,
            legal_name=legal_name
            or f"Servicios {category} {self._identity_code:08d}-{index:03d} SA de CV",
            registered_date=f"202{index % 5}-0{(index % 9) + 1}-15",
            address=f"Av. Industria {100 + index}, Monterrey, Nuevo Leon",
            bank_clabe=vendor_clabe,
            category=category,
            contact_email=f"contacto{self._identity_code:08d}-{index:03d}@proveedor.example.mx",
        )
        self.add_account(
            vendor.bank_clabe,
            holder_kind="vendor",
            holder_id=vendor.rfc,
            allow_shared=allow_shared_account,
        )
        self.estate.vendors.append(vendor)
        return vendor

    def add_contract(
        self, *, vendor: Vendor, start_date: date, value_centavos: Centavos, scope_text: str
    ) -> Contract:
        """Create a contract that later purchase orders can group under."""
        assert_non_negative_amount(value_centavos, label="contract value")
        if start_date > self.end_date:
            raise ValueError("contract start_date must not follow the observation window")
        self._require_vendor(vendor)
        contract = Contract(
            contract_id=self._next_contract_id(),
            vendor_rfc=vendor.rfc,
            start_date=start_date.isoformat(),
            value_centavos=value_centavos,
            scope_text=scope_text,
        )
        self.estate.contracts.append(contract)
        return contract

    def add_efos_context(
        self, *, vendor: Vendor, status: str, publication_date: date
    ) -> EfosRecord:
        """Add a fictional screening-context row; it is never causal proof by itself."""
        if status not in {"presunto", "definitivo"}:
            raise ValueError("EFOS status must be presunto or definitivo")
        self._require_vendor(vendor)
        record = EfosRecord(
            rfc=vendor.rfc,
            legal_name=vendor.legal_name,
            status=status,
            publication_date=publication_date.isoformat(),
        )
        self.estate.efos_records.append(record)
        return record

    def record_purchase(
        self,
        *,
        vendor: Vendor,
        event_date: date,
        subtotal_centavos: Centavos,
        description: str | None = None,
        contract: Contract | None = None,
        requester: Employee | None = None,
        approver: Employee | None = None,
        create_purchase_order: bool = True,
        settle: bool = True,
        status: str = "vigente",
    ) -> Invoice:
        """Record a PO, AP invoice, balanced posting, and optional settlement."""
        self._require_vendor(vendor)
        self._require_event_date(event_date)
        if contract is not None and contract.vendor_rfc != vendor.rfc:
            raise ValueError("purchase contract belongs to another vendor")
        return self._purchase(
            vendor,
            event_date,
            subtotal_centavos,
            recurring=False,
            settle=settle,
            status=status,
            contract_id=contract.contract_id if contract else None,
            description=description,
            requester_name=requester.name if requester else None,
            approver_name=approver.name if approver else None,
            create_purchase_order=create_purchase_order,
        )

    def record_sale(
        self,
        *,
        customer_rfc: str,
        customer_clabe: str,
        event_date: date,
        subtotal_centavos: Centavos,
        description: str,
        settle: bool = True,
        status: str = "vigente",
    ) -> Invoice:
        """Record a credit sale and optional inbound customer settlement."""
        self._require_event_date(event_date)
        if customer_clabe not in self.estate.accounts:
            self.add_account(customer_clabe, holder_kind="customer", holder_id=customer_rfc)
        invoice = self._issue_invoice(
            issuer_rfc=self.estate.company_rfc,
            receiver_rfc=customer_rfc,
            event_date=event_date,
            subtotal_centavos=subtotal_centavos,
            description=description,
            status=status,
        )
        self._post_sale_invoice(invoice, self.estate.employees[1].name)
        if settle:
            self._receive_customer_payment(invoice, customer_clabe, event_date)
        return invoice

    def reverse_cancelled_purchase(
        self, *, invoice: Invoice, reversal_date: date, approver: str | None = None
    ) -> None:
        """Post the balanced AP reversal for a cancelled purchase invoice."""
        if invoice.status != "cancelado":
            raise ValueError("only a cancelled purchase invoice may be reversed")
        self._require_event_date(reversal_date)
        self._post_purchase_reversal(
            invoice,
            reversal_date,
            approver or self.estate.employees[1].name,
        )

    def reverse_cancelled_sale(
        self, *, invoice: Invoice, reversal_date: date, approver: str | None = None
    ) -> None:
        """Post the balanced reversal for a cancelled credit-sale invoice."""
        if invoice.status != "cancelado" or invoice.issuer_rfc != self.estate.company_rfc:
            raise ValueError("only a cancelled company sale may be reversed")
        self._require_event_date(reversal_date)
        lines = self._ledger_lines(
            event_id=f"SALE_REVERSAL:{invoice.uuid}",
            date_value=reversal_date.isoformat(),
            invoice_uuid=invoice.uuid,
            approver=approver or self.estate.employees[1].name,
            description=f"Reversion de venta cancelada {invoice.uuid}",
            amounts=(
                ("4000", "Ingresos por servicios", invoice.subtotal_centavos, 0),
                ("2080", "IVA trasladado", invoice.iva_centavos, 0),
                ("1050", "Cuentas por cobrar", 0, invoice.total_centavos),
            ),
        )
        assert_balanced(lines)
        self.estate.ledger.extend(lines)
        self.estate.receivable_balances[invoice.uuid] = 0
        self.estate.cancellation_reversals[invoice.uuid] = lines[0].event_id

    def record_purchase_refund(
        self, *, invoice: Invoice, vendor: Vendor, refund_date: date, amount_centavos: Centavos
    ) -> BankTransaction:
        """Record a vendor refund with a balanced bank/expense correction."""
        self._require_event_date(refund_date)
        self._require_vendor(vendor)
        assert_non_negative_amount(amount_centavos, label="refund amount")
        settled = invoice.total_centavos - self.estate.payable_balances[invoice.uuid]
        already_refunded = self.estate.refunded_balances.get(invoice.uuid, 0)
        if amount_centavos > settled - already_refunded:
            raise ValueError("refund cannot exceed the settled, unrefunded amount")
        expense_refund = amount_centavos * invoice.subtotal_centavos // invoice.total_centavos
        iva_refund = amount_centavos - expense_refund
        lines = self._ledger_lines(
            event_id=f"REFUND:{invoice.uuid}:{self._transaction_id}",
            date_value=refund_date.isoformat(),
            invoice_uuid=invoice.uuid,
            approver=self.estate.employees[1].name,
            description=f"Reembolso proveedor {invoice.uuid}",
            amounts=(
                ("1020", "Bancos", amount_centavos, 0),
                ("5000", "Gastos operativos", 0, expense_refund),
                ("1180", "IVA acreditable", 0, iva_refund),
            ),
        )
        assert_balanced(lines)
        self.estate.ledger.extend(lines)
        self.estate.refunded_balances[invoice.uuid] = already_refunded + amount_centavos
        if (
            invoice.status == "cancelado"
            and self.estate.refunded_balances[invoice.uuid] == invoice.total_centavos
        ):
            self.estate.cancellation_reversals[invoice.uuid] = lines[0].event_id
        return self.record_transfer(
            transfer_date=refund_date,
            from_clabe=vendor.bank_clabe,
            to_clabe=self.estate.company_clabe,
            amount_centavos=amount_centavos,
            reference=f"Reembolso proveedor {invoice.uuid}",
        )

    def record_transfer(
        self,
        *,
        transfer_date: date,
        from_clabe: str,
        to_clabe: str,
        amount_centavos: Centavos,
        reference: str,
        channel: str = "SPEI",
    ) -> BankTransaction:
        """Record an observed inbound, outbound, or third-party bank transfer."""
        assert_non_negative_amount(amount_centavos, label="transfer amount")
        self._require_event_date(transfer_date)
        if from_clabe not in self.estate.accounts or to_clabe not in self.estate.accounts:
            raise ValueError("both transfer CLABEs must be registered accounts")
        if channel not in {"SPEI", "cheque", "efectivo"}:
            raise ValueError(f"unsupported payment channel: {channel}")
        if self.estate.account_balances[from_clabe] < amount_centavos:
            raise ValueError(f"insufficient simulated funds for {from_clabe}")
        transaction = BankTransaction(
            txn_id=self._next_transaction_id(),
            date=transfer_date.isoformat(),
            from_clabe=from_clabe,
            to_clabe=to_clabe,
            amount_centavos=amount_centavos,
            reference=reference,
            channel=channel,
        )
        self.estate.bank_transactions.append(transaction)
        self.estate.account_balances[from_clabe] -= amount_centavos
        self.estate.account_balances[to_clabe] += amount_centavos
        return transaction

    def _add_employees(self) -> None:
        for index in range(1, self.config.employee_count + 1):
            name = _NAMES[(index - 1) % len(_NAMES)] + f" {index:02d}"
            employee = Employee(
                emp_id=f"EMP:{self._identity_code:08d}-{index:04d}",
                name=f"{name} {self._identity_code:08d}",
                role=_ROLES[(index - 1) % len(_ROLES)],
                bank_clabe=self._clabe(100_000 + index),
                hire_date=f"202{index % 5}-01-{(index % 27) + 1:02d}",
            )
            self.estate.employees.append(employee)
            self.add_account(
                employee.bank_clabe,
                holder_kind="employee",
                holder_id=employee.emp_id,
            )

    def _add_vendors(self) -> None:
        for index in range(1, self.config.vendor_count + 1):
            category = _CATEGORIES[(index - 1) % len(_CATEGORIES)]
            self.add_vendor(category=category)

    def _add_recurring_purchases(self) -> None:
        months = self._month_starts()
        for vendor in self.estate.vendors[:3]:
            monthly_subtotal = self.random.randrange(18_000, 45_000) * 100
            contract = self.add_contract(
                vendor=vendor,
                start_date=months[0],
                value_centavos=monthly_subtotal * len(months),
                scope_text=f"Contrato marco: {_SCOPES[vendor.category].lower()}",
            )
            for month_start in months:
                event_date = min(
                    max(month_start + timedelta(days=4), self.start_date),
                    self.end_date,
                )
                self._purchase(
                    vendor,
                    event_date,
                    monthly_subtotal,
                    recurring=True,
                    contract_id=contract.contract_id,
                )

    def _add_one_off_purchases(self) -> None:
        span = max((self.end_date - self.start_date).days, 1)
        fixed_invoice_count = len(self._month_starts()) * 3 + 3
        count = self.config.normal_event_count - fixed_invoice_count
        if count < 1:
            raise ValueError("normal_event_count is too low for the selected date range")
        for index in range(count):
            vendor = self.estate.vendors[3 + (index % (len(self.estate.vendors) - 3))]
            event_date = self.start_date + timedelta(days=8 + (index * 11) % max(span - 8, 1))
            subtotal = self.random.randrange(12_000, 95_000) * 100
            self._purchase(vendor, min(event_date, self.end_date), subtotal, recurring=False)

    def _add_cancelled_purchase_with_reversal(self) -> None:
        vendor = self.estate.vendors[-1]
        event_date = min(self.start_date + timedelta(days=18), self.end_date)
        invoice = self._purchase(
            vendor, event_date, 22_500_00, recurring=False, settle=False, status="cancelado"
        )
        reversal_date = min(event_date + timedelta(days=2), self.end_date)
        self._post_purchase_reversal(invoice, reversal_date, self.estate.employees[1].name)

    def _add_credit_sales(self) -> None:
        customer_rfc = self._rfc(200_000)
        customer_clabe = self._clabe(200_000)
        event_date = min(self.start_date + timedelta(days=12), self.end_date)
        for index, subtotal in enumerate((38_000_00, 61_500_00), start=1):
            invoice = self.record_sale(
                customer_rfc=customer_rfc,
                customer_clabe=customer_clabe,
                event_date=min(event_date + timedelta(days=index * 17), self.end_date),
                subtotal_centavos=subtotal,
                description=f"Venta a credito de servicios operativos {index}",
                settle=False,
            )
            receipt_date = min(
                date.fromisoformat(invoice.issue_date) + timedelta(days=9), self.end_date
            )
            self._receive_customer_payment(invoice, customer_clabe, receipt_date)

    def _purchase(
        self,
        vendor: Vendor,
        event_date: date,
        subtotal_centavos: Centavos,
        *,
        recurring: bool,
        settle: bool = True,
        status: str = "vigente",
        contract_id: str | None = None,
        description: str | None = None,
        requester_name: str | None = None,
        approver_name: str | None = None,
        create_purchase_order: bool = True,
    ) -> Invoice:
        requester = (
            requester_name
            or self.estate.employees[(self._po_id - 1) % len(self.estate.employees)].name
        )
        approver = (
            approver_name or self.estate.employees[self._po_id % len(self.estate.employees)].name
        )
        description = description or _SCOPES[vendor.category]
        if recurring:
            description = f"Cuota mensual: {description.lower()}"
        invoice_total = subtotal_centavos + calculate_iva(subtotal_centavos)
        if create_purchase_order:
            po = PurchaseOrder(
                po_id=self._next_po_id(),
                vendor_rfc=vendor.rfc,
                date=event_date.isoformat(),
                amount_centavos=invoice_total,
                requester=requester,
                approver=approver,
                description=description,
            )
            self.estate.purchase_orders.append(po)
            if contract_id is not None:
                self.estate.purchase_order_contracts[po.po_id] = contract_id
        invoice = self._issue_invoice(
            issuer_rfc=vendor.rfc,
            receiver_rfc=self.estate.company_rfc,
            event_date=event_date,
            subtotal_centavos=subtotal_centavos,
            description=description,
            status=status,
        )
        self._post_purchase_invoice(invoice, approver)
        if settle:
            if recurring and self._invoice_id % 2 == 0:
                first_payment = invoice.total_centavos * 60 // 100
                self._settle_purchase(
                    invoice,
                    vendor,
                    min(event_date + timedelta(days=7), self.end_date),
                    first_payment,
                )
                self._settle_purchase(
                    invoice,
                    vendor,
                    min(event_date + timedelta(days=18), self.end_date),
                    invoice.total_centavos - first_payment,
                )
            else:
                self._settle_purchase(
                    invoice,
                    vendor,
                    min(event_date + timedelta(days=10), self.end_date),
                    invoice.total_centavos,
                )
        return invoice

    def _issue_invoice(
        self,
        *,
        issuer_rfc: str,
        receiver_rfc: str,
        event_date: date,
        subtotal_centavos: Centavos,
        description: str,
        status: str,
    ) -> Invoice:
        assert_non_negative_amount(subtotal_centavos, label="invoice subtotal")
        iva = calculate_iva(subtotal_centavos)
        invoice = Invoice(
            uuid=f"INV-{self._invoice_id:05d}",
            issuer_rfc=issuer_rfc,
            receiver_rfc=receiver_rfc,
            issue_date=event_date.isoformat(),
            subtotal_centavos=subtotal_centavos,
            iva_centavos=iva,
            total_centavos=subtotal_centavos + iva,
            concepto_text=description,
            uso_cfdi="G03",
            forma_pago="03",
            metodo_pago="PPD",
            status=status,
        )
        self._invoice_id += 1
        self.estate.invoices.append(invoice)
        return invoice

    def _post_purchase_invoice(self, invoice: Invoice, approver: str) -> None:
        lines = self._ledger_lines(
            event_id=f"PURCHASE:{invoice.uuid}",
            date_value=invoice.issue_date,
            invoice_uuid=invoice.uuid,
            approver=approver,
            description=f"Registro factura {invoice.uuid}",
            amounts=(
                ("5000", "Gastos operativos", invoice.subtotal_centavos, 0),
                ("1180", "IVA acreditable", invoice.iva_centavos, 0),
                ("2100", "Cuentas por pagar", 0, invoice.total_centavos),
            ),
        )
        assert_balanced(lines)
        self.estate.ledger.extend(lines)
        self.estate.payable_balances[invoice.uuid] = invoice.total_centavos

    def _settle_purchase(
        self, invoice: Invoice, vendor: Vendor, payment_date: date, amount_centavos: Centavos
    ) -> None:
        outstanding = self.estate.payable_balances[invoice.uuid]
        if amount_centavos <= 0 or amount_centavos > outstanding:
            raise ValueError(f"invalid payment against {invoice.uuid}")
        lines = self._ledger_lines(
            event_id=f"SETTLEMENT:{invoice.uuid}:{self._transaction_id}",
            date_value=payment_date.isoformat(),
            invoice_uuid=invoice.uuid,
            approver=self.estate.employees[1].name,
            description=f"Pago factura {invoice.uuid}",
            amounts=(
                ("2100", "Cuentas por pagar", amount_centavos, 0),
                ("1020", "Bancos", 0, amount_centavos),
            ),
        )
        assert_balanced(lines)
        self.estate.ledger.extend(lines)
        self.estate.payable_balances[invoice.uuid] = outstanding - amount_centavos
        self.record_transfer(
            transfer_date=payment_date,
            from_clabe=self.estate.company_clabe,
            to_clabe=vendor.bank_clabe,
            amount_centavos=amount_centavos,
            reference=f"Pago factura {invoice.uuid}",
        )

    def _post_purchase_reversal(self, invoice: Invoice, reversal_date: date, approver: str) -> None:
        lines = self._ledger_lines(
            event_id=f"REVERSAL:{invoice.uuid}",
            date_value=reversal_date.isoformat(),
            invoice_uuid=invoice.uuid,
            approver=approver,
            description=f"Reversion de factura cancelada {invoice.uuid}",
            amounts=(
                ("2100", "Cuentas por pagar", invoice.total_centavos, 0),
                ("5000", "Gastos operativos", 0, invoice.subtotal_centavos),
                ("1180", "IVA acreditable", 0, invoice.iva_centavos),
            ),
        )
        assert_balanced(lines)
        self.estate.ledger.extend(lines)
        self.estate.payable_balances[invoice.uuid] = 0
        self.estate.cancellation_reversals[invoice.uuid] = lines[0].event_id

    def _post_sale_invoice(self, invoice: Invoice, approver: str) -> None:
        lines = self._ledger_lines(
            event_id=f"SALE:{invoice.uuid}",
            date_value=invoice.issue_date,
            invoice_uuid=invoice.uuid,
            approver=approver,
            description=f"Registro venta {invoice.uuid}",
            amounts=(
                ("1050", "Cuentas por cobrar", invoice.total_centavos, 0),
                ("4000", "Ingresos por servicios", 0, invoice.subtotal_centavos),
                ("2080", "IVA trasladado", 0, invoice.iva_centavos),
            ),
        )
        assert_balanced(lines)
        self.estate.ledger.extend(lines)
        self.estate.receivable_balances[invoice.uuid] = invoice.total_centavos

    def _receive_customer_payment(
        self, invoice: Invoice, customer_clabe: str, payment_date: date
    ) -> None:
        amount_centavos = self.estate.receivable_balances[invoice.uuid]
        lines = self._ledger_lines(
            event_id=f"RECEIPT:{invoice.uuid}",
            date_value=payment_date.isoformat(),
            invoice_uuid=invoice.uuid,
            approver=self.estate.employees[1].name,
            description=f"Cobro factura {invoice.uuid}",
            amounts=(
                ("1020", "Bancos", amount_centavos, 0),
                ("1050", "Cuentas por cobrar", 0, amount_centavos),
            ),
        )
        assert_balanced(lines)
        self.estate.ledger.extend(lines)
        self.estate.receivable_balances[invoice.uuid] = 0
        self.record_transfer(
            transfer_date=payment_date,
            from_clabe=customer_clabe,
            to_clabe=self.estate.company_clabe,
            amount_centavos=amount_centavos,
            reference=f"Cobro factura {invoice.uuid}",
        )

    def _ledger_lines(
        self,
        *,
        event_id: str,
        date_value: str,
        invoice_uuid: str,
        approver: str,
        description: str,
        amounts: tuple[tuple[str, str, Centavos, Centavos], ...],
    ) -> list[LedgerLine]:
        lines: list[LedgerLine] = []
        for account_code, account_name, debit, credit in amounts:
            lines.append(
                LedgerLine(
                    entry_id=self._ledger_id,
                    event_id=event_id,
                    date=date_value,
                    account_code=account_code,
                    account_name=account_name,
                    debit_centavos=debit,
                    credit_centavos=credit,
                    description=description,
                    invoice_uuid=invoice_uuid,
                    cost_center="CC-100 Operaciones",
                    approver=approver,
                )
            )
            self._ledger_id += 1
        return lines

    def _month_starts(self) -> list[date]:
        result: list[date] = []
        current = self.start_date.replace(day=1)
        while current <= self.end_date:
            result.append(current)
            current = date(current.year + (current.month == 12), (current.month % 12) + 1, 1)
        return result

    def _clabe(self, index: int) -> str:
        value = (self._identity_code * 10_007 + index * 7_919) % 100_000_000_000
        base = f"646180{value:011d}"
        weights = (3, 7, 1) * 5 + (3, 7)
        checksum = (
            10 - sum(int(digit) * weight for digit, weight in zip(base, weights, strict=True)) % 10
        ) % 10
        return f"{base}{checksum}"

    def _rfc(self, index: int) -> str:
        prefix = self._letters(self._identity_code * 31 + index, width=3)
        suffix = self._letters(self._identity_code * 17 + index * 13, width=3)
        year = 70 + (self._identity_code + index) % 30
        month = 1 + (self._identity_code + index * 3) % 12
        day = 1 + (self._identity_code + index * 7) % 28
        return f"{prefix}{year:02d}{month:02d}{day:02d}{suffix}"

    @staticmethod
    def _letters(value: int, *, width: int) -> str:
        letters: list[str] = []
        for _ in range(width):
            value, remainder = divmod(value, 26)
            letters.append(chr(ord("A") + remainder))
        return "".join(reversed(letters))

    def _require_vendor(self, vendor: Vendor) -> None:
        if vendor.rfc not in {known_vendor.rfc for known_vendor in self.estate.vendors}:
            raise ValueError(f"unknown vendor: {vendor.rfc}")

    def _require_event_date(self, event_date: date) -> None:
        if not self.start_date <= event_date <= self.end_date:
            raise ValueError("event date must fall within the observation window")

    def _next_po_id(self) -> str:
        value = f"PO-{self._po_id:05d}"
        self._po_id += 1
        return value

    def _next_contract_id(self) -> str:
        value = f"CTR-{self._contract_id:05d}"
        self._contract_id += 1
        return value

    def _next_transaction_id(self) -> str:
        value = f"BNK-{self._transaction_id:05d}"
        self._transaction_id += 1
        return value


def build_normal_estate(config: EstateGeneratorConfig) -> GeneratedEstate:
    """Generate deterministic ordinary activity for a public estate."""
    return EstateEventBuilder(config).build_normal_activity()


def build_normal_builder(config: EstateGeneratorConfig) -> EstateEventBuilder:
    """Return a normal-activity builder ready for event-level extensions."""
    builder = EstateEventBuilder(config)
    builder.build_normal_activity()
    return builder


def _valid_clabe(clabe: str) -> bool:
    if len(clabe) != 18 or not clabe.isdigit():
        return False
    weights = (3, 7, 1) * 5 + (3, 7)
    expected = (
        10
        - sum(int(digit) * weight for digit, weight in zip(clabe[:17], weights, strict=True)) % 10
    ) % 10
    return int(clabe[-1]) == expected
