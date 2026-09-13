"""Turn an uploaded dataset into the estate's tables and diagnose them.

Two upload shapes are accepted:

* exactly one `.zip` holding one CSV per table (optionally inside a folder), or
* one or more loose `.csv` files, one per table.

Each CSV is matched to a table by its file name, falling back to its header
columns. Anything under a `private/` folder is skipped on purpose: the synthetic
estate generator keeps the ground truth there, and the investigation must never
see it.

Everything in this module is synchronous and free of I/O besides the optional
`write_tables`; the API runs it in a worker thread.
"""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import io
import re
import zipfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from app.core.errors import UploadRejectedError
from app.runs.estate import TABLE_SPECS, SourceTable, TableSpec

type UploadFormat = Literal["zip", "csv"]
type DiagnosticStatus = Literal["ok", "warning", "error"]

ACCEPTED_EXTENSIONS = (".zip", ".csv")

# Ceiling on the uncompressed size of a zip, and on how much one entry may
# inflate. Both guard against zip bombs.
MAX_UNCOMPRESSED_BYTES = 1024 * 1024 * 1024
MAX_COMPRESSION_RATIO = 200

_DELIMITERS = (",", ";", "\t", "|")
_MAX_VALUE_EXAMPLES = 3


@dataclass(frozen=True, slots=True)
class UploadedFile:
    filename: str
    data: bytes


@dataclass(slots=True)
class ParsedTable:
    name: SourceTable
    source_file: str
    header: list[str]
    rows: list[list[str]]
    malformed_rows: int = 0


@dataclass(frozen=True, slots=True)
class IgnoredFile:
    filename: str
    reason: str


@dataclass(slots=True)
class TableDiagnostic:
    name: SourceTable
    rows: int
    status: DiagnosticStatus
    warnings: list[str]
    source_file: str | None
    missing: bool


@dataclass(frozen=True, slots=True)
class ColumnWarning:
    table: SourceTable
    column: str
    message: str


@dataclass(slots=True)
class Dataset:
    format: UploadFormat
    filename: str
    sha256: str
    tables: dict[SourceTable, ParsedTable]
    ignored_files: list[IgnoredFile]
    diagnostics: list[TableDiagnostic] = field(default_factory=list)
    column_warnings: list[ColumnWarning] = field(default_factory=list)

    @property
    def blocked(self) -> bool:
        return any(d.status == "error" for d in self.diagnostics)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def ingest(files: list[UploadedFile]) -> Dataset:
    """Read the upload, map its CSVs to tables and diagnose every table.

    Raises `UploadRejectedError` when the upload as a whole cannot be used.
    Problems with individual tables are not errors here: they are reported in
    `Dataset.diagnostics` so the user sees all of them at once.
    """
    if not files:
        raise UploadRejectedError("no_files", "No se recibió ningún archivo.")

    for file in files:
        if not file.filename.lower().endswith(ACCEPTED_EXTENSIONS):
            raise UploadRejectedError(
                "unsupported_format",
                f"El formato de {file.filename} no está soportado. Sube un .zip o archivos .csv.",
                details={"filename": file.filename, "accepted": list(ACCEPTED_EXTENSIONS)},
                status_code=415,
            )

    archives = [f for f in files if f.filename.lower().endswith(".zip")]
    filenames = [f.filename for f in files]
    if archives and len(archives) != len(files):
        raise UploadRejectedError(
            "mixed_formats",
            "Sube un solo .zip o uno o varios .csv, pero no ambos a la vez.",
            details={"filenames": filenames},
        )
    if len(archives) > 1:
        raise UploadRejectedError(
            "multiple_archives",
            "Solo se puede subir un .zip por investigación.",
            details={"filenames": filenames},
        )

    if archives:
        archive = archives[0]
        dataset = _read_zip(archive)
    else:
        dataset = _read_csvs(files)

    if not dataset.tables:
        raise UploadRejectedError(
            "no_tables_found",
            "No se encontró ninguna tabla reconocible. Nombra cada CSV como la tabla "
            "(por ejemplo invoices.csv) o usa las columnas del estate.",
            details={"ignored_files": [_ignored_dict(i) for i in dataset.ignored_files]},
        )

    dataset.diagnostics, dataset.column_warnings = diagnose(dataset.tables)
    return dataset


