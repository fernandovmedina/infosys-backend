"""Fraud-detection rules, one package per scheme family.

Ported from motor-agente-forense `src/rules/<n>_<bloque>/`. The numbered folders
there could only be loaded with importlib; here each became a regular package
and its `registro.py` became the package `__init__` exposing `RULES`. `RULES`
below keeps the reference execution order (folders 1 → 6), which the engine's
output order depends on.
"""

from __future__ import annotations

from app.fraud.rules import (
    data_integrity,
    kickback,
    phantom_vendor,
    revenue_inflation,
    round_tripping,
    threshold_splitting,
)

REGISTRIES = (
    phantom_vendor,  # 1_proveedores_fantasma_efos_edos
    kickback,  # 2_kickback
    round_tripping,  # 3_round_tripping
    threshold_splitting,  # 4_threshold_splitting
    revenue_inflation,  # 5_revenue_inflation
    data_integrity,  # 6_integridad_datos_capa_1
)

RULES = [rule for registry in REGISTRIES for rule in registry.RULES]
