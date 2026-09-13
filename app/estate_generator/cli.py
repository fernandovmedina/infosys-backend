"""Offline command-line entry point for the public estate generator."""

from __future__ import annotations

import argparse
from datetime import date

from app.estate_generator.config import EstateGeneratorConfig, ObservationProfile
from app.estate_generator.generator import generate_estate
from app.estate_generator.output import export_run


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate a deterministic forensic-auditor estate run."
    )
    parser.add_argument("--seed", type=int, required=True, help="Deterministic random seed")
    parser.add_argument(
        "--sqlite",
        action="store_true",
        help="Write only estate.db; otherwise write one CSV per schema table",
    )
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
    estate = generate_estate(config)
    run_directory, artifacts = export_run(
        estate,
        seed=args.seed,
        observation_profile=config.observation_profile,
        sqlite_only=args.sqlite,
    )
    format_name = "SQLite" if args.sqlite else "CSV"
    print(
        f"Generated {format_name} estate run at {run_directory} with "
        f"{len(estate.invoices)} invoices and {len(estate.bank_transactions)} bank transactions."
    )
    for artifact in artifacts.values():
        print(f"  {artifact}")


if __name__ == "__main__":
    main()
