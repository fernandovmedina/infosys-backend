"""Focused normal-business accounting tests."""

from __future__ import annotations

from collections import defaultdict

from app.estate_generator.accounting import assert_balanced
from app.estate_generator.config import EstateGeneratorConfig
from app.estate_generator.generator import generate_estate


def test_every_internal_journal_event_is_balanced_and_invoices_reconcile() -> None:
    estate = generate_estate(EstateGeneratorConfig(seed=17, normal_event_count=30))
    events: dict[str, list] = defaultdict(list)
    for line in estate.ledger:
        events[line.event_id].append(line)
    for lines in events.values():
        assert_balanced(lines)
    for invoice in estate.invoices:
        assert invoice.subtotal_centavos + invoice.iva_centavos == invoice.total_centavos


def test_partial_settlements_and_cancelled_invoice_are_explainable() -> None:
    estate = generate_estate(EstateGeneratorConfig(seed=22, normal_event_count=30))
    payments_per_invoice: dict[str, int] = defaultdict(int)
    for transaction in estate.bank_transactions:
        if transaction.reference.startswith("Invoice payment "):
            payments_per_invoice[transaction.reference.removeprefix("Invoice payment ")] += 1

    assert any(count == 2 for count in payments_per_invoice.values())
    assert all(balance >= 0 for balance in estate.payable_balances.values())
    cancelled = [invoice for invoice in estate.invoices if invoice.status == "cancelado"]
    assert len(cancelled) == 1
    assert cancelled[0].uuid in estate.cancellation_reversals
    assert estate.payable_balances[cancelled[0].uuid] == 0
