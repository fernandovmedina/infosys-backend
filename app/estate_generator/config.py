"""Public configuration for deterministic estate generation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class EstateGeneratorConfig:
    """Inputs that define a reproducible public estate.

    Values here are intentionally public generation controls. Scenario truth,
    actor attribution, and evaluator-only notes must not be added to this
    configuration because an investigator can safely import this package.
    """

    seed: int
    output_path: Path
    start_date: str = "2026-01-01"
    end_date: str = "2026-06-30"
    vendor_count: int = 50
    employee_count: int = 10
