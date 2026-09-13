"""Private evaluator scoring policy; production app code never imports this package."""

import json
from pathlib import Path
from typing import Any

import pytest

from evaluation.fraud_evaluator import cli
from evaluation.fraud_evaluator.scoring import false_positive_details, score_submission, total_row


def _submission(*findings: dict[str, Any]) -> dict[str, Any]:
    return {
        "findings": list(findings),
        "run_metadata": {"llm_calls": 0, "mxn_cost": 0, "wall_clock_seconds": 1.25},
    }


def test_scoring_uses_one_to_one_type_and_entity_matching() -> None:
    truth = {
        "seed": 7,
        "schemes": [
            {"type": "kickback", "entities": ["RFC:V1", "EMP:1"], "peso_amount": 10},
            {"type": "kickback", "entities": ["RFC:V2", "EMP:2"], "peso_amount": 20},
        ],
        "decoys": [{"entity": "RFC:D1"}, {"entity": "RFC:D2"}],
    }
    finding = {"scheme_type": "kickback", "entities": ["RFC:V1", "RFC:V2"], "peso_amount": 10}
    second = {"scheme_type": "round_tripping", "entities": ["RFC:V2", "RFC:D1"], "peso_amount": 9}

    row = score_submission(
        truth=truth, submission=_submission(finding, second), output_valid=True
    )

    assert row.schemes_found == 1
    assert row.decoys_accused == 1
    assert row.recall_pct == 50.0
    assert row.false_accusation_rate_pct == 50.0
    assert row.peso_claimed == 19.0 and row.peso_actual == 30.0


def test_total_recomputes_rates_from_counts() -> None:
    first = score_submission(
        truth={
            "seed": 1,
            "schemes": [{"type": "kickback", "entities": ["RFC:A"], "peso_amount": 1}],
            "decoys": [{"entity": "RFC:D"}],
        },
        submission=_submission(
            {"scheme_type": "kickback", "entities": ["RFC:A"], "peso_amount": 1}
        ),
        output_valid=True,
    )
    second = score_submission(
        truth={
            "seed": 2,
            "schemes": [
                {"type": "kickback", "entities": ["RFC:B"], "peso_amount": 1},
                {"type": "kickback", "entities": ["RFC:C"], "peso_amount": 1},
            ],
            "decoys": [{"entity": "RFC:E"}],
        },
        submission=_submission(),
        output_valid=False,
    )

    total = total_row([first, second])
    assert total["recall_pct"] == 33.33
    assert total["false_accusation_rate_pct"] == 0.0
    assert total["peso_reconciles"] == "false"


def test_false_positive_diagnostics_include_the_decoy_explanation_and_rules() -> None:
    truth = {
        "seed": 7,
        "schemes": [],
        "decoys": [
            {
                "entity": "RFC:DECOY010101AAA",
                "signal": "legitimate_short_lifecycle",
                "why_innocent": "The contract and purchase order document the work.",
            }
        ],
    }
    submission = _submission(
        {
            "scheme_type": "phantom_vendor",
            "entities": ["RFC:DECOY010101AAA"],
            "peso_amount": 1,
            "confidence": "probable",
            "rule_broken": "CFF Artículo 69-B",
        }
    )

    details = false_positive_details(
        truth=truth,
        submission=submission,
        signals=[{"entity_id": "DECOY010101AAA", "rule_id": "VENDOR_SHORT_LIFECYCLE"}],
    )

    assert len(details) == 1
    assert details[0].why_innocent.startswith("The contract")
    assert details[0].triggered_rules == "VENDOR_SHORT_LIFECYCLE"


def test_tuning_mode_rejects_reserved_heldout_seed(tmp_path: Path) -> None:
    heldout = tmp_path / "heldout.json"
    heldout.write_text(json.dumps({"cases": [{"seed": 9}]}), encoding="utf-8")
    manifest = tmp_path / "matrix.json"
    manifest.write_text(json.dumps([{"seed": 9, "ground_truth": "missing.json"}]), encoding="utf-8")

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(cli, "HELDOUT_MANIFEST", heldout)
        with pytest.raises(ValueError, match="reserved"):
            cli._load_tuning(manifest)


def test_heldout_evaluation_rejects_a_partial_case_limit(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="only in tuning"):
        cli.evaluate(mode="heldout", output_root=tmp_path / "result", max_cases=1)


def test_heldout_evaluation_rejects_a_tuning_offset(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="only in tuning"):
        cli.evaluate(mode="heldout", output_root=tmp_path / "result", start_at=1)


def test_production_application_does_not_reference_private_evaluator() -> None:
    root = Path(__file__).resolve().parents[2]
    forbidden = ("ground" + "_truth", "fraud_evaluator", "evaluation.estate_generator")
    leaks = [
        str(path.relative_to(root))
        for path in (root / "app").rglob("*.py")
        if any(needle in path.read_text(encoding="utf-8") for needle in forbidden)
    ]

    assert leaks == []


def test_heldout_evaluation_separates_public_inputs_from_private_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    heldout = tmp_path / "heldout.json"
    heldout.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "seed": 42,
                        "observation_profile": "challenge_wide",
                        "all_five": True,
                        "decoy_count": 1,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(cli, "HELDOUT_MANIFEST", heldout)

    table = cli.evaluate(mode="heldout", output_root=tmp_path / "result")

    rows = table.read_text(encoding="utf-8").splitlines()
    assert len(rows) == 3 and rows[1].startswith("42,") and rows[2].startswith("TOTAL,")
    assert not list((tmp_path / "result" / "public").rglob("private"))
    assert (tmp_path / "result" / "private" / "seed42.ground_truth.json").is_file()
