"""Reglas del módulo 1 (proveedores fantasma EFOS/EDOS) que ejecuta el runner."""

from .efos_direct_match import rule_efos_direct_match
from .efos_post_dated import rule_efos_post_dated
from .efos_presunto_match import rule_efos_presunto_match
from .invoice_no_po_no_contract import rule_invoice_no_po_no_contract
from .shared_clabe_multi_rfc import rule_shared_clabe_multi_rfc
from .vendor_short_lifecycle import rule_vendor_short_lifecycle

RULES = [
    rule_efos_direct_match,
    rule_efos_presunto_match,
    rule_efos_post_dated,
    rule_vendor_short_lifecycle,
    rule_invoice_no_po_no_contract,
    rule_shared_clabe_multi_rfc,
]
