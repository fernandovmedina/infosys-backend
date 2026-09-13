"""Reglas del módulo 4 (threshold splitting) que ejecuta el runner."""

from .contract_split_into_pos import rule_contract_split_into_pos
from .same_approver_split import rule_same_approver_split

RULES = [
    rule_same_approver_split,
    rule_contract_split_into_pos,
]
