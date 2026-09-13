"""
Narrativa determinista por plantilla: interpola los campos ya calculados del
Finding. No decide nada; solo redacta en lenguaje llano, en 150 palabras o menos.
"""

from .catalogo import FRASE_FAMILIA, MAX_PALABRAS_NARRATIVA, NOMBRE_ESQUEMA
from .evidencia import pesos

TABLA_LLANA = {
    "invoices": "facturas",
    "bank_txns": "transferencias bancarias",
    "purchase_orders": "órdenes de compra",
    "contracts": "contratos",
}

CONFIANZA_LLANA = {
    "proven": "Lo consideramos probado: al menos uno de los registros demuestra el hecho por sí solo.",
    "probable": (
        "Lo consideramos probable: varias señales independientes apuntan a lo mismo, pero hace falta "
        "confirmar con documentos fuera de la contabilidad que la operación no existió."
    ),
}


def _palabras(texto: str) -> int:
    return len(texto.split())


def redactar(
    esquema: str,
    etiquetas: list[str],
    familias: list[str],
    peso: float,
    tabla_monto: str,
    exhibits: list[dict],
    confidence: str,
) -> str:
    fechas = sorted(e["_fecha"] for e in exhibits if e["source_table"] == tabla_monto)
    n = len(fechas)

    def armar(max_entidades: int, max_familias: int) -> str:
        nombres = ", ".join(etiquetas[:max_entidades])
        if len(etiquetas) > max_entidades:
            nombres += f" y {len(etiquetas) - max_entidades} más"
        hechos = "; además, ".join(FRASE_FAMILIA[f] for f in familias[:max_familias])
        periodo = (
            f"entre el {fechas[0]} y el {fechas[-1]}"
            if n > 1 and fechas[0] != fechas[-1]
            else f"el {fechas[0]}"
        )
        return (
            " ".join(
                [
                    f"Posible {NOMBRE_ESQUEMA[esquema]} que involucra a {nombres}.",
                    f"Los registros muestran que {hechos}." if hechos else "",
                    f"El monto en juego es {pesos(peso)}, la suma de {n} {TABLA_LLANA[tabla_monto]} ({periodo}).",
                    CONFIANZA_LLANA[confidence],
                ]
            )
            .replace("  ", " ")
            .strip()
        )

    for max_ent, max_fam in ((len(etiquetas), len(familias)), (3, len(familias)), (2, 2), (1, 1)):
        texto = armar(max_ent, max_fam)
        if _palabras(texto) <= MAX_PALABRAS_NARRATIVA:
            return texto
    return " ".join(texto.split()[:MAX_PALABRAS_NARRATIVA])
