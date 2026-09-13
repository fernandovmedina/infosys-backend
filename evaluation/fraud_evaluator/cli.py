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
from evaluation.fraud_evaluator.scoring import RESULT_COLUMNS, ScoreRow, score_submission, total_row

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
    output_root: Path, mode: Mode, rows: list[ScoreRow], cases: list[EvaluationCase]
) -> Path:
    results = output_root / "results"
    results.mkdir(parents=True, exist_ok=True)
    table_path = results / "results_table.csv"
    with table_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=RESULT_COLUMNS)
        writer.writeheader()
        writer.writerows(row.csv_row() for row in rows)
        writer.writerow(total_row(rows))
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


def evaluate(*, mode: Mode, output_root: Path, manifest_path: Path | None = None) -> Path:
    """Produce a Results table or fail without publishing a partial final table."""
    if output_root.exists():
        raise FileExistsError(f"refusing to reuse evaluator output directory: {output_root}")
    if mode == "heldout":
        cases = _prepare_heldout(output_root)
    else:
        if manifest_path is None:
            raise ValueError("--manifest is required for tuning mode")
        output_root.mkdir(parents=True)
        cases = _load_tuning(manifest_path)

    rows: list[ScoreRow] = []
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
    except Exception:
        shutil.rmtree(output_root)
        raise
    return _write_results(output_root, mode, rows, cases)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("heldout", "tuning"), required=True)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--manifest", type=Path, help="Required only for tuning mode.")
    args = parser.parse_args()
    try:
        table = evaluate(mode=args.mode, output_root=args.output_root, manifest_path=args.manifest)
    except (FileExistsError, FileNotFoundError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    print(f"Wrote {table}")


if __name__ == "__main__":
    main()
