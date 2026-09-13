"""Reglas del módulo 6 (integridad de datos, capa 1) que ejecuta el runner."""

from .clabe_invalid_length import rule_clabe_invalid_length
from .ledger_unbalanced_entry import rule_ledger_unbalanced_entry
from .malformed_rfc import rule_malformed_rfc
from .orphan_invoice_uuid import rule_orphan_invoice_uuid

RULES = [
    rule_ledger_unbalanced_entry,
    rule_orphan_invoice_uuid,
    rule_malformed_rfc,
    rule_clabe_invalid_length,
]
