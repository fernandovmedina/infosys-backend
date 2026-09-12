"""DuckDB connection access for ad-hoc analysis scripts.

DuckDB runs in-process and is synchronous; there is no pool and no FastAPI
startup wiring. Open a connection where the analysis runs and close it when
done (or let the script exit).
"""

from __future__ import annotations

import duckdb


def connect(path: str | None = None) -> duckdb.DuckDBPyConnection:
    """Open an in-memory DuckDB (default) or a file-backed database."""
    return duckdb.connect(path or ":memory:")