def _ignored_dict(ignored: IgnoredFile) -> dict[str, str]:
    return {"filename": ignored.filename, "reason": ignored.reason}


# ---------------------------------------------------------------------------
# Upload shapes
# ---------------------------------------------------------------------------


def _read_zip(archive: UploadedFile) -> Dataset:
    try:
        bundle = zipfile.ZipFile(io.BytesIO(archive.data))
    except zipfile.BadZipFile as exc:
        raise _invalid_archive(archive.filename, "el archivo está dañado o no es un ZIP") from exc

    candidates: list[UploadedFile] = []
    ignored: list[IgnoredFile] = []
    with bundle:
        entries = [info for info in bundle.infolist() if not info.is_dir()]
        total = sum(info.file_size for info in entries)
        if total > MAX_UNCOMPRESSED_BYTES:
            raise _invalid_archive(
                archive.filename, "el contenido descomprimido es demasiado grande"
            )

        for info in entries:
            path = PurePosixPath(info.filename)
            parts = [part.lower() for part in path.parts]
            if any(p.startswith(".") or p == "__macosx" for p in parts):
                continue  # OS metadata; not worth mentioning.
            if "private" in parts[:-1]:
                ignored.append(
                    IgnoredFile(info.filename, "carpeta private/: no se usa en la investigación")
                )
                continue
            if info.flag_bits & 0x1:
                raise _invalid_archive(archive.filename, "el ZIP está protegido con contraseña")
            suffix = path.suffix.lower()
            if suffix == ".zip":
                ignored.append(IgnoredFile(info.filename, "no se admiten ZIP dentro del ZIP"))
                continue
            if suffix != ".csv":
                ignored.append(IgnoredFile(info.filename, "no es un archivo .csv"))
                continue
            if info.compress_size and info.file_size / info.compress_size > MAX_COMPRESSION_RATIO:
                raise _invalid_archive(archive.filename, f"{info.filename} está sobrecomprimido")
            try:
                data = bundle.read(info)
            except (zipfile.BadZipFile, OSError, RuntimeError) as exc:
                raise _invalid_archive(
                    archive.filename, f"no se pudo leer {info.filename}"
                ) from exc
            candidates.append(UploadedFile(info.filename, data))

    tables, more_ignored = _map_csvs(candidates)
    return Dataset(
        format="zip",
        filename=archive.filename,
        sha256=hashlib.sha256(archive.data).hexdigest(),
        tables=tables,
        ignored_files=ignored + more_ignored,
    )


def _read_csvs(files: list[UploadedFile]) -> Dataset:
    tables, ignored = _map_csvs(files)
    # Hash name + content in a stable order, so the same files give the same
    # fingerprint however the browser happened to order them.
    digest = hashlib.sha256()
    for file in sorted(files, key=lambda f: f.filename):
        digest.update(file.filename.encode())
        digest.update(b"\0")
        digest.update(hashlib.sha256(file.data).digest())
    return Dataset(
        format="csv",
        filename=files[0].filename if len(files) == 1 else f"{len(files)} archivos CSV",
        sha256=digest.hexdigest(),
        tables=tables,
        ignored_files=ignored,
    )


def _invalid_archive(filename: str, reason: str) -> UploadRejectedError:
    return UploadRejectedError(
        "invalid_archive",
        f"No se pudo leer {filename}: {reason}.",
        details={"filename": filename},
    )


# ---------------------------------------------------------------------------
# CSV parsing and table identification
# ---------------------------------------------------------------------------


