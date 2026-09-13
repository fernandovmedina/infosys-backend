"""Determinism and public business-record tests."""

from __future__ import annotations

from datetime import date

import pytest

from app.estate_generator.checks import validate_public_estate
from app.estate_generator.config import EstateGeneratorConfig
from app.estate_generator.generator import generate_estate
from app.estate_generator.normal_business import EstateEventBuilder


def test_same_seed_generates_same_public_records() -> None:
    first = generate_estate(EstateGeneratorConfig(seed=101, normal_event_count=30))
    second = generate_estate(EstateGeneratorConfig(seed=101, normal_event_count=30))

    assert first.vendors == second.vendors
    assert first.purchase_orders == second.purchase_orders
    assert first.invoices == second.invoices
    assert first.ledger == second.ledger
    assert first.bank_transactions == second.bank_transactions


def test_normal_estate_has_recurring_contracts_credit_sales_and_grouped_orders() -> None:
    estate = generate_estate(EstateGeneratorConfig(seed=5, normal_event_count=30))

    assert len(estate.contracts) == 3
    assert estate.purchase_order_contracts
    assert any(invoice.issuer_rfc == estate.company_rfc for invoice in estate.invoices)
    assert any(invoice.issuer_rfc != estate.company_rfc for invoice in estate.invoices)
    assert estate.accounts[estate.company_clabe].holder_kind == "company"


def test_different_seeds_change_public_identities_and_clabes() -> None:
    first = generate_estate(EstateGeneratorConfig(seed=5, normal_event_count=30))
    second = generate_estate(EstateGeneratorConfig(seed=6, normal_event_count=30))

    assert first.company_rfc != second.company_rfc
    assert first.company_clabe != second.company_clabe
    assert first.employees[0].emp_id != second.employees[0].emp_id
    assert first.vendors[0].rfc != second.vendors[0].rfc
    assert first.vendors[0].bank_clabe != second.vendors[0].bank_clabe


@pytest.mark.parametrize(
    "config",
    [
        EstateGeneratorConfig(seed=1, end_date=date(2025, 12, 31)),
        EstateGeneratorConfig(seed=1, vendor_count=2),
        EstateGeneratorConfig(seed=1, employee_count=1),
        EstateGeneratorConfig(seed=1, normal_event_count=21),
    ],
)
def test_invalid_configs_fail_before_generating_records(config: EstateGeneratorConfig) -> None:
    with pytest.raises(ValueError):
        generate_estate(config)


def test_event_builder_extends_normal_activity_without_identifier_collisions() -> None:
    builder = EstateEventBuilder(EstateGeneratorConfig(seed=7, normal_event_count=30))
    estate = builder.build_normal_activity()
    vendor = builder.add_vendor(category="Consultoria")
    contract = builder.add_contract(
        vendor=vendor,
        start_date=date(2026, 2, 1),
        value_centavos=100_000,
        scope_text="Asesoria especializada",
    )
    invoice = builder.record_purchase(
        vendor=vendor,
        event_date=date(2026, 2, 2),
        subtotal_centavos=50_000,
        contract=contract,
    )
    external = builder._clabe(999_999)
    builder.add_account(external, holder_kind="counterparty", holder_id="EXT:1")
    transaction = builder.record_transfer(
        transfer_date=date(2026, 2, 3),
        from_clabe=vendor.bank_clabe,
        to_clabe=external,
        amount_centavos=10_000,
        reference="Transferencia entre terceros",
    )

    assert invoice.uuid in estate.payable_balances
    assert transaction.txn_id in {item.txn_id for item in estate.bank_transactions}
    assert len({item.uuid for item in estate.invoices}) == len(estate.invoices)


@pytest.mark.parametrize("event_date", [date(2025, 12, 31), date(2026, 7, 1)])
def test_event_api_rejects_dates_outside_observation_window(event_date: date) -> None:
    builder = EstateEventBuilder(EstateGeneratorConfig(seed=7, normal_event_count=30))
    estate = builder.build_normal_activity()

    with pytest.raises(ValueError):
        builder.record_purchase(
            vendor=estate.vendors[0],
            event_date=event_date,
            subtotal_centavos=10_000,
        )
    with pytest.raises(ValueError):
        builder.record_transfer(
            transfer_date=event_date,
            from_clabe=estate.company_clabe,
            to_clabe=estate.vendors[0].bank_clabe,
            amount_centavos=10_000,
            reference="Fecha invalida",
        )


def test_validation_rejects_an_outflow_before_the_account_was_funded() -> None:
    builder = EstateEventBuilder(EstateGeneratorConfig(seed=77, normal_event_count=30))
    estate = builder.build_normal_activity()
    vendor = builder.add_vendor(category="Consultoria")
    recipient_clabe = builder._clabe(999_998)
    builder.add_account(recipient_clabe, holder_kind="counterparty", holder_id="EXT:chronology")
    builder.record_transfer(
        transfer_date=date(2026, 2, 10),
        from_clabe=estate.company_clabe,
        to_clabe=vendor.bank_clabe,
        amount_centavos=10_000,
        reference="Fondeo posterior",
    )
    builder.record_transfer(
        transfer_date=date(2026, 2, 1),
        from_clabe=vendor.bank_clabe,
        to_clabe=recipient_clabe,
        amount_centavos=10_000,
        reference="Salida anterior imposible",
    )

    with pytest.raises(ValueError, match="insufficient chronological funds"):
        validate_public_estate(estate)
