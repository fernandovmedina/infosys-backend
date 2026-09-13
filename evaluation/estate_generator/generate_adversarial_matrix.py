"""Generate private, adversarial tuning fixtures for false-positive calibration."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.estate_generator.config import EstateGeneratorConfig, ObservationProfile
from app.estate_generator.output import OUTPUT_ROOT, create_run_directory
from evaluation.estate_generator.harness import render_fixture_run
from evaluation.estate_generator.scenarios import build_scenario_run


def generate(
    *, output_root: Path, first_seed: int, replicates: int, include_fraud: bool = False
) -> Path:
    if replicates < 1:
        raise ValueError("replicates must be positive")
    records: list[dict[str, object]] = []
    for index in range(replicates):
        seed = first_seed + index
        profile = (
            ObservationProfile.CHALLENGE_WIDE
            if index % 2 == 0
            else ObservationProfile.COMPANY_ONLY
        )
        config = EstateGeneratorConfig(seed=seed, observation_profile=profile)
        planted_fraud = include_fraud and index % 2 == 1
        run = build_scenario_run(
            config,
            all_five=planted_fraud,
            scheme_count=0 if not planted_fraud else None,
            decoy_count=0,
            adversarial=True,
        )
        directory = create_run_directory(seed, root=output_root / "tuning" / "adversarial")
        _, truth_path, provenance_path = render_fixture_run(run, config, directory)
        records.append(
            {
                "seed": seed,
                "category": "adversarial_innocent_lookalikes",
                "contains_planted_fraud": planted_fraud,
                "observation_profile": profile.value,
                "ground_truth": str(truth_path.relative_to(output_root)),
                "provenance": str(provenance_path.relative_to(output_root)),
            }
        )
    manifest = output_root / "adversarial_manifest.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT / "adversarial")
    parser.add_argument("--first-seed", type=int, default=71_001)
    parser.add_argument("--replicates", type=int, default=10)
    parser.add_argument(
        "--include-fraud",
        action="store_true",
        help="Alternate clean adversarial estates with all-five planted-fraud estates.",
    )
    args = parser.parse_args()
    try:
        manifest = generate(
            output_root=args.output_root,
            first_seed=args.first_seed,
            replicates=args.replicates,
            include_fraud=args.include_fraud,
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    print(f"Wrote {manifest}")


if __name__ == "__main__":
    main()