def _map_csvs(
    files: list[UploadedFile],
) -> tuple[dict[SourceTable, ParsedTable], list[IgnoredFile]]:
    tables: dict[SourceTable, ParsedTable] = {}
    sources: dict[SourceTable, list[str]] = {}
    ignored: list[IgnoredFile] = []

    for file in files:
        header, rows, malformed = parse_csv(file)
        name = table_for_filename(file.filename) or table_for_header(header)
        if name is None:
            ignored.append(
                IgnoredFile(
                    file.filename, "no coincide con ninguna tabla por nombre ni por columnas"
                )
            )
            continue
        sources.setdefault(name, []).append(file.filename)
        tables[name] = ParsedTable(name, file.filename, header, rows, malformed)

    for name, filenames in sources.items():
        if len(filenames) > 1:
            raise UploadRejectedError(
                "duplicate_table",
                f"La tabla {name} aparece en varios archivos: {', '.join(filenames)}. "
                "Deja solo uno.",
                details={"table": name, "filenames": filenames},
            )
    return tables, ignored


def parse_csv(file: UploadedFile) -> tuple[list[str], list[list[str]], int]:
    """Decode and split a CSV. Returns (normalized header, data rows, malformed row count).

    Rows whose field count differs from the header are padded or truncated so
    downstream code can index them by column, and counted as malformed.
    """
    text = _decode(file)
    first_line = text.split("\n", 1)[0]
    delimiter = max(_DELIMITERS, key=first_line.count)
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)
    try:
        raw_header = next(reader, None)
        records = [row for row in reader if any(cell.strip() for cell in row)]
    except csv.Error as exc:
        raise _invalid_csv(file.filename, f"CSV mal formado ({exc})") from exc

    header = [_normalize_column(c) for c in raw_header or []]
    if not any(header):
        raise _invalid_csv(file.filename, "no tiene fila de encabezados")

    width = len(header)
    malformed = 0
    rows: list[list[str]] = []
    for record in records:
        if len(record) != width:
            malformed += 1
            record = (record + [""] * width)[:width]
        rows.append(record)
    return header, rows, malformed


def _decode(file: UploadedFile) -> str:
    if b"\0" in file.data[:8192]:
        raise _invalid_csv(file.filename, "parece un archivo binario, no texto")
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return file.data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return file.data.decode("latin-1")


def _invalid_csv(filename: str, reason: str) -> UploadRejectedError:
    return UploadRejectedError(
        "invalid_csv",
        f"No se pudo leer {filename}: {reason}.",
        details={"filename": filename, "reason": reason},
    )


def _normalize_column(column: str) -> str:
    return re.sub(r"[\s\-]+", "_", column.strip().lstrip("\ufeff").lower())


def _normalize_stem(filename: str) -> str:
    stem = PurePosixPath(filename.replace("\\", "/")).stem
    return re.sub(r"[\s\-.]+", "_", stem.strip().lower())


def table_for_filename(filename: str) -> SourceTable | None:
    stem = _normalize_stem(filename)
    for spec in TABLE_SPECS:
        if stem == spec.name or stem in spec.aliases:
            return spec.name
    return None


def table_for_header(header: list[str]) -> SourceTable | None:
    """The table whose key columns are all present and whose columns best cover the header."""
    present = set(header)
    best: tuple[float, SourceTable] | None = None
    for spec in TABLE_SPECS:
        if not set(spec.key_columns) <= present:
            continue
        coverage = len(present & set(spec.columns)) / len(spec.columns)
        if coverage >= 0.6 and (best is None or coverage > best[0]):
            best = (coverage, spec.name)
    return best[1] if best else None


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------


def diagnose(
    tables: dict[SourceTable, ParsedTable],
) -> tuple[list[TableDiagnostic], list[ColumnWarning]]:
    """One diagnostic per estate table, in canonical order, plus column-level warnings."""
    diagnostics: list[TableDiagnostic] = []
    column_warnings: list[ColumnWarning] = []

    for spec in TABLE_SPECS:
        table = tables.get(spec.name)
        if table is None:
            diagnostics.append(
                TableDiagnostic(
                    name=spec.name,
                    rows=0,
                    status="error" if spec.required else "warning",
                    warnings=[f"no encontrada → {spec.capability_loss}"],
                    source_file=None,
                    missing=True,
                )
            )
            continue

        warnings, columns = _diagnose_table(spec, table)
        column_warnings.extend(columns)
        missing_keys = [c for c in spec.key_columns if c not in table.header]
        if missing_keys or not table.rows:
            status: DiagnosticStatus = "error" if spec.required else "warning"
        elif warnings or columns:
            status = "warning"
        else:
            status = "ok"
        diagnostics.append(
            TableDiagnostic(
                name=spec.name,
                rows=len(table.rows),
                status=status,
                warnings=warnings,
                source_file=table.source_file,
                missing=False,
            )
        )
    return diagnostics, column_warnings


