from pathlib import Path

import duckdb
import pytest

from app.fraud.engine.esquema import TABLES
from app.fraud.engine.ingesta import COLUMNAS, archivos_en_carpeta, cargar_csvs

RAIZ = Path(__file__).resolve().parents[2]
ESCENARIO_1301 = RAIZ / "tests" / "fixtures" / "fraud" / "seed1301"


@pytest.fixture
def con():
    """Estate DuckDB en memoria con las 8 tablas vacías."""
    conexion = duckdb.connect()
    for ddl in TABLES.values():
        conexion.execute(ddl)
    yield conexion
    conexion.close()


@pytest.fixture
def insertar(con):
    """insertar('tabla', {col: valor, ...}, ...) con las columnas faltantes en NULL."""

    def _insertar(tabla: str, *filas: dict[str, object]) -> None:
        columnas = COLUMNAS[tabla]
        for fila in filas:
            desconocidas = set(fila) - set(columnas)
            assert not desconocidas, f"columnas que no existen en {tabla}: {desconocidas}"
            con.execute(
                f"INSERT INTO {tabla} ({', '.join(columnas)}) "
                f"VALUES ({', '.join('?' for _ in columnas)})",
                [fila.get(c) for c in columnas],
            )

    return _insertar


@pytest.fixture(scope="session")
def con_1301():
    conexion = duckdb.connect()
    cargar_csvs(conexion, archivos_en_carpeta(ESCENARIO_1301))
    yield conexion
    conexion.close()
