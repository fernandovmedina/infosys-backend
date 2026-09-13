"""Database access for fraud-analysis results (`fraud_analysis`, `fraud_signal`)."""

from __future__ import annotations

import json
from typing import Any

import asyncpg

from app.fraud.schemas import FraudAnalysis, Signal

_JSON_COLUMNS = (
    "submission",
    "signals_per_rule",
    "data_quality",
    "rule_failures",
    "warnings",
    "rows_per_table",
)

_SIGNAL_COLUMNS = (
    "run_id",
    "ordinal",
    "rule_id",
    "scheme_type",
    "evidence_family",
    "source_table",
    "entity_id",
    "evidence_id",
    "detected_on",
    "severity",
    "self_sufficiency",
    "amount",
    "context",
)


async def save_analysis(conn: asyncpg.Connection, *, run_id: str, analysis: FraudAnalysis) -> None:
    """Store (or replace, on a re-run) the analysis of `run_id` and all of its signals.

    Call inside a transaction so the analysis and its signals land together.
    """
    data = analysis.model_dump(mode="json")
    await conn.execute("DELETE FROM fraud_analysis WHERE run_id = $1", run_id)
    await conn.execute(
        """
        INSERT INTO fraud_analysis (
            run_id, engine_version, seed, rules_evaluated, rules_triggered,
            findings_count, total_exposure, submission, signals_per_rule, data_quality,
            rule_failures, warnings, rows_per_table, case_file_html
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7,
                $8::jsonb, $9::jsonb, $10::jsonb, $11::jsonb, $12::jsonb, $13::jsonb, $14)
        """,
        run_id,
        analysis.engine_version,
        analysis.seed,
        analysis.rules_evaluated,
        analysis.rules_triggered,
        analysis.findings_count,
        analysis.total_exposure,
        *(json.dumps(data[column], ensure_ascii=False) for column in _JSON_COLUMNS),
        analysis.case_file_html,
    )
    # One COPY for every signal instead of an INSERT per row.
    await conn.copy_records_to_table(
        "fraud_signal",
        columns=_SIGNAL_COLUMNS,
        records=[
            (
                run_id,
                ordinal,
                signal.rule_id,
                signal.scheme_type,
                signal.evidence_family,
                signal.source_table,
                signal.entity_id,
                signal.evidence_id,
                signal.detected_on,
                signal.severity,
                signal.self_sufficiency,
                signal.amount,
                None if signal.context is None else json.dumps(signal.context, ensure_ascii=False),
            )
            for ordinal, signal in enumerate(analysis.signals)
        ],
    )


def _json(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


async def get_analysis(conn: asyncpg.Connection, *, run_id: str) -> FraudAnalysis | None:
    row = await conn.fetchrow(
        """
        SELECT engine_version, seed, rules_evaluated, rules_triggered, findings_count,
               total_exposure, submission, signals_per_rule, data_quality, rule_failures,
               warnings, rows_per_table, case_file_html
        FROM fraud_analysis
        WHERE run_id = $1
        """,
        run_id,
    )
    if row is None:
        return None
    signal_rows = await conn.fetch(
        f"""
        SELECT {", ".join(_SIGNAL_COLUMNS[2:])}
        FROM fraud_signal
        WHERE run_id = $1
        ORDER BY ordinal
        """,
        run_id,
    )
    analysis = dict(row)
    for column in _JSON_COLUMNS:
        analysis[column] = _json(analysis[column])
    signals = []
    for signal_row in signal_rows:
        signal = dict(signal_row)
        signal["context"] = _json(signal["context"])
        signals.append(Signal.model_validate(signal))
    return FraudAnalysis.model_validate({**analysis, "signals": signals})
