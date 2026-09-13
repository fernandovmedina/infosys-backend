"""Response models for the investigation-run endpoints.

Field names mirror the frontend's `lib/runs/types.ts`.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Literal

from pydantic import BaseModel

from app.runs.estate import SourceTable

type RunStatus = Literal["validating", "ready", "running", "completed", "failed"]


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


class RunState(BaseModel):
    run_id: str
    status: RunStatus
    filename: str
    created_at: dt.datetime
    started_at: dt.datetime | None = None
    finished_at: dt.datetime | None = None
    error: ApiErrorBody | None = None


class RunSummary(BaseModel):
    run_id: str
    status: RunStatus
    filename: str
    created_at: dt.datetime
    finished_at: dt.datetime | None = None
