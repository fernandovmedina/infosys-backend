"""
Traductor Finding interno -> submission.json. Aplica las autoverificaciones
(registros existentes, peso reconciliado, 3 exhibits, 150 palabras) antes de
emitir: una acusación que no valida no se imprime.
"""

from .catalogo import MAX_PALABRAS_NARRATIVA, MIN_EXHIBITS, RULE_BROKEN
from .ensamblador import Ensamblador, FindingInterno
from .entidades import format_entity_id
from .evidencia import (
    assert_exhibits_exist,
    build_money_trail,
    montos_por_tabla,
    publicar_exhibits,
    self_check_peso_reconciliation,
)
from .metricas import RunMetrics
from .narrativa import redactar


def traducir_finding(ensamblador: Ensamblador, fi: FindingInterno) -> tuple[dict, dict]:
    """Devuelve (finding publicable, anexo para el case file)."""
    cl = fi.cluster
    estate = ensamblador.estate
    assert_exhibits_exist(estate, fi.exhibits)
    if len(fi.exhibits) < MIN_EXHIBITS:
        raise ValueError(
            f"Finding de {cl.esquema} con {len(fi.exhibits)} exhibits (mínimo {MIN_EXHIBITS})"
        )
    if not self_check_peso_reconciliation(fi.peso_amount, fi.exhibits):
        raise ValueError(
            f"peso_amount {fi.peso_amount} no reconcilia con {montos_por_tabla(fi.exhibits)}"
        )

    etiquetas = [ensamblador.etiqueta(e) for e in cl.acusables]
    narrativa = redactar(
        cl.esquema,
        etiquetas,
        cl.familias,
        fi.peso_amount,
        fi.tabla_monto,
        fi.exhibits,
        fi.confidence,
    )
    if len(narrativa.split()) > MAX_PALABRAS_NARRATIVA:
        raise ValueError("Narrativa excede el máximo de palabras")

    finding = {
        "scheme_type": cl.esquema,
        "entities": [format_entity_id(e.canonico, e.tipo) for e in cl.acusables],
        "narrative": narrativa,
        "rule_broken": RULE_BROKEN[cl.esquema],
        "peso_amount": fi.peso_amount,
        "money_trail": build_money_trail(ensamblador.resolutor, fi.exhibits),
        "exhibits": publicar_exhibits(fi.exhibits),
        "confidence": fi.confidence,
    }
    anexo = {
        "nombres": {
            format_entity_id(e.canonico, e.tipo): ensamblador.nombre(e) for e in cl.acusables
        },
        "reglas": cl.reglas,
        "tabla_monto": fi.tabla_monto,
        "reconciliacion": {
            tabla: [
                (ex["exhibit_id"], ex["record_id"], round(ex["_monto"] or 0.0, 2))
                for ex in fi.exhibits
                if ex["source_table"] == tabla
            ]
            for tabla in sorted(montos_por_tabla(fi.exhibits))
        },
    }
    return finding, anexo


def build_submission(
    seed: int, findings: list[dict], leads: list[dict], metrics: RunMetrics
) -> dict:
    return {
        "seed": seed,
        "findings": findings,
        "leads_not_pursued": leads,
        "run_metadata": metrics.finalize(),
    }
