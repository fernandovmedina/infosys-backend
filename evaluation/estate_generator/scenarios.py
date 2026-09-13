"""Private scenario assembly using public business-event APIs only."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from random import Random

from app.estate_generator.accounting import calculate_iva
from app.estate_generator.config import EstateGeneratorConfig, ObservationProfile
from app.estate_generator.models import GeneratedEstate, Invoice
from app.estate_generator.normal_business import EstateEventBuilder, build_normal_builder

SCHEME_TYPES = (
    "phantom_vendor",
    "kickback",
    "round_tripping",
    "threshold_splitting",
    "revenue_inflation",
)


@dataclass(frozen=True, slots=True)
class PrivateScenario:
    scheme_id: str
    scheme_type: str
    entities: tuple[str, ...]
    invoices: tuple[str, ...]
    transactions: tuple[str, ...]
    peso_centavos: int
    difficulty: str
    maximum_public_confidence: str
    illicit_benefit_centavos: int | None = None


@dataclass(frozen=True, slots=True)
class PrivateDecoy:
    entity: str
    signal: str
    why_innocent: str
    invoices: tuple[str, ...]


@dataclass(slots=True)
class ScenarioRun:
    estate: GeneratedEstate
    scenarios: list[PrivateScenario]
    decoys: list[PrivateDecoy]


def build_scenario_run(
    config: EstateGeneratorConfig,
    *,
    all_five: bool = False,
    scheme_count: int | None = None,
    scheme_types: Sequence[str] | None = None,
    decoy_count: int | None = None,
) -> ScenarioRun:
    """Build a variable private fixture and its public estate, offline and seeded."""
    if all_five and (scheme_count is not None or scheme_types is not None):
        raise ValueError("all_five cannot be combined with another scheme selection")
    if scheme_count is not None and scheme_types is not None:
        raise ValueError("scheme_count cannot be combined with scheme_types")
    if scheme_types is not None:
        selected = tuple(scheme_types)
        if not selected or len(selected) > len(SCHEME_TYPES):
            raise ValueError("scheme_types must contain 1..5 scheme types")
        if len(set(selected)) != len(selected) or any(
            scheme_type not in SCHEME_TYPES for scheme_type in selected
        ):
            raise ValueError(f"scheme_types must be unique values from {SCHEME_TYPES}")
    random = Random(config.seed ^ 0x5CE0A)
    builder = build_normal_builder(config)
    builder.add_efos_context(
        vendor=builder.estate.vendors[0], status="definitivo", publication_date=config.start_date
    )
    requested_schemes = (
        5 if all_five else scheme_count if scheme_count is not None else config.seed % 6
    )
    requested_decoys = decoy_count if decoy_count is not None else (config.seed * 3) % 11
    if not 0 <= requested_schemes <= 5 or not 0 <= requested_decoys <= 10:
        raise ValueError("scheme_count must be 0..5 and decoy_count must be 0..10")
    types = list(SCHEME_TYPES)
    random.shuffle(types)
    if scheme_types is None:
        selected = tuple(types) if all_five else tuple(types[:requested_schemes])
    scenarios = [_add_scheme(builder, kind, index + 1) for index, kind in enumerate(selected)]
    protected_entities = {entity for scenario in scenarios for entity in scenario.entities}
    # A revenue-cancellation decoy necessarily names the audited company.  When
    # that company is also planted with revenue inflation, calling it an honest
    # decoy would contaminate entity-level false-accusation scoring.
    decoy_types = [kind for kind in types if not (kind == "revenue_inflation" and any(
        scenario.scheme_type == "revenue_inflation" for scenario in scenarios
    ))]
    decoys = []
    for index in range(requested_decoys):
        decoy = _add_decoy(
            builder,
            decoy_types[index % len(decoy_types)],
            index + 1,
            excluded_entities=protected_entities,
        )
        decoys.append(decoy)
        protected_entities.add(decoy.entity)
    return ScenarioRun(estate=builder.estate, scenarios=scenarios, decoys=decoys)


def _add_scheme(builder: EstateEventBuilder, kind: str, index: int) -> PrivateScenario:
    event_date = _event_date(builder, index)
    amount_jitter = builder.random.randrange(-3_000, 3_001) * 100
    employee = builder.estate.employees[index % len(builder.estate.employees)]
    if kind == "phantom_vendor":
        vendor = builder.add_vendor(
            category="Consultoria",
            bank_clabe=employee.bank_clabe,
            allow_shared_account=True,
        )
        invoice = builder.record_purchase(
            vendor=vendor,
            event_date=event_date,
            subtotal_centavos=84_000_00 + amount_jitter,
            description=builder.random.choice(
                (
                    "Specialized operational-planning services",
                    "Technical planning assistance",
                )
            ),
            create_purchase_order=False,
        )
        builder.add_efos_context(
            vendor=vendor, status="presunto", publication_date=event_date + timedelta(days=1)
        )
        return _scenario(
            builder,
            kind,
            index,
            (f"RFC:{vendor.rfc}", employee.emp_id),
            (invoice,),
            invoice.total_centavos,
        )
    if kind == "kickback":
        shared = builder.config.observation_profile is ObservationProfile.COMPANY_ONLY
        vendor = builder.add_vendor(
            category="Mantenimiento",
            bank_clabe=employee.bank_clabe if shared else None,
            allow_shared_account=shared,
        )
        invoice = builder.record_purchase(
            vendor=vendor,
            event_date=event_date,
            subtotal_centavos=120_000_00 + amount_jitter,
            description=builder.random.choice(
                (
                    "Corrective maintenance for the production line",
                    "Urgent repair of manufacturing equipment",
                )
            ),
            requester=employee,
            approver=employee,
        )
        benefit = invoice.total_centavos // 10
        return_txn = (
            None
            if shared
            else builder.record_transfer(
                transfer_date=event_date + timedelta(days=12),
                from_clabe=vendor.bank_clabe,
                to_clabe=employee.bank_clabe,
                amount_centavos=benefit,
                reference=f"Professional services {invoice.uuid}",
            )
        )
        return _scenario(
            builder,
            kind,
            index,
            (f"RFC:{vendor.rfc}", employee.emp_id),
            (invoice,),
            (
                invoice.total_centavos
                if builder.config.observation_profile is ObservationProfile.COMPANY_ONLY
                else benefit
            ),
            (return_txn.txn_id,) if return_txn else (),
            illicit_benefit_centavos=benefit,
        )
    if kind == "round_tripping":
        vendor = builder.add_vendor(category="Logistica")
        invoice = builder.record_purchase(
            vendor=vendor,
            event_date=event_date,
            subtotal_centavos=75_000_00 + amount_jitter,
            description=builder.random.choice(
                (
                    "Regional delivery coordination",
                    "Exceptional route and shipment management",
                )
            ),
        )
        intermediary = builder._clabe(700_000 + index)
        builder.add_account(intermediary, holder_kind="counterparty", holder_id=f"EXT:{index}")
        first = builder.record_transfer(
            transfer_date=event_date + timedelta(days=12),
            from_clabe=vendor.bank_clabe,
            to_clabe=intermediary,
            amount_centavos=invoice.total_centavos,
            reference=f"Operational settlement {invoice.uuid}",
        )
        second = builder.record_transfer(
            transfer_date=event_date + timedelta(days=14),
            from_clabe=intermediary,
            to_clabe=builder.estate.company_clabe,
            amount_centavos=invoice.total_centavos - 500_00,
            reference=f"Treasury adjustment {invoice.uuid}",
        )
        return _scenario(
            builder,
            kind,
            index,
            (f"RFC:{vendor.rfc}",),
            (invoice,),
            invoice.total_centavos,
            (first.txn_id, second.txn_id),
        )
    if kind == "threshold_splitting":
        vendor = builder.add_vendor(category="Insumos")
        base_subtotal = builder.random.randrange(39_000, 46_001) * 100
        part_subtotals = tuple(
            base_subtotal + offset * builder.random.randrange(150, 701) * 100
            for offset in (-1, 0, 1)
        )
        aggregate_gross = sum(value + calculate_iva(value) for value in part_subtotals)
        contract = builder.add_contract(
            vendor=vendor,
            start_date=event_date,
            value_centavos=aggregate_gross,
            scope_text=(
                "Consolidated facility-upgrade obligation; combined amounts above MXN 100,000 "
                "require joint approval"
            ),
        )
        invoices: list[Invoice] = []
        for part, subtotal in enumerate(part_subtotals):
            invoices.append(
                builder.record_purchase(
                    vendor=vendor,
                    event_date=event_date + timedelta(days=part),
                    subtotal_centavos=subtotal,
                    description="Integrated facility-upgrade package for the northern site",
                    requester=employee,
                    approver=employee,
                    contract=contract,
                )
            )
        return _scenario(
            builder,
            kind,
            index,
            (f"RFC:{vendor.rfc}", employee.emp_id),
            tuple(invoices),
            sum(i.total_centavos for i in invoices),
        )
    if kind == "revenue_inflation":
        customer_rfc = builder._rfc(800_000 + index)
        customer_clabe = builder._clabe(800_000 + index)
        base_subtotal = builder.random.randrange(49_000, 62_001) * 100
        description = builder.random.choice(
            (
                "Commercial services invoiced on credit",
                "Business-expansion project invoiced on credit",
            )
        )
        invoices = [
            builder.record_sale(
                customer_rfc=customer_rfc,
                customer_clabe=customer_clabe,
                event_date=event_date + timedelta(days=part),
                subtotal_centavos=base_subtotal + part * 350_00,
                description=description,
                settle=False,
                status="cancelado",
            )
            for part in range(3)
        ]
        return _scenario(
            builder,
            kind,
            index,
            (f"RFC:{builder.estate.company_rfc}",),
            tuple(invoices),
            sum(i.total_centavos for i in invoices),
        )
    raise ValueError(f"unsupported scenario type: {kind}")


def _add_decoy(
    builder: EstateEventBuilder, kind: str, index: int, *, excluded_entities: set[str]
) -> PrivateDecoy:
    event_date = _event_date(builder, index + 10)
    eligible_employees = [
        employee
        for employee in builder.estate.employees
        if employee.emp_id not in excluded_entities
    ]
    if not eligible_employees:
        raise ValueError("no employee remains available for an isolated decoy")
    employee = eligible_employees[(index + 2) % len(eligible_employees)]
    if kind == "phantom_vendor":
        vendor = builder.add_vendor(category="Consultoria")
        builder.add_efos_context(vendor=vendor, status="presunto", publication_date=event_date)
        contract = builder.add_contract(
            vendor=vendor,
            start_date=event_date,
            value_centavos=150_000_00,
            scope_text="Documented advisory services",
        )
        invoice = builder.record_purchase(
            vendor=vendor, event_date=event_date, subtotal_centavos=75_000_00, contract=contract
        )
        return PrivateDecoy(
            f"RFC:{vendor.rfc}",
            "new_vendor",
            "Consistent contract, purchase order, invoice, and payment.",
            (invoice.uuid,),
        )
    if kind == "kickback":
        vendor = builder.add_vendor(category="Mantenimiento")
        invoice = builder.record_purchase(
            vendor=vendor, event_date=event_date, subtotal_centavos=60_000_00
        )
        builder.record_purchase_refund(
            invoice=invoice,
            vendor=vendor,
            refund_date=event_date + timedelta(days=12),
            amount_centavos=5_000_00,
        )
        return PrivateDecoy(
            f"RFC:{vendor.rfc}",
            "return_payment",
            "The return goes to the company and is identified as a refund.",
            (invoice.uuid,),
        )
    if kind == "round_tripping":
        vendor = builder.add_vendor(category="Logistica")
        invoice = builder.record_purchase(
            vendor=vendor, event_date=event_date, subtotal_centavos=40_000_00, status="cancelado"
        )
        builder.record_purchase_refund(
            invoice=invoice,
            vendor=vendor,
            refund_date=event_date + timedelta(days=12),
            amount_centavos=invoice.total_centavos,
        )
        return PrivateDecoy(
            f"RFC:{vendor.rfc}",
            "return_path",
            "Cancelled invoice with a visible accounting reversal.",
            (invoice.uuid,),
        )
    if kind == "threshold_splitting":
        invoices = []
        vendor = builder.add_vendor(category="Insumos")
        for part, scope in enumerate(
            ("Monthly maintenance", "Annual licence", "Safety supply")
        ):
            contract = builder.add_contract(
                vendor=vendor, start_date=event_date, value_centavos=42_500_00, scope_text=scope
            )
            invoices.append(
                builder.record_purchase(
                    vendor=vendor,
                    event_date=event_date + timedelta(days=part),
                    subtotal_centavos=42_500_00,
                    description=scope,
                    requester=employee,
                    approver=employee,
                    contract=contract,
                )
            )
        return PrivateDecoy(
            employee.emp_id,
            "near_limit_purchases",
            "Purchase orders from the same vendor show independent obligations and contracts.",
            tuple(i.uuid for i in invoices),
        )
    customer_rfc, clabe = builder._rfc(950_000 + index), builder._clabe(950_000 + index)
    invoice = builder.record_sale(
        customer_rfc=customer_rfc,
        customer_clabe=clabe,
        event_date=event_date,
        subtotal_centavos=55_000_00,
        description="Cancelled sale with reversal",
        settle=False,
        status="cancelado",
    )
    builder.reverse_cancelled_sale(invoice=invoice, reversal_date=event_date + timedelta(days=1))
    return PrivateDecoy(
        f"RFC:{builder.estate.company_rfc}",
        "cancelled_revenue",
        "The cancellation reverses revenue, IVA, and accounts receivable.",
        (invoice.uuid,),
    )


def _scenario(
    builder: EstateEventBuilder,
    kind: str,
    index: int,
    entities: tuple[str, ...],
    invoices: tuple[Invoice, ...],
    peso_centavos: int,
    extra_txns: tuple[str, ...] = (),
    illicit_benefit_centavos: int | None = None,
) -> PrivateScenario:
    invoice_txns = tuple(
        txn.txn_id
        for txn in builder.estate.bank_transactions
        if any(invoice.uuid in txn.reference for invoice in invoices)
    )
    needs_counterparty = kind in {"kickback", "round_tripping"}
    confidence = (
        "probable"
        if needs_counterparty
        and builder.config.observation_profile is ObservationProfile.COMPANY_ONLY
        else "proven"
    )
    transaction_ids = tuple(dict.fromkeys(invoice_txns + extra_txns))
    return PrivateScenario(
        f"S{index}_{kind}",
        kind,
        entities,
        tuple(invoice.uuid for invoice in invoices),
        transaction_ids,
        peso_centavos,
        "medium",
        confidence,
        illicit_benefit_centavos,
    )


def _event_date(builder: EstateEventBuilder, index: int) -> date:
    seed_jitter = (builder.config.seed * 17 + index * 7) % 4
    return min(
        builder.start_date + timedelta(days=35 + index * 4 + seed_jitter),
        builder.end_date - timedelta(days=15),
    )
