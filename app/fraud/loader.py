"""Load a run's stored dataset into a DuckDB estate the fraud engine can audit.

`POST /fraud/analyze` uses the engine's own strict ingestion
(`app.fraud.engine.ingesta.cargar_csvs`), which refuses any file or column that
differs from the estate schema. A run is different: its upload was already
diagnosed by `app.runs.ingest`, which only blocks the run when a *required*
table is unusable and reports everything else as warnings the user accepted.
Refusing those warnings here would make them blocking after the fact, so this
loader keeps the same table DDL and text-then-cast approach but tolerates what
the diagnostics tolerate:

* a missing optional table is created empty (its detectors return no signals);
* a missing column is loaded as NULL; extra columns are ignored;
* a value that does not cast to its column type becomes NULL, and thousands
  separators in numeric columns are removed first (the diagnostics accept
  `1,234.50` as a number).

For a dataset that already matches the schema the resulting tables are the same
as `cargar_csvs` builds, so the engine's output is identical.
"""

from __future__ import annotations

import csv
from pathlib import Path

import duckdb

from app.fraud.engine.esquema import TABLES
from app.fraud.engine.ingesta import LECTURA_CSV, TIPOS

_TEXT_TYPES = ("VARCHAR", "TEXT")


def _header(path: Path) -> list[str]:
    with path.open(newline="", encoding="utf-8") as handle:
        return next(csv.reader(handle), [])


def _projection(columns: list[tuple[str, str]], present: set[str]) -> str:
    parts = []
    for column, sql_type in columns:
        # Column names and types come from the estate schema, never from the file.
        if column not in present:
            parts.append(f"CAST(NULL AS {sql_type})")
        elif sql_type in _TEXT_TYPES:
            parts.append(f'"{column}"')
        else:
            parts.append(f"TRY_CAST(REPLACE(\"{column}\", ',', '') AS {sql_type})")
    return ", ".join(parts)


def load_run_tables(con: duckdb.DuckDBPyConnection, directory: Path) -> dict[str, int]:
    """Create the eight estate tables in `con` from `directory/<table>.csv`. Rows per table."""
    counts: dict[str, int] = {}
    con.execute("BEGIN")
    try:
        for table, ddl in TABLES.items():
            con.execute(ddl)
            path = directory / f"{table}.csv"
            if path.is_file():
                columns = TIPOS[table]
                names = ", ".join(column for column, _ in columns)
                projection = _projection(columns, set(_header(path)))
                con.execute(
                    f"INSERT INTO {table} ({names}) SELECT {projection} FROM {LECTURA_CSV}",
                    [str(path)],
                )
            row = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
            counts[table] = int(row[0]) if row else 0
    except BaseException:
        con.execute("ROLLBACK")
        raise
    con.execute("COMMIT")
    return counts
