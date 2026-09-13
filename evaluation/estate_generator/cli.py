"""Private fixture CLI; never expose this command from the deployed API."""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from app.estate_generator.config import EstateGeneratorConfig, ObservationProfile
from evaluation.estate_generator.harness import render_fixture
from evaluation.estate_generator.scenarios import SCHEME_TYPES, build_scenario_run


def _parse_scheme_list(value: str) -> tuple[str, ...]:
    scheme_types = tuple(part.strip() for part in value.split(",") if part.strip())
    if not scheme_types or any(item not in SCHEME_TYPES for item in scheme_types):
        raise argparse.ArgumentTypeError(
            f"schemes must be comma-separated values from {', '.join(SCHEME_TYPES)}"
        )
    if len(set(scheme_types)) != len(scheme_types):
        raise argparse.ArgumentTypeError("schemes cannot contain duplicates")
    return scheme_types


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a private-evaluation estate fixture.")
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--all-five", action="store_true")
    selection.add_argument("--scheme-count", type=int)
    selection.add_argument(
        "--scheme-type",
        action="append",
        choices=SCHEME_TYPES,
        metavar="SCHEME",
        help="Select one scheme; repeat for multiple explicit scheme types",
    )
    selection.add_argument(
        "--schemes",
        type=_parse_scheme_list,
        metavar="SCHEME[,SCHEME...]",
        help="Select comma-separated scheme types explicitly",
    )
    parser.add_argument("--decoy-count", type=int)
    parser.add_argument("--force", action="store_true")
    parser.add_argument(
        "--observation-profile",
        type=ObservationProfile,
        choices=list(ObservationProfile),
        default=ObservationProfile.CHALLENGE_WIDE,
    )
    parser.add_argument("--start-date", type=date.fromisoformat, default=date(2026, 1, 1))
    parser.add_argument("--end-date", type=date.fromisoformat, default=date(2026, 6, 30))
    args = parser.parse_args()
    config = EstateGeneratorConfig(
        seed=args.seed,
        start_date=args.start_date,
        end_date=args.end_date,
        observation_profile=args.observation_profile,
    )
    run = build_scenario_run(
        config,
        all_five=args.all_five,
        scheme_count=args.scheme_count,
        scheme_types=args.scheme_type or args.schemes,
        decoy_count=args.decoy_count,
    )
    _, truth_path, provenance_path = render_fixture(run, config, args.output, overwrite=args.force)
    print(
        f"Generated public estate {args.output}; private sidecars: {truth_path}, {provenance_path}"
    )


if __name__ == "__main__":
    main()
