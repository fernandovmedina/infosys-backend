"""SQLite projection tests for the supplied public format contract."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.estate_generator.config import EstateGeneratorConfig, ObservationProfile
from app.estate_generator.generator import generate_sqlite_estate


def _table_snapshot(path: Path) -> dict[str, list[tuple[object, ...]]]:
    with sqlite3.connect(path) as connection:
        tables = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
            )
        ]
        return {
            table: connection.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()
            for table in tables
        }


def test_export_uses_exact_eight_table_schema_and_is_deterministic(tmp_path: Path) -> None:
    first_path = tmp_path / "first.db"
    second_path = tmp_path / "second.db"
    config = EstateGeneratorConfig(seed=9, normal_event_count=30)

    generate_sqlite_estate(config, first_path)
    generate_sqlite_estate(config, second_path)

    first = _table_snapshot(first_path)
    second = _table_snapshot(second_path)
    assert set(first) == {
        "bank_txns",
        "contracts",
        "efos_list",
        "employees",
        "invoices",
        "ledger",
        "purchase_orders",
        "vendors",
    }
    assert first == second
    assert first["vendors"]
    assert first["invoices"]
    assert first["ledger"]
    assert first["bank_txns"]


def test_company_only_profile_exports_only_company_bank_transfers(tmp_path: Path) -> None:
    output_path = tmp_path / "company-only.db"
    estate = generate_sqlite_estate(
        EstateGeneratorConfig(
            seed=11, normal_event_count=30, observation_profile=ObservationProfile.COMPANY_ONLY
        ),
        output_path,
    )
    with sqlite3.connect(output_path) as connection:
        rows = connection.execute("SELECT from_clabe, to_clabe FROM bank_txns").fetchall()

    assert rows
    assert all(estate.company_clabe in row for row in rows)


def test_existing_output_requires_explicit_overwrite(tmp_path: Path) -> None:
    output_path = tmp_path / "estate.db"
    config = EstateGeneratorConfig(seed=3, normal_event_count=30)
    generate_sqlite_estate(config, output_path)

    with pytest.raises(FileExistsError):
        generate_sqlite_estate(config, output_path)

    generate_sqlite_estate(config, output_path, overwrite=True)
    assert output_path.is_file()
