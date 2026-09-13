"""SQLite projection tests for the supplied public format contract."""

from __future__ import annotations

import csv
import sqlite3
from datetime import datetime
from pathlib import Path

import pytest

from app.estate_generator.config import EstateGeneratorConfig, ObservationProfile
from app.estate_generator.generator import generate_sqlite_estate
from app.estate_generator.normal_business import build_normal_estate
from app.estate_generator.output import CSV_HEADERS, create_run_directory, export_run


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


def test_default_run_export_writes_each_schema_table_as_csv(tmp_path: Path) -> None:
    config = EstateGeneratorConfig(seed=13, normal_event_count=30)
    estate = build_normal_estate(config)
    run_directory, artifacts = export_run(
        estate,
        seed=config.seed,
        observation_profile=config.observation_profile,
        root=tmp_path,
        now=datetime(2026, 9, 12, 18, 30, 45),
    )

    assert run_directory.name == "seed13_20260912_183045"
    assert set(artifacts) == set(CSV_HEADERS)
    assert {path.name for path in run_directory.glob("*.csv")} == {
        f"{table}.csv" for table in CSV_HEADERS
    }
    assert not (run_directory / "estate.db").exists()
    for table, header in CSV_HEADERS.items():
        lines = (run_directory / f"{table}.csv").read_text(encoding="utf-8").splitlines()
        assert tuple(lines[0].split(",")) == header
        if table != "efos_list":
            assert len(lines) > 1


def test_csv_headers_match_published_estate_example(tmp_path: Path) -> None:
    """Keep the generator aligned with the judges' CSV field-shape example."""
    example_directory = (
        Path(__file__).resolve().parents[2] / "public" / "material" / "estate_csv_example"
    )
    config = EstateGeneratorConfig(seed=16, normal_event_count=30)
    run_directory, _ = export_run(
        build_normal_estate(config),
        seed=config.seed,
        observation_profile=config.observation_profile,
        root=tmp_path,
        now=datetime(2026, 9, 12, 18, 30, 45),
    )

    for table in CSV_HEADERS:
        with (example_directory / f"{table}.csv").open(
            encoding="utf-8", newline=""
        ) as handle:
            example_header = next(csv.reader(handle))
        with (run_directory / f"{table}.csv").open(
            encoding="utf-8", newline=""
        ) as handle:
            generated_header = next(csv.reader(handle))
            generated_rows = list(csv.reader(handle))

        assert generated_header == example_header
        assert all(len(row) == len(example_header) for row in generated_rows)


def test_sqlite_run_export_writes_only_database(tmp_path: Path) -> None:
    config = EstateGeneratorConfig(seed=14, normal_event_count=30)
    run_directory, artifacts = export_run(
        build_normal_estate(config),
        seed=config.seed,
        observation_profile=config.observation_profile,
        sqlite_only=True,
        root=tmp_path,
        now=datetime(2026, 9, 12, 18, 30, 45),
    )

    assert run_directory.name == "seed14_20260912_183045"
    assert set(artifacts) == {"sqlite"}
    assert artifacts["sqlite"].name == "estate.db"
    assert not list(run_directory.glob("*.csv"))
    with sqlite3.connect(artifacts["sqlite"]) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_run_directory_collision_gets_a_unique_suffix(tmp_path: Path) -> None:
    timestamp = datetime(2026, 9, 12, 18, 30, 45)
    first = create_run_directory(15, root=tmp_path, now=timestamp)
    second = create_run_directory(15, root=tmp_path, now=timestamp)

    assert first.name == "seed15_20260912_183045"
    assert second.name == "seed15_20260912_183045_2"
