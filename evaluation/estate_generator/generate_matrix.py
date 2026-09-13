"""Generate categorized, labeled fixture matrices for detector development."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

from app.estate_generator.config import EstateGeneratorConfig, ObservationProfile
from app.estate_generator.output import OUTPUT_ROOT, create_run_directory
from evaluation.estate_generator.harness import render_fixture_run
from evaluation.estate_generator.scenarios import build_scenario_run


@dataclass(frozen=True, slots=True)
class CaseSpec:
    category: str
    scheme_types: tuple[str, ...] | None = None
    scheme_count: int | None = None
    all_five: bool = False


CASES = (
    CaseSpec("clean" , scheme_count=0),
    CaseSpec("isolated/phantom_vendor", ("phantom_vendor",)),
    CaseSpec("isolated/kickback", ("kickback",)),
    CaseSpec("isolated/round_tripping", ("round_tripping",)),
    CaseSpec("isolated/threshold_splitting", ("threshold_splitting",)),
    CaseSpec("isolated/revenue_inflation", ("revenue_inflation",)),
    CaseSpec("mixed/seed_driven"),
    CaseSpec("mixed/three_schemes", scheme_count=3),
    CaseSpec("all_five", all_five=True),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replicates", type=int, default=5, help="replicas per split/variant")
    parser.add_argument("--report-replicates", type=int, default=1)
    parser.add_argument("--first-seed", type=int, default=2001)
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    parser.add_argument(
        "--observation-profile",
        type=ObservationProfile,
        choices=list(ObservationProfile),
        default=ObservationProfile.CHALLENGE_WIDE,
    )
    return parser.parse_args()


def validate_count(value: int, name: str) -> None:
    if value < 0:
        raise SystemExit(f"{name} must be non-negative")


def generate_matrix(
    *,
    output_root: Path,
    first_seed: int,
    tuning_replicates: int,
    report_replicates: int,
    observation_profile: ObservationProfile,
) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    seed = first_seed
    for split, count in (("tuning", tuning_replicates), ("report", report_replicates)):
        for spec in CASES:
            for with_decoys in (False, True):
                variant = "with_decoys" if with_decoys else "without_decoys"
                destination = output_root / split / spec.category / variant
                for _ in range(count):
                    config = EstateGeneratorConfig(
                        seed=seed,
                        observation_profile=observation_profile,
                    )
                    run = build_scenario_run(
                        config,
                        all_five=spec.all_five,
                        scheme_count=spec.scheme_count,
                        scheme_types=spec.scheme_types,
                        decoy_count=5 if with_decoys else 0,
                    )
                    run_directory = create_run_directory(seed, root=destination)
                    _, truth_path, provenance_path = render_fixture_run(
                        run, config, run_directory
                    )
                    records.append(
                        {
                            "split": split,
                            "case_id": f"{split}/{spec.category}/{variant}/{run_directory.name}",
                            "seed": seed,
                            "category": spec.category,
                            "variant": variant,
                            "ground_truth": str(truth_path.relative_to(output_root)),
                            "provenance": str(provenance_path.relative_to(output_root)),
                        }
                    )
                    print(f"[{split}] {records[-1]['case_id']}")
                    seed += 1
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "matrix_manifest.json").write_text(
        json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return records


def main() -> int:
    args = parse_args()
    validate_count(args.replicates, "--replicates")
    validate_count(args.report_replicates, "--report-replicates")
    if args.replicates == 0 and args.report_replicates == 0:
        raise SystemExit("at least one replica is required")
    records = generate_matrix(
        output_root=args.output_root,
        first_seed=args.first_seed,
        tuning_replicates=args.replicates,
        report_replicates=args.report_replicates,
        observation_profile=args.observation_profile,
    )
    print(f"Generated {len(records)} cases under {args.output_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
