"""
Narrativa determinista por plantilla: interpola los campos ya calculados del
Finding. No decide nada; solo redacta en lenguaje llano, en 150 palabras o menos.
"""

from .catalogo import FRASE_FAMILIA, MAX_PALABRAS_NARRATIVA, NOMBRE_ESQUEMA
from .evidencia import pesos

TABLA_LLANA = {
    "invoices": "invoices",
    "bank_txns": "bank transfers",
    "purchase_orders": "purchase orders",
    "contracts": "contracts",
}

CONFIANZA_LLANA = {
    "proven": "We consider this proven: at least one record independently establishes the fact.",
    "probable": (
        "We consider this probable: several independent signals point to the same conclusion, but "
        "documents outside the accounting records are needed to confirm that the transaction did not occur."
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
            nombres += f" and {len(etiquetas) - max_entidades} more"
        hechos = "; additionally, ".join(FRASE_FAMILIA[f] for f in familias[:max_familias])
        periodo = (
            f"between {fechas[0]} and {fechas[-1]}"
            if n > 1 and fechas[0] != fechas[-1]
            else f"on {fechas[0]}"
        )
        return (
            " ".join(
                [
                    f"Potential {NOMBRE_ESQUEMA[esquema]} involving {nombres}.",
                    f"The records show that it {hechos}." if hechos else "",
                    f"The amount at issue is {pesos(peso)}, the total of {n} {TABLA_LLANA[tabla_monto]} ({periodo}).",
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
