"""Tests for generator/package boundaries that do not require PostgreSQL."""

from __future__ import annotations

from pathlib import Path

from app.estate_generator import EstateGeneratorConfig
from app.estate_generator.challenge_contract import ESTATE_SCHEMA_PATH, load_estate_schema


def test_estate_schema_is_available_from_one_canonical_path() -> None:
    """The generator reads the supplied format contract rather than a copy."""
    schema = load_estate_schema()

    assert ESTATE_SCHEMA_PATH.is_file()
    assert "CREATE TABLE vendors" in schema
    assert "CREATE TABLE efos_list" in schema


def test_public_generator_config_has_no_evaluator_fields(tmp_path: Path) -> None:
    """Public configuration is limited to reproducible generation controls."""
    output_path = tmp_path / "estate.db"
    config = EstateGeneratorConfig(seed=7, output_path=output_path)

    assert config.seed == 7
    assert config.output_path.name == "estate.db"
