"""Reglas del módulo 3 (round tripping) que ejecuta el runner."""

from .bank_cycle_2node import rule_bank_cycle_2node
from .bank_cycle_nnode import rule_bank_cycle_nnode
from .bank_txn_not_in_ledger import rule_bank_txn_not_in_ledger
from .cycle_leakage_rate import rule_cycle_leakage_rate
from .invoice_bidirectional import rule_invoice_bidirectional
from .outbound_to_suspect_entity import rule_outbound_to_suspect_entity

RULES = [
    rule_bank_cycle_2node,
    rule_bank_cycle_nnode,
    rule_cycle_leakage_rate,
    rule_outbound_to_suspect_entity,
    rule_invoice_bidirectional,
    rule_bank_txn_not_in_ledger,
]
