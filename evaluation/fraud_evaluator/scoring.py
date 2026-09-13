"""Deterministic scoring for the challenge Results table."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

RESULT_COLUMNS = (
    "seed",
    "schemes_planted",
    "schemes_found",
    "recall_pct",
    "decoys_planted",
    "decoys_accused",
    "false_accusation_rate_pct",
    "peso_claimed",
    "peso_actual",
    "peso_reconciles",
    "llm_calls",
    "mxn_cost",
    "wall_clock_s",
)


@dataclass(frozen=True)
class ScoreRow:
    seed: int
    schemes_planted: int
    schemes_found: int
    recall_pct: float
    decoys_planted: int
    decoys_accused: int
    false_accusation_rate_pct: float
    peso_claimed: float
    peso_actual: float
    peso_reconciles: bool
    llm_calls: int
    mxn_cost: float
    wall_clock_s: float

    def csv_row(self) -> dict[str, str | int | float]:
        row = asdict(self)
        row["peso_reconciles"] = "true" if self.peso_reconciles else "false"
        return row


def _entities(item: dict[str, Any]) -> set[str]:
    return {str(entity) for entity in item.get("entities", [])}


def _matches(scheme: dict[str, Any], finding: dict[str, Any]) -> bool:
    return scheme.get("type") == finding.get("scheme_type") and bool(
        _entities(scheme) & _entities(finding)
    )


def _maximum_matches(schemes: list[dict[str, Any]], findings: list[dict[str, Any]]) -> int:
    """One-to-one maximum bipartite matching, with deterministic traversal order."""
    assigned: dict[int, int] = {}

    def visit(scheme_index: int, seen: set[int]) -> bool:
        for finding_index, finding in enumerate(findings):
            if finding_index in seen or not _matches(schemes[scheme_index], finding):
                continue
            seen.add(finding_index)
            owner = assigned.get(finding_index)
            if owner is None or visit(owner, seen):
                assigned[finding_index] = scheme_index
                return True
        return False

    return sum(1 for index in range(len(schemes)) if visit(index, set()))


def score_submission(
    *,
    truth: dict[str, Any],
    submission: dict[str, Any],
    output_valid: bool,
) -> ScoreRow:
    """Score one validated production submission against one private answer key."""
    schemes = list(truth.get("schemes", []))
    decoys = list(truth.get("decoys", []))
    findings = list(submission.get("findings", []))
    metadata = submission["run_metadata"]
    accused_entities = {entity for finding in findings for entity in _entities(finding)}
    decoy_entities = {str(decoy["entity"]) for decoy in decoys}
    found = _maximum_matches(schemes, findings)
    decoys_accused = len(accused_entities & decoy_entities)
    return ScoreRow(
        seed=int(truth["seed"]),
        schemes_planted=len(schemes),
        schemes_found=found,
        recall_pct=round(100 * found / len(schemes), 2) if schemes else 100.0,
        decoys_planted=len(decoys),
        decoys_accused=decoys_accused,
        false_accusation_rate_pct=(
            round(100 * decoys_accused / len(decoys), 2) if decoys else 0.0
        ),
        peso_claimed=round(sum(float(item["peso_amount"]) for item in findings), 2),
        peso_actual=round(sum(float(item["peso_amount"]) for item in schemes), 2),
        peso_reconciles=output_valid,
        llm_calls=int(metadata["llm_calls"]),
        mxn_cost=round(float(metadata["mxn_cost"]), 2),
        wall_clock_s=round(float(metadata["wall_clock_seconds"]), 2),
    )


def total_row(rows: list[ScoreRow]) -> dict[str, str | int | float]:
    """Aggregate counts and recompute rates; never average per-seed percentages."""
    schemes_planted = sum(row.schemes_planted for row in rows)
    schemes_found = sum(row.schemes_found for row in rows)
    decoys_planted = sum(row.decoys_planted for row in rows)
    decoys_accused = sum(row.decoys_accused for row in rows)
    return {
        "seed": "TOTAL",
        "schemes_planted": schemes_planted,
        "schemes_found": schemes_found,
        "recall_pct": round(100 * schemes_found / schemes_planted, 2)
        if schemes_planted
        else 100.0,
        "decoys_planted": decoys_planted,
        "decoys_accused": decoys_accused,
        "false_accusation_rate_pct": round(100 * decoys_accused / decoys_planted, 2)
        if decoys_planted
        else 0.0,
        "peso_claimed": round(sum(row.peso_claimed for row in rows), 2),
        "peso_actual": round(sum(row.peso_actual for row in rows), 2),
        "peso_reconciles": "true" if all(row.peso_reconciles for row in rows) else "false",
        "llm_calls": sum(row.llm_calls for row in rows),
        "mxn_cost": round(sum(row.mxn_cost for row in rows), 2),
        "wall_clock_s": round(sum(row.wall_clock_s for row in rows), 2),
    }
