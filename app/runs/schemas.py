"""Response models for the investigation-run endpoints.

Field names mirror the frontend's `lib/runs/types.ts`.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.runs.estate import SourceTable

type RunStatus = Literal["validating", "ready", "running", "completed", "failed"]
type Verdict = Literal["fraud_proven", "fraud_probable", "clean_with_leads", "clean"]
type RunEventType = Literal[
    "step",
    "detector_result",
    "finding_draft",
    "challenge",
    "validation",
    "lead_closed",
    "warning",
    "completed",
    "failed",
]
type AgentRole = Literal["system", "detector", "investigator", "challenger", "validator"]


def _is_none(value: Any) -> bool:
    return value is None


def omitted() -> Any:
    """Default of an optional field: `None`, left out of the JSON (`field?: T` in TypeScript)."""
    return Field(default=None, exclude_if=_is_none)


class ApiErrorBody(BaseModel):
    code: str
    message: str
    details: Any = None


class CreateRunResponse(BaseModel):
    run_id: str
    status: RunStatus


class DeleteRunsResponse(BaseModel):
    deleted: int


class TableDiagnostic(BaseModel):
    name: SourceTable
    rows: int
    status: Literal["ok", "warning", "error"]
    warnings: list[str]
    source_file: str | None
    missing: bool


class ColumnWarning(BaseModel):
    table: SourceTable
    column: str
    message: str


class IgnoredFile(BaseModel):
    filename: str
    reason: str


class ValidationResult(BaseModel):
    run_id: str
    status: RunStatus
    filename: str
    format: Literal["zip", "csv"]
    sha256: str
    tables: list[TableDiagnostic]
    column_warnings: list[ColumnWarning]
    ignored_files: list[IgnoredFile]


class RunCounters(BaseModel):
    """Live counters. The engine is deterministic: no LLM calls and no cost, only elapsed time."""

    llm_calls: int = 0
    mxn_cost: float = 0.0
    elapsed_seconds: float


class RunEvent(BaseModel):
    """One step of the investigation log; also each Server-Sent Event of `/events`."""

    seq: int
    ts: dt.datetime
    type: RunEventType
    role: AgentRole
    kind: str | None = omitted()
    message: str
    detail: str | None = omitted()
    result: str | None = omitted()
    result_status: Literal["ok", "warning", "pending", "error"] | None = omitted()
    entities: list[str] | None = omitted()
    entity_names: dict[str, str] | None = omitted()
    entity: str | None = omitted()
    tool: str | None = omitted()
    counters: RunCounters | None = omitted()
    run_id: str | None = omitted()
    report_url: str | None = omitted()
    error: ApiErrorBody | None = omitted()


class RunState(BaseModel):
    run_id: str
    status: RunStatus
    filename: str
    created_at: dt.datetime
    started_at: dt.datetime | None = None
    finished_at: dt.datetime | None = None
    error: ApiErrorBody | None = None
    last_seq: int = Field(default=0, description="Last event `seq`, to resume `/events`.")
    counters: RunCounters | None = None


class RunSummary(BaseModel):
    run_id: str
    status: RunStatus
    filename: str
    created_at: dt.datetime
    finished_at: dt.datetime | None = None
    company_name: str | None = None
    verdict: Verdict | None = None
    findings_count: int | None = None
    total_exposure: float | None = None
