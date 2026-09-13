"""
Ingesta: carga los 8 CSV de una empresa (vendors.csv, invoices.csv, ...) en una
conexión DuckDB con el esquema del estate. La usan la API, scripts/cargar_csv.py
y las pruebas.

Antes de cargar valida que estén todos los archivos y que sus encabezados sean
exactamente las columnas del esquema (en cualquier orden). Todo se lee como texto
y se castea al tipo de la tabla en el INSERT, así los RFC, CLABE y códigos
('03') no pierden ceros; un monto o id que no se puede convertir se reporta
como error del archivo en vez de cargarse a medias. Si algo falla no queda
nada cargado (transacción).
"""

import csv
from dataclasses import dataclass
from pathlib import Path

import duckdb

from .esquema import TABLES


@dataclass(frozen=True)
class ErrorIngesta:
    archivo: str
    columna: str | None
    mensaje: str

    def a_dict(self) -> dict:
        return {"archivo": self.archivo, "columna": self.columna, "mensaje": self.mensaje}


class IngestaInvalida(ValueError):
    def __init__(self, errores: list[ErrorIngesta]):
        self.errores = errores
        super().__init__("; ".join(f"{e.archivo}: {e.mensaje}" for e in errores))


def _columnas_esquema() -> dict[str, list[tuple[str, str]]]:
    """{tabla: [(columna, tipo DuckDB), ...]} en el orden del esquema."""
    with duckdb.connect() as con:
        columnas = {}
        for tabla, ddl in TABLES.items():
            con.execute(ddl)
            columnas[tabla] = [
                (c[1], c[2]) for c in con.execute(f"PRAGMA table_info('{tabla}')").fetchall()
            ]
    return columnas


TIPOS = _columnas_esquema()
COLUMNAS = {tabla: [c for c, _ in cols] for tabla, cols in TIPOS.items()}
LECTURA_CSV = "read_csv(?, header = true, all_varchar = true, encoding = 'utf-8')"


def archivos_en_carpeta(carpeta: Path) -> dict[str, Path]:
    """{tabla: carpeta/<tabla>.csv} para los archivos que existen."""
    return {t: carpeta / f"{t}.csv" for t in TABLES if (carpeta / f"{t}.csv").is_file()}


def _encabezado(ruta: Path) -> list[str] | None:
    try:
        with ruta.open(newline="", encoding="utf-8-sig") as fh:
            fila = next(csv.reader(fh), None)
    except OSError, UnicodeDecodeError, csv.Error:
        return None
    return [c.strip() for c in fila] if fila else None


def validar_archivos(archivos: dict[str, Path]) -> list[ErrorIngesta]:
    errores = []
    for tabla, esperadas in COLUMNAS.items():
        nombre = f"{tabla}.csv"
        ruta = archivos.get(tabla)
        if ruta is None or not Path(ruta).is_file():
            errores.append(ErrorIngesta(nombre, None, "file is missing"))
            continue
        encabezado = _encabezado(Path(ruta))
        if encabezado is None:
            errores.append(
                ErrorIngesta(nombre, None, "could not be read as a UTF-8 CSV with a header")
            )
            continue
        for col in esperadas:
            if col not in encabezado:
                errores.append(ErrorIngesta(nombre, col, "column is missing"))
        for col in encabezado:
            if col not in esperadas:
                errores.append(ErrorIngesta(nombre, col, "column does not exist in the schema"))
        if len(set(encabezado)) != len(encabezado):
            errores.append(ErrorIngesta(nombre, None, "header has repeated columns"))
    extra = sorted(set(archivos) - set(TABLES))
    for tabla in extra:
        errores.append(
            ErrorIngesta(f"{tabla}.csv", None, "archivo que no corresponde a ninguna tabla")
        )
    return errores


def cargar_csvs(
    con: duckdb.DuckDBPyConnection, archivos: dict[str, Path], max_filas: int | None = None
) -> dict[str, int]:
    """
    Crea (si hace falta), vacía y llena las 8 tablas. Devuelve filas por tabla.
    Lanza IngestaInvalida con todos los errores encontrados.
    """
    errores = validar_archivos(archivos)
    if errores:
        raise IngestaInvalida(errores)

    errores = _revisar_contenido(con, archivos, max_filas)
    if errores:
        raise IngestaInvalida(errores)

    conteos = {}
    con.execute("BEGIN")
    try:
        for tabla, ddl in TABLES.items():
            con.execute(ddl)
            # Tabla y columnas vienen del esquema, no del CSV: por eso van en f-string.
            lista = ", ".join(COLUMNAS[tabla])
            con.execute(f"DELETE FROM {tabla}")
            con.execute(
                f"INSERT INTO {tabla} ({lista}) SELECT {lista} FROM {LECTURA_CSV}",
                [str(archivos[tabla])],
            )
            conteos[tabla] = con.execute(f"SELECT COUNT(*) FROM {tabla}").fetchone()[0]
    except BaseException:
        con.execute("ROLLBACK")
        raise
    con.execute("COMMIT")
    return conteos


def _revisar_contenido(
    con: duckdb.DuckDBPyConnection, archivos: dict[str, Path], max_filas: int | None
) -> list[ErrorIngesta]:
    """CSV legible, límite de filas y valores convertibles al tipo de cada columna no textual."""
    errores = []
    for tabla, columnas in TIPOS.items():
        nombre, ruta = f"{tabla}.csv", str(archivos[tabla])
        try:
            filas = con.execute(f"SELECT COUNT(*) FROM {LECTURA_CSV}", [ruta]).fetchone()[0]
        except duckdb.Error as exc:
            errores.append(
                ErrorIngesta(nombre, None, f"could not be read: {str(exc).splitlines()[0]}")
            )
            continue
        if max_filas is not None and filas > max_filas:
            errores.append(ErrorIngesta(nombre, None, f"{filas} rows; maximum is {max_filas}"))
            continue
        for columna, tipo in columnas:
            if tipo in ("VARCHAR", "TEXT"):
                continue
            # Columna y tipo salen del esquema, no del CSV.
            malo = con.execute(
                f"SELECT {columna} FROM {LECTURA_CSV} "
                f"WHERE {columna} IS NOT NULL AND TRY_CAST({columna} AS {tipo}) IS NULL LIMIT 1",
                [ruta],
            ).fetchone()
            if malo:
                errores.append(
                    ErrorIngesta(nombre, columna, f"value {malo[0]!r} is not valid {tipo}")
                )
    return errores
