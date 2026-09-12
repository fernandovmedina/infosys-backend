"""Tests for the CSV parsing and seeding mechanism."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from app.sat.importer import (
    DEFAULT_CSV_PATH,
    ImportError_,
    build_record,
    compute_source_hash,
    find_header_index,
    parse_csv,
    parse_publication_date,
    read_rows,
    validate_row,
)

HEADER = [
    "No",
    "RFC",
    "Nombre del Contribuyente",
    "Situación del contribuyente",
    *[f"col{i}" for i in range(16)],
]


def _row(
    no: str = "1",
    rfc: str = "AAA080808HL8",
    name: str = "EMPRESA SA DE CV",
    situacion: str = "Definitivo",
) -> list[str]:
    return [no, rfc, name, situacion, *[""] * 16]


def _write_csv(path: Path, rows: list[list[str]], preamble: int = 2) -> Path:
    import csv

    with path.open("w", encoding="cp1252", newline="") as handle:
        writer = csv.writer(handle)
        for _ in range(preamble):
            writer.writerow(["Información actualizada al 31 de julio de 2026", *[""] * 19])
        writer.writerow(HEADER)
        writer.writerows(rows)
    return path


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("01/06/2018", dt.date(2018, 6, 1)),
        ("25/06/2018", dt.date(2018, 6, 25)),
        ("2018-06-25", dt.date(2018, 6, 25)),
        ("", None),
        ("   ", None),
        ("not a date", None),
        ("31/02/2018", None),  # impossible date, rejected rather than coerced
    ],
)
def test_parse_publication_date(raw: str, expected: dt.date | None) -> None:
    assert parse_publication_date(raw) == expected


def test_find_header_index_skips_preamble() -> None:
    rows = [["legal notice"], ["title"], HEADER, _row()]
    assert find_header_index(rows) == 2


def test_find_header_index_raises_without_header() -> None:
    with pytest.raises(ImportError_, match="header row"):
        find_header_index([["nothing"], ["useful"]])


def test_source_hash_ignores_the_sequence_number() -> None:
    """SAT renumbers rows each publication; that must not look like a change."""
    assert compute_source_hash(_row(no="1")) == compute_source_hash(_row(no="9999"))


def test_source_hash_differs_when_content_changes() -> None:
    assert compute_source_hash(_row(situacion="Definitivo")) != compute_source_hash(
        _row(situacion="Presunto")
    )


@pytest.mark.parametrize(
    ("row", "reason"),
    [
        (_row(rfc=""), "missing RFC"),
        (_row(name=""), "missing taxpayer name"),
        (_row(situacion=""), "missing situacion"),
        ([""] * 20, "blank line"),
        (["1", "AAA080808HL8"], "expected 20 columns, found 2"),
    ],
)
def test_validate_row_rejects_malformed_rows(row: list[str], reason: str) -> None:
    assert validate_row(1, row) == reason


def test_validate_row_accepts_a_good_row() -> None:
    assert validate_row(1, _row()) is None


def test_build_record_normalizes() -> None:
    record = build_record(_row(rfc=" aaa080808hl8 ", name="Ingenios Santos, S.A. de C.V."))
    assert record[1] == "aaa080808hl8"  # raw preserved
    assert record[2] == "AAA080808HL8"  # rfc_normalized
    assert record[4] == "INGENIOS SANTOS SA DE CV"  # name_normalized
    assert record[5] == "INGENIOS SANTOS"  # name_core
    assert record[8] is False  # is_redacted


def test_build_record_flags_redacted_rows() -> None:
    record = build_record(_row(rfc="XXXXXXXXXXXX", name="Información suprimida"))
    assert record[8] is True


def test_build_record_marks_cleared_statuses() -> None:
    assert build_record(_row(situacion="Desvirtuado "))[7] is True
    assert build_record(_row(situacion="Definitivo"))[7] is False


def test_parse_csv_reports_malformed_rows_without_aborting(tmp_path: Path) -> None:
    """One bad row must not cost us the other 14,760."""
    path = _write_csv(
        tmp_path / "partial.csv",
        [
            _row(no="1", rfc="AAA080808HL8"),
            _row(no="2", rfc=""),  # malformed: no RFC
            ["3", "BBB080808HL8"],  # malformed: truncated
            _row(no="4", rfc="CCC080808HL8"),
        ],
    )
    records, report = parse_csv(path)

    assert report.parsed == 2
    assert report.failed == 2
    assert len(records) == 2
    assert {failure.reason for failure in report.failures} == {
        "missing RFC",
        "expected 20 columns, found 2",
    }


def test_parse_csv_counts_redacted_rows(tmp_path: Path) -> None:
    path = _write_csv(
        tmp_path / "redacted.csv",
        [_row(no="1"), _row(no="2", rfc="XXXXXXXXXXXX", name="Información suprimida")],
    )
    _, report = parse_csv(path)
    assert report.parsed == 2
    assert report.redacted == 1


def test_read_rows_raises_on_a_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ImportError_, match="not found"):
        read_rows(tmp_path / "does-not-exist.csv")


def test_read_rows_raises_on_an_empty_file(tmp_path: Path) -> None:
    path = tmp_path / "empty.csv"
    path.write_text("", encoding="cp1252")
    with pytest.raises(ImportError_, match="empty"):
        read_rows(path)


@pytest.mark.skipif(not DEFAULT_CSV_PATH.exists(), reason="black_list.csv not present")
def test_reference_dataset_parses_cleanly() -> None:
    """The shipped snapshot must parse with no failures."""
    records, report = parse_csv(DEFAULT_CSV_PATH)
    assert report.failed == 0
    assert report.parsed == len(records) == 14_761
    assert report.redacted == 238
