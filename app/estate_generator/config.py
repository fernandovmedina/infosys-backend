"""Public configuration for deterministic estate generation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum


class ObservationProfile(StrEnum):
    """Which bank transfers are visible in the exported public estate."""

    CHALLENGE_WIDE = "challenge_wide"
    COMPANY_ONLY = "company_only"


@dataclass(frozen=True, slots=True)
class EstateGeneratorConfig:
    """Inputs that define a reproducible public estate.

    Values here are intentionally public generation controls. Scenario truth,
    actor attribution, and evaluator-only notes must not be added to this
    configuration because an investigator can safely import this package.
    """

    seed: int
    start_date: date = date(2026, 1, 1)
    end_date: date = date(2026, 6, 30)
    vendor_count: int = 50
    employee_count: int = 10
    normal_event_count: int = 360
    observation_profile: ObservationProfile = ObservationProfile.CHALLENGE_WIDE
