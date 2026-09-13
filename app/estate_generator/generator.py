"""Public facade for deterministic estate generation."""

from __future__ import annotations

from pathlib import Path

from app.estate_generator.checks import validate_public_estate
from app.estate_generator.config import EstateGeneratorConfig
from app.estate_generator.exporter import export_sqlite
from app.estate_generator.models import GeneratedEstate
from app.estate_generator.normal_business import build_normal_estate


def generate_estate(config: EstateGeneratorConfig) -> GeneratedEstate:
    """Build and validate an in-memory public estate for ``config.seed``."""
    estate = build_normal_estate(config)
    validate_public_estate(estate)
    return estate


def generate_sqlite_estate(
    config: EstateGeneratorConfig, output_path: Path, *, overwrite: bool = False
) -> GeneratedEstate:
    """Build an estate and write it to a public SQLite destination."""
    estate = generate_estate(config)
    export_sqlite(
        estate,
        output_path,
        observation_profile=config.observation_profile,
        overwrite=overwrite,
    )
    return estate
