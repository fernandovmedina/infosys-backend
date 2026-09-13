"""Exact-cent accounting helpers used by normal business events."""

from __future__ import annotations

from collections.abc import Iterable

from app.estate_generator.models import Centavos, LedgerLine

IVA_RATE_NUMERATOR = 16
IVA_RATE_DENOMINATOR = 100


def calculate_iva(subtotal_centavos: Centavos) -> Centavos:
    """Return the challenge profile's 16% IVA, rounded exactly to a cent."""
    return subtotal_centavos * IVA_RATE_NUMERATOR // IVA_RATE_DENOMINATOR


def assert_balanced(lines: Iterable[LedgerLine]) -> None:
    """Raise when a single accounting event is not balanced in centavos."""
    materialized = tuple(lines)
    debit = sum(line.debit_centavos for line in materialized)
    credit = sum(line.credit_centavos for line in materialized)
    if debit != credit:
        event_ids = sorted({line.event_id for line in materialized})
        raise ValueError(f"unbalanced journal event {event_ids}: {debit} != {credit}")


def assert_non_negative_amount(amount_centavos: Centavos, *, label: str) -> None:
    if amount_centavos <= 0:
        raise ValueError(f"{label} must be positive centavos")
