"""Offline command-line entry point for the public estate generator."""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from app.estate_generator.config import EstateGeneratorConfig, ObservationProfile
from app.estate_generator.generator import generate_sqlite_estate


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate a deterministic forensic-auditor SQLite estate."
    )
    parser.add_argument("--seed", type=int, required=True, help="Deterministic random seed")
    parser.add_argument("--output", type=Path, required=True, help="SQLite destination path")
    parser.add_argument("--force", action="store_true", help="Replace an existing output file")
    parser.add_argument(
        "--start-date",
        type=date.fromisoformat,
        default=date(2026, 1, 1),
        help="Inclusive ISO 8601 start date",
    )
    parser.add_argument(
        "--end-date",
        type=date.fromisoformat,
        default=date(2026, 6, 30),
        help="Inclusive ISO 8601 end date",
    )
    parser.add_argument("--vendor-count", type=int, default=50)
    parser.add_argument("--employee-count", type=int, default=10)
    parser.add_argument("--normal-event-count", type=int, default=360)
    parser.add_argument(
        "--observation-profile",
        type=ObservationProfile,
        choices=list(ObservationProfile),
        default=ObservationProfile.CHALLENGE_WIDE,
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    config = EstateGeneratorConfig(
        seed=args.seed,
        start_date=args.start_date,
        end_date=args.end_date,
        vendor_count=args.vendor_count,
        employee_count=args.employee_count,
        normal_event_count=args.normal_event_count,
        observation_profile=args.observation_profile,
    )
    estate = generate_sqlite_estate(config, args.output, overwrite=args.force)
    print(
        f"Generated {args.output} with {len(estate.invoices)} invoices, "
        f"{len(estate.bank_transactions)} bank transactions, and seed {args.seed}."
    )


if __name__ == "__main__":
    main()
