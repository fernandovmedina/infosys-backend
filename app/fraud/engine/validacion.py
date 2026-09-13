"""
Gate con el validador oficial (validate_format.py, copia sin modificar de
public/material/validate_format.py; tests/test_fraud lo verifica byte a byte).
Se importan sus funciones en el mismo proceso en vez de lanzar un subproceso.
El validador lee el estate con sqlite3, así que se exporta una copia SQLite
temporal de las 8 tablas del estate DuckDB.
"""

import importlib.util
import sqlite3
import tempfile
from pathlib import Path

import duckdb

from .catalogo import TABLE_PK

VALIDADOR = Path(__file__).resolve().parent / "validate_format.py"

TIPOS_SQLITE = {
    "INTEGER": "INTEGER",
    "BIGINT": "INTEGER",
    "SMALLINT": "INTEGER",
    "TINYINT": "INTEGER",
    "FLOAT": "REAL",
    "REAL": "REAL",
    "DOUBLE": "REAL",
    "DECIMAL": "REAL",
}


def _cargar_validador():
    spec = importlib.util.spec_from_file_location("validate_format", VALIDADOR)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


_validador = _cargar_validador()


def exportar_sqlite(con: duckdb.DuckDBPyConnection, destino: Path) -> None:
    with sqlite3.connect(destino) as sq:
        for tabla in TABLE_PK:
            columnas = con.execute(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_name = ? ORDER BY ordinal_position",
                [tabla],
            ).fetchall()
            if not columnas:
                continue
            ddl = ", ".join(
                f'"{c}" {TIPOS_SQLITE.get(t.split("(")[0], "TEXT")}' for c, t in columnas
            )
            # Nombres de tabla y columna salen del catálogo del estate, no de datos de usuario.
            sq.execute(f'CREATE TABLE "{tabla}" ({ddl})')
            nombres = ", ".join(f'"{c}"' for c, _ in columnas)
            filas = con.execute(f"SELECT {nombres} FROM {tabla}").fetchall()
            marcadores = ", ".join("?" for _ in columnas)
            sq.executemany(f'INSERT INTO "{tabla}" VALUES ({marcadores})', filas)


def validar(con: duckdb.DuckDBPyConnection, submission: dict) -> tuple[bool, list[str]]:
    """Estructura + registros citados contra el estate. Devuelve (pasó, errores del validador)."""
    errores = _validador.validate_structure(submission)
    with tempfile.TemporaryDirectory() as tmp:
        estate_sqlite = Path(tmp) / "estate.db"
        exportar_sqlite(con, estate_sqlite)
        errores += _validador.validate_against_estate(submission, str(estate_sqlite))
    return not errores, errores