def _diagnose_table(spec: TableSpec, table: ParsedTable) -> tuple[list[str], list[ColumnWarning]]:
    warnings: list[str] = []
    columns: list[ColumnWarning] = []

    if not table.rows:
        warnings.append(f"la tabla está vacía → {spec.capability_loss}")

    missing_keys = [c for c in spec.key_columns if c not in table.header]
    if missing_keys:
        warnings.append(
            f"faltan columnas imprescindibles ({', '.join(missing_keys)}) → {spec.capability_loss}"
        )
    for column in spec.columns:
        if column not in table.header and column not in spec.key_columns:
            columns.append(ColumnWarning(spec.name, column, _missing_column_message(spec, column)))

    if table.malformed_rows:
        warnings.append(
            f"{table.malformed_rows} filas no tienen el mismo número de columnas que el encabezado"
        )

    duplicates = _duplicate_key_count(table, spec.columns[0])
    if duplicates:
        warnings.append(
            f"{duplicates} valores repetidos en {spec.columns[0]}, que debería ser único"
        )

    for column in spec.numeric_columns:
        bad = _invalid_values(table, column, _is_number)
        if bad:
            columns.append(ColumnWarning(spec.name, column, _bad_values_message(bad, "numéricos")))
    for column in spec.date_columns:
        bad = _invalid_values(table, column, _is_iso_date)
        if bad:
            columns.append(
                ColumnWarning(spec.name, column, _bad_values_message(bad, "fechas ISO 8601"))
            )
    for column, allowed in spec.enum_columns.items():
        lowered = {a.lower() for a in allowed}
        bad = _invalid_values(table, column, lambda v, lowered=lowered: v.lower() in lowered)
        if bad:
            columns.append(
                ColumnWarning(
                    spec.name,
                    column,
                    _bad_values_message(bad, f"valores esperados ({' | '.join(allowed)})"),
                )
            )
    return warnings, columns


def _missing_column_message(spec: TableSpec, column: str) -> str:
    if column in spec.enum_columns:
        return f"falta la columna; se esperaba {' | '.join(spec.enum_columns[column])}"
    return "falta la columna"


def _column_values(table: ParsedTable, column: str) -> list[str] | None:
    if column not in table.header:
        return None
    index = table.header.index(column)
    return [row[index].strip() for row in table.rows]


def _duplicate_key_count(table: ParsedTable, column: str) -> int:
    values = _column_values(table, column)
    if values is None:
        return 0
    counts = Counter(v for v in values if v)
    return sum(n - 1 for n in counts.values() if n > 1)


def _invalid_values(table: ParsedTable, column: str, valid: Any) -> Counter[str]:
    values = _column_values(table, column)
    if values is None:
        return Counter()
    # Blank cells are allowed: the schema marks most columns as nullable.
    return Counter(v for v in values if v and not valid(v))


def _bad_values_message(bad: Counter[str], expected: str) -> str:
    total = sum(bad.values())
    examples = ", ".join(repr(v) for v, _ in bad.most_common(_MAX_VALUE_EXAMPLES))
    return f"{total} valores no son {expected} (p. ej. {examples})"


def _is_number(value: str) -> bool:
    try:
        float(value.replace(",", ""))
    except ValueError:
        return False
    return True


def _is_iso_date(value: str) -> bool:
    try:
        dt.date.fromisoformat(value[:10])
    except ValueError:
        return False
    return True


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def write_tables(dataset: Dataset, directory: Path) -> None:
    """Write every recognized table as a normalized UTF-8, comma-separated CSV."""
    directory.mkdir(parents=True, exist_ok=True)
    for table in dataset.tables.values():
        with (directory / f"{table.name}.csv").open("w", encoding="utf-8", newline="") as out:
            writer = csv.writer(out)
            writer.writerow(table.header)
            writer.writerows(table.rows)
