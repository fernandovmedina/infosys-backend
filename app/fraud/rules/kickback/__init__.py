"""
Reglas del módulo 2 (kickback) que ejecuta el runner.

No se registran: vendor_employee_name_similarity (similitud de texto, fuera
del alcance SQL), efos_definitive_match (duplica EFOS_DIRECT_MATCH del
módulo 1) y efos_presunto_match (archivo vacío).
"""

from .approver_vendor_concentration import rule_approver_vendor_concentration
from .no_segregation_of_duties import rule_no_segregation_of_duties
from .payment_to_employee_account import rule_payment_to_employee_account
from .price_outlier_by_category import rule_price_outlier_by_category

RULES = [
    rule_payment_to_employee_account,
    rule_approver_vendor_concentration,
    rule_no_segregation_of_duties,
    rule_price_outlier_by_category,
]
