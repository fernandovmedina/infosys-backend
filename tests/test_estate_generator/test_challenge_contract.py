"""Tests for generator/package boundaries that do not require PostgreSQL."""

from __future__ import annotations

from app.estate_generator import EstateGeneratorConfig, ObservationProfile
from app.estate_generator.challenge_contract import ESTATE_SCHEMA_PATH, load_estate_schema


def test_estate_schema_is_available_from_one_canonical_path() -> None:
    """The generator reads the supplied format contract rather than a copy."""
    schema = load_estate_schema()

    assert ESTATE_SCHEMA_PATH.is_file()
    assert "CREATE TABLE vendors" in schema
    assert "CREATE TABLE efos_list" in schema


def test_public_generator_config_has_no_evaluator_fields() -> None:
    """Public configuration is limited to reproducible generation controls."""
    config = EstateGeneratorConfig(seed=7)

    assert config.seed == 7
    assert config.observation_profile is ObservationProfile.CHALLENGE_WIDE
