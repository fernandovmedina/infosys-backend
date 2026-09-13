"""Reusable importer that seeds the SAT blacklist from ``black_list.csv``.

Design notes
------------
* The published file is **cp1252**, not UTF-8, and carries two preamble lines
  (a legal notice and a title) before the real header row. The header is located
  by looking for the ``RFC`` column rather than by hard-coding a line number, so
  a future snapshot with a different preamble still imports.
* Rows are normalized in Python with :mod:`app.sat.normalization` and streamed
  into ``sat_blacklist_staging`` with ``COPY``, then merged by
  ``sat_blacklist_merge_staging()`` in one set-based statement. There is never one INSERT per row.
* ``source_hash`` (SHA-256 of the row minus its sequence number) makes the whole
  run idempotent and collapses the exact duplicates the source file contains.
* A malformed row never aborts the run: it is counted, reported with its line
  number and reason, and the import continues.

Usage::

    uv run sat-blacklist-import
    uv run sat-blacklist-import --csv /path/to/snapshot.csv
    uv run sat-blacklist-import --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import datetime as dt
import hashlib
import logging
import sys
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import asyncpg

from app.core.database import pool_context
from app.sat.normalization import (
    is_cleared,
    is_redacted,
    name_core,
    normalize_name,
    normalize_rfc,
    normalize_situacion,
)

logger = logging.getLogger("sat.importer")

DEFAULT_CSV_PATH = Path("black_list.csv")
SOURCE_ENCODING = "cp1252"
EXPECTED_COLUMN_COUNT = 20
MAX_PREAMBLE_LINES = 25
COPY_BATCH_SIZE = 5_000

# Column order of the staging table, and therefore of the COPY payload.
STAGING_COLUMNS = (
    "source_row_number",
    "rfc",
    "rfc_normalized",
    "name",
    "name_normalized",
    "name_core",
    "situacion",
    "is_cleared",
    "is_redacted",
    "presuncion_sat_oficio",
    "presuncion_sat_publicacion",
    "presuncion_dof_oficio",
    "presuncion_dof_publicacion",
    "desvirtuado_sat_oficio",
    "desvirtuado_sat_publicacion",
    "desvirtuado_dof_oficio",
    "desvirtuado_dof_publicacion",
    "definitivo_sat_oficio",
    "definitivo_sat_publicacion",
    "definitivo_dof_oficio",
    "definitivo_dof_publicacion",
    "sentencia_sat_oficio",
    "sentencia_sat_publicacion",
    "sentencia_dof_oficio",
    "sentencia_dof_publicacion",
    "source_hash",
)


class ImportError_(Exception):
    """Raised when the import cannot proceed at all (unreadable or unusable file)."""


@dataclass
class RowFailure:
    """A single row that could not be parsed."""

    line_number: int
    reason: str


@dataclass
class ImportReport:
    """Outcome of an import run."""

    parsed: int = 0
    inserted: int = 0
    updated: int = 0
    duplicates_collapsed: int = 0
    redacted: int = 0
    failed: int = 0
    failures: list[RowFailure] = field(default_factory=list)
    dry_run: bool = False

    @property
    def skipped(self) -> int:
        """Rows that reached the database but changed nothing (already current)."""
        return self.parsed - self.duplicates_collapsed - self.inserted - self.updated

    def render(self) -> str:
        """Human-readable summary."""
        lines = [
            "SAT blacklist import report",
            "--------------------------------------",
            f"  rows parsed          : {self.parsed:>6}",
            f"  inserted             : {self.inserted:>6}",
            f"  updated              : {self.updated:>6}",
            f"  unchanged (skipped)  : {self.skipped:>6}",
            f"  duplicates collapsed : {self.duplicates_collapsed:>6}",
            f"  redacted (unsearch.) : {self.redacted:>6}",
            f"  failed rows          : {self.failed:>6}",
        ]
        if self.dry_run:
            lines.append("  (dry run -- nothing was written)")
        for failure in self.failures[:20]:
            lines.append(f"    ! line {failure.line_number}: {failure.reason}")
        if len(self.failures) > 20:
            lines.append(f"    ... and {len(self.failures) - 20} more")
        return "\n".join(lines)


def parse_publication_date(value: str) -> dt.date | None:
    """Parse a ``dd/mm/yyyy`` publication date, tolerating blanks and odd formats."""
    text = (value or "").strip()
    if not text:
        return None
    for fmt in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _clean(value: str) -> str | None:
    """Trim a free-text cell, returning None when it is empty."""
    text = (value or "").strip()
    return text or None


def compute_source_hash(row: Sequence[str]) -> bytes:
    """SHA-256 over every source column except the leading sequence number.

    The sequence number is excluded because SAT renumbers rows on every
    publication; including it would make an unchanged record look new.
    """
    payload = "\x1f".join(cell.strip() for cell in row[1:])
    return hashlib.sha256(payload.encode("utf-8")).digest()


def find_header_index(rows: list[list[str]]) -> int:
    """Locate the header row, skipping the legal-notice preamble."""
    for index, row in enumerate(rows[:MAX_PREAMBLE_LINES]):
        cells = [cell.strip().upper() for cell in row]
        if "RFC" in cells and any(cell.startswith("NOMBRE") for cell in cells):
            return index
    raise ImportError_(
        "Could not locate the header row: no line in the first "
        f"{MAX_PREAMBLE_LINES} contains an 'RFC' column."
    )


def read_rows(csv_path: Path) -> tuple[list[str], list[tuple[int, list[str]]]]:
    """Read the CSV and return its header plus (line number, row) pairs."""
    if not csv_path.exists():
        raise ImportError_(f"CSV file not found: {csv_path}")

    try:
        text = csv_path.read_bytes().decode(SOURCE_ENCODING)
    except OSError as exc:
        raise ImportError_(f"Could not read {csv_path}: {exc}") from exc
    except UnicodeDecodeError as exc:
        raise ImportError_(f"{csv_path} is not valid {SOURCE_ENCODING}: {exc}") from exc

    rows = list(csv.reader(text.splitlines()))
    if not rows:
        raise ImportError_(f"{csv_path} is empty.")

    header_index = find_header_index(rows)
    header = rows[header_index]
    # +1 converts the 0-based list index into a 1-based file line number.
    data = [(header_index + i + 2, row) for i, row in enumerate(rows[header_index + 1 :])]
    return header, data


def build_record(row: Sequence[str]) -> tuple[Any, ...]:
    """Turn one raw CSV row into a staging tuple, normalizing along the way."""
    try:
        source_row_number: int | None = int(row[0].strip())
    except ValueError, IndexError:
        source_row_number = None

    rfc_raw = row[1].strip()
    name_raw = row[2].strip()
    rfc_normalized = normalize_rfc(rfc_raw)
    name_normalized = normalize_name(name_raw)
    situacion = normalize_situacion(row[3])

    return (
        source_row_number,
        rfc_raw,
        rfc_normalized,
        name_raw,
        name_normalized,
        name_core(name_raw),
        situacion,
        is_cleared(situacion),
        is_redacted(rfc_normalized),
        _clean(row[4]),
        parse_publication_date(row[5]),
        _clean(row[6]),
        parse_publication_date(row[7]),
        _clean(row[8]),
        parse_publication_date(row[9]),
        _clean(row[10]),
        parse_publication_date(row[11]),
        _clean(row[12]),
        parse_publication_date(row[13]),
        _clean(row[14]),
        parse_publication_date(row[15]),
        _clean(row[16]),
        parse_publication_date(row[17]),
        _clean(row[18]),
        parse_publication_date(row[19]),
        compute_source_hash(row),
    )


def validate_row(line_number: int, row: Sequence[str]) -> str | None:
    """Return a rejection reason for a malformed row, or None when it is usable."""
    if not any(cell.strip() for cell in row):
        return "blank line"
    if len(row) < EXPECTED_COLUMN_COUNT:
        return f"expected {EXPECTED_COLUMN_COUNT} columns, found {len(row)}"
    if not row[1].strip():
        return "missing RFC"
    if not row[2].strip():
        return "missing taxpayer name"
    if not row[3].strip():
        return "missing situacion"
    return None


def parse_csv(csv_path: Path) -> tuple[list[tuple[Any, ...]], ImportReport]:
    """Parse and normalize the whole file, collecting failures instead of raising."""
    _, data = read_rows(csv_path)
    report = ImportReport()
    records: list[tuple[Any, ...]] = []

    for line_number, row in data:
        reason = validate_row(line_number, row)
        if reason is not None:
            if reason == "blank line":
                continue  # trailing newlines are not worth reporting
            report.failed += 1
            report.failures.append(RowFailure(line_number, reason))
            continue
        try:
            record = build_record(row)
        except (ValueError, IndexError) as exc:
            report.failed += 1
            report.failures.append(RowFailure(line_number, f"unparseable row: {exc}"))
            continue

        records.append(record)
        report.parsed += 1
        if record[8]:  # is_redacted
            report.redacted += 1

    return records, report


def _batched(records: Sequence[tuple[Any, ...]], size: int) -> Iterator[Sequence[tuple[Any, ...]]]:
    for start in range(0, len(records), size):
        yield records[start : start + size]


async def load_records(
    pool: asyncpg.Pool, records: Sequence[tuple[Any, ...]], report: ImportReport
) -> ImportReport:
    """COPY the parsed records into staging and merge them in one statement."""
    async with pool.acquire() as connection, connection.transaction():
        await connection.execute("TRUNCATE sat_blacklist_staging")
        for batch in _batched(records, COPY_BATCH_SIZE):
            await connection.copy_records_to_table(
                "sat_blacklist_staging",
                records=batch,
                columns=list(STAGING_COLUMNS),
            )
        merged = await connection.fetchrow("SELECT * FROM sat_blacklist_merge_staging()")
        await connection.execute("TRUNCATE sat_blacklist_staging")

    if merged is not None:
        report.inserted = merged["inserted"] or 0
        report.updated = merged["updated"] or 0
        report.duplicates_collapsed = merged["duplicates_collapsed"] or 0

    # Fresh statistics, so the planner uses the RFC/name indexes right away.
    await pool.execute("ANALYZE sat_blacklist_record")
    return report


async def run_import(csv_path: Path, *, dry_run: bool = False) -> ImportReport:
    """Parse the CSV and, unless this is a dry run, load it into the database."""
    records, report = parse_csv(csv_path)
    report.dry_run = dry_run

    if not records:
        raise ImportError_(f"No usable rows found in {csv_path}.")
    if dry_run:
        return report

    try:
        async with pool_context() as pool:
            return await load_records(pool, records, report)
    except (asyncpg.PostgresError, OSError) as exc:
        raise ImportError_(f"Database error during import: {exc}") from exc


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point (``uv run sat-blacklist-import``)."""
    parser = argparse.ArgumentParser(
        prog="sat-blacklist-import",
        description="Import the SAT blacklist CSV into PostgreSQL.",
    )
    parser.add_argument(
        "--csv", type=Path, default=DEFAULT_CSV_PATH, help="Path to the CSV snapshot."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and report without writing to the database.",
    )
    parser.add_argument("--quiet", action="store_true", help="Only print the summary.")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.WARNING if args.quiet else logging.INFO,
        format="%(levelname)s %(message)s",
    )

    try:
        report = asyncio.run(run_import(args.csv, dry_run=args.dry_run))
    except ImportError_ as exc:
        print(f"Import failed: {exc}", file=sys.stderr)
        return 1

    print(report.render())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
