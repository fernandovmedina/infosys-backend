"""
Runner del motor: ejecuta las reglas registradas en `app.fraud.rules.RULES`
contra un estate DuckDB y valida el contrato de cada Signal.

Portado de motor-agente-forense `src/agente/runner.py`. Cambios: las reglas se
cargan desde el registro explícito del paquete (antes, importlib sobre las
carpetas numeradas de src/rules/) y se quitaron el script CLI y `guardar_signals`
(escribían los Signals en la tabla `signals` de un archivo DuckDB; aquí los
Signals se guardan en PostgreSQL, ver app/fraud/repository.py).
"""

import json

import duckdb
import pandas as pd

from app.fraud.rules import RULES as RULES

COLUMNAS_CONTRATO = [
    "rule_id",
    "source_table",
    "entity_id",
    "evidence_id",
    "fecha_deteccion",
    "severidad",
    "autosuficiencia",
    "monto",
]
SEVERIDADES = {"alta", "media", "baja"}
AUTOSUFICIENCIAS = {"autosuficiente", "presuntiva"}


def cargar_reglas() -> list:
    """Las reglas de todos los módulos, en el orden de la referencia (carpetas 1 → 6)."""
    return list(RULES)


def nombre_regla(regla) -> str:
    return getattr(regla, "__name__", repr(regla))


def validar_contrato(df: pd.DataFrame) -> list[str]:
    """Devuelve la lista de violaciones del contrato de Signal (vacía si cumple)."""
    errores = []
    if list(df.columns[: len(COLUMNAS_CONTRATO)]) != COLUMNAS_CONTRATO:
        errores.append(f"columnas iniciales {list(df.columns[:8])} != {COLUMNAS_CONTRATO}")
        return errores
    if df["rule_id"].nunique(dropna=False) > 1:
        errores.append(f"rule_id no constante: {sorted(df['rule_id'].astype(str).unique())}")
    invalidas = set(df["severidad"]) - SEVERIDADES
    if invalidas:
        errores.append(f"invalid severity: {sorted(map(str, invalidas))}")
    invalidas = set(df["autosuficiencia"]) - AUTOSUFICIENCIAS
    if invalidas:
        errores.append(f"invalid self-sufficiency: {sorted(map(str, invalidas))}")
    return errores


def a_signals(df: pd.DataFrame) -> pd.DataFrame:
    """Deja las columnas del contrato y empaqueta las extra en `contexto` (JSON)."""
    extra = [c for c in df.columns if c not in COLUMNAS_CONTRATO]
    salida = df[COLUMNAS_CONTRATO].copy()
    if extra and not df.empty:
        # to_json convierte NaN, tipos numpy y fechas a JSON válido.
        registros = json.loads(df[extra].to_json(orient="records", date_format="iso"))
        salida["contexto"] = [json.dumps(r, ensure_ascii=False) for r in registros]
    else:
        salida["contexto"] = None
    return salida


def ejecutar_reglas(
    con: duckdb.DuckDBPyConnection, reglas: list
) -> tuple[pd.DataFrame, list[tuple[str, str]], list[tuple[str, int]]]:
    """
    Corre cada regla con la conexión. Una regla que lanza excepción o rompe el
    contrato no detiene la corrida: se reporta en `fallos` y sus filas no se
    guardan. Devuelve (signals concatenados, fallos, filas por regla).
    """
    partes, fallos, resumen = [], [], []
    for regla in reglas:
        nombre = nombre_regla(regla)
        try:
            df = regla(con)
        except Exception as exc:
            fallos.append((nombre, f"{type(exc).__name__}: {exc}"))
            continue
        errores = validar_contrato(df)
        if errores:
            fallos.append((nombre, "; ".join(errores)))
            continue
        resumen.append((nombre, len(df)))
        if not df.empty:
            partes.append(a_signals(df))

    columnas = COLUMNAS_CONTRATO + ["contexto"]
    signals = pd.concat(partes, ignore_index=True) if partes else pd.DataFrame(columns=columnas)
    return signals[columnas], fallos, resumen
