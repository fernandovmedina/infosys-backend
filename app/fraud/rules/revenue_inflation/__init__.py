"""Reglas del módulo 5 (revenue inflation) que ejecuta el runner."""

from .ar_aging_excessive import rule_ar_aging_excessive
from .inflate_and_cancel import rule_inflate_and_cancel

RULES = [
    rule_inflate_and_cancel,
    rule_ar_aging_excessive,
]
