"""Run production fraud analysis against private tuning or held-out fixtures.

This evaluator is intentionally outside the deployable ``app`` package.  It
owns truth files and scoring; the fraud engine receives only public CSV paths.
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from app.estate_generator.config import EstateGeneratorConfig, ObservationProfile
from app.fraud.engine.ingesta import archivos_en_carpeta
from app.fraud.service import ENGINE_VERSION, analyze_files
from evaluation.estate_generator.harness import render_fixture_run
from evaluation.estate_generator.scenarios import build_scenario_run
from evaluation.fraud_evaluator.scoring import (
    FALSE_POSITIVE_COLUMNS,
    RESULT_COLUMNS,
    FalsePositive,
    ScoreRow,
    false_positive_details,
    score_submission,
    total_row,
)

EVALUATION_ROOT = Path(__file__).resolve().parents[1]
HELDOUT_MANIFEST = EVALUATION_ROOT / "estate_generator" / "heldout_manifest.json"
DEFAULT_OUTPUT_ROOT = EVALUATION_ROOT.parent / "generated" / "evaluation"

Mode = Literal["heldout", "tuning"]


@dataclass(frozen=True)
class EvaluationCase:
    seed: int
    public_directory: Path
    truth_path: Path


def _heldout_seeds() -> set[int]:
    document = json.loads(HELDOUT_MANIFEST.read_text(encoding="utf-8"))
    return {int(case["seed"]) for case in document["cases"]}


def _prepare_heldout(output_root: Path) -> list[EvaluationCase]:
    document = json.loads(HELDOUT_MANIFEST.read_text(encoding="utf-8"))
    public_root, private_root = output_root / "public", output_root / "private"
    cases: list[EvaluationCase] = []
    for item in document["cases"]:
        seed = int(item["seed"])
        config = EstateGeneratorConfig(
            seed=seed,
            observation_profile=ObservationProfile(item["observation_profile"]),
        )
        run = build_scenario_run(
            config,
            all_five=bool(item["all_five"]),
            decoy_count=int(item["decoy_count"]),
        )
        public_directory = public_root / f"seed{seed}"
        _, truth_path, provenance_path = render_fixture_run(run, config, public_directory)
        private_root.mkdir(parents=True, exist_ok=True)
        private_truth = private_root / f"seed{seed}.ground_truth.json"
        private_provenance = private_root / f"seed{seed}.provenance.json"
        shutil.move(str(truth_path), private_truth)
        shutil.move(str(provenance_path), private_provenance)
        (public_directory / "private").rmdir()
        cases.append(EvaluationCase(seed, public_directory, private_truth))
    return cases


def _load_tuning(manifest_path: Path) -> list[EvaluationCase]:
    document = json.loads(manifest_path.read_text(encoding="utf-8"))
    heldout = _heldout_seeds()
    cases: list[EvaluationCase] = []
    for item in document:
        seed = int(item["seed"])
        if seed in heldout:
            raise ValueError(f"seed {seed} is reserved for held-out reporting")
        truth_path = manifest_path.parent / str(item["ground_truth"])
        if not truth_path.is_file():
            raise FileNotFoundError(f"missing private evaluator file: {truth_path}")
        cases.append(EvaluationCase(seed, truth_path.parent.parent, truth_path))
    return sorted(cases, key=lambda item: item.seed)


def _write_results(
    output_root: Path,
    mode: Mode,
    rows: list[ScoreRow],
    cases: list[EvaluationCase],
    false_positives: list[FalsePositive],
) -> Path:
    results = output_root / "results"
    results.mkdir(parents=True, exist_ok=True)
    table_path = results / "results_table.csv"
    with table_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=RESULT_COLUMNS)
        writer.writeheader()
        writer.writerows(row.csv_row() for row in rows)
        writer.writerow(total_row(rows))
    diagnostics_path = results / "false_positive_diagnostics.csv"
    with diagnostics_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FALSE_POSITIVE_COLUMNS)
        writer.writeheader()
        writer.writerows(item.csv_row() for item in false_positives)
    summary: dict[tuple[str, str, str], int] = {}
    for item in false_positives:
        key = (item.decoy_signal, item.finding_scheme_type, item.triggered_rules)
        summary[key] = summary.get(key, 0) + 1
    with (results / "false_positive_summary.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=("decoy_signal", "finding_scheme_type", "triggered_rules", "occurrences"),
        )
        writer.writeheader()
        writer.writerows(
            {
                "decoy_signal": key[0],
                "finding_scheme_type": key[1],
                "triggered_rules": key[2],
                "occurrences": count,
            }
            for key, count in sorted(summary.items())
        )
    (results / "evaluation_manifest.json").write_text(
        json.dumps(
            {
                "mode": mode,
                "engine_version": ENGINE_VERSION,
                "seeds": [case.seed for case in cases],
                "matching": (
                    "same scheme type plus exact entity-id overlap; one-to-one maximum matching"
                ),
                "decoy_accusation": "a decoy entity appears in a published finding",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return table_path


def evaluate(
    *,
    mode: Mode,
    output_root: Path,
    manifest_path: Path | None = None,
    start_at: int = 0,
    max_cases: int | None = None,
) -> Path:
    """Produce a Results table or fail without publishing a partial final table."""
    if output_root.exists():
        raise FileExistsError(f"refusing to reuse evaluator output directory: {output_root}")
    if mode == "heldout" and max_cases is not None:
        raise ValueError("--max-cases is allowed only in tuning mode")
    if mode == "heldout" and start_at:
        raise ValueError("--start-at is allowed only in tuning mode")
    if start_at < 0:
        raise ValueError("--start-at cannot be negative")
    if mode == "heldout":
        cases = _prepare_heldout(output_root)
    else:
        if manifest_path is None:
            raise ValueError("--manifest is required for tuning mode")
        output_root.mkdir(parents=True)
        cases = _load_tuning(manifest_path)
        if max_cases is not None:
            if max_cases < 1:
                raise ValueError("--max-cases must be positive")
            cases = cases[start_at : start_at + max_cases]
        elif start_at:
            cases = cases[start_at:]

    rows: list[ScoreRow] = []
    false_positives: list[FalsePositive] = []
    try:
        for case in cases:
            analysis = analyze_files(
                archivos_en_carpeta(case.public_directory), seed=case.seed, max_rows=1_000_000
            )
            truth: dict[str, Any] = json.loads(case.truth_path.read_text(encoding="utf-8"))
            rows.append(
                score_submission(
                    truth=truth,
                    submission=analysis.submission.model_dump(mode="json"),
                    output_valid=True,
                )
            )
            false_positives += false_positive_details(
                truth=truth,
                submission=analysis.submission.model_dump(mode="json"),
                signals=[signal.model_dump(mode="json") for signal in analysis.signals],
            )
    except Exception:
        shutil.rmtree(output_root)
        raise
    return _write_results(output_root, mode, rows, cases, false_positives)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("heldout", "tuning"), required=True)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--manifest", type=Path, help="Required only for tuning mode.")
    parser.add_argument(
        "--max-cases", type=int, help="Evaluate the first N seed-sorted tuning cases only."
    )
    parser.add_argument(
        "--start-at", type=int, default=0, help="Zero-based offset into seed-sorted tuning cases."
    )
    args = parser.parse_args()
    try:
        table = evaluate(
            mode=args.mode,
            output_root=args.output_root,
            manifest_path=args.manifest,
            start_at=args.start_at,
            max_cases=args.max_cases,
        )
    except (FileExistsError, FileNotFoundError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    print(f"Wrote {table}")


if __name__ == "__main__":
    main()
