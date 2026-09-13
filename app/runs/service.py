"""Business logic for investigation runs: upload, validation and lifecycle.

Validation is synchronous: by the time `create_run` returns, the dataset has
been read, its tables written to disk and the diagnostics stored, so a new run
starts out `ready`. Blocking diagnostics do not fail the upload; they keep the
run from starting, and the validation screen explains why.

Starting a run moves it to `running` and returns right away; `execute_run` then
audits the stored tables with the fraud engine (outside the request, in a worker
thread) and closes the run as `completed`, with its `fraud_analysis`, or `failed`.
"""

from __future__ import annotations

import asyncio
import dataclasses
import datetime as dt
import json
import logging
import secrets
import shutil
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import asyncpg
from starlette.concurrency import run_in_threadpool

from app.casefile.index import identify_company
from app.core.config import get_settings
from app.core.errors import (
    AppError,
    InvalidRunStateError,
    RunNotFoundError,
    RunResultNotAvailableError,
    ValidationBlockedError,
)
from app.fraud import repository as fraud_repository
from app.fraud import service as fraud_service
from app.fraud.schemas import FraudAnalysis, Submission
from app.runs import events as run_events
from app.runs import repository
from app.runs.ingest import Dataset, UploadedFile, ingest, write_tables
from app.runs.schemas import (
    AgentRole,
    ApiErrorBody,
    CreateRunResponse,
    DeleteRunsResponse,
    RunCounters,
    RunEvent,
    RunState,
    RunSummary,
    ValidationResult,
    Verdict,
)

RUN_HISTORY_LIMIT = 100
EVENT_POLL_SECONDS = 0.5
EVENT_HEARTBEAT_SECONDS = 15.0
_TERMINAL_EVENTS = ("completed", "failed")

logger = logging.getLogger(__name__)


def run_directory(run_id: str) -> Path:
    return Path(get_settings().runs_storage_dir) / run_id


def _new_run_id() -> str:
    return f"run_{secrets.token_hex(8)}"


def _validation_payload(dataset: Dataset) -> dict[str, Any]:
    return {
        "tables": [dataclasses.asdict(d) for d in dataset.diagnostics],
        "column_warnings": [dataclasses.asdict(w) for w in dataset.column_warnings],
        "ignored_files": [dataclasses.asdict(i) for i in dataset.ignored_files],
    }


async def create_run(
    pool: asyncpg.Pool, *, user_id: int, files: list[UploadedFile]
) -> CreateRunResponse:
    dataset = await run_in_threadpool(ingest, files)

    run_id = _new_run_id()
    directory = run_directory(run_id)
    await run_in_threadpool(write_tables, dataset, directory / "tables")
    try:
        async with pool.acquire() as conn:
            run = await repository.create_run(
                conn,
                run_id=run_id,
                user_id=user_id,
                status="ready",
                filename=dataset.filename,
                format=dataset.format,
                sha256=dataset.sha256,
                validation=_validation_payload(dataset),
            )
    except BaseException:
        shutil.rmtree(directory, ignore_errors=True)
        raise

    return CreateRunResponse(run_id=run["id"], status=run["status"])


async def _get_owned_run(pool: asyncpg.Pool, *, run_id: str, user_id: int) -> dict[str, Any]:
    async with pool.acquire() as conn:
        run = await repository.get_run(conn, run_id=run_id, user_id=user_id)
    if run is None:
        raise RunNotFoundError()
    return run


def verdict_of(submission: Submission) -> Verdict:
    """The case file's one-word conclusion, straight from the submission."""
    if any(finding.confidence == "proven" for finding in submission.findings):
        return "fraud_proven"
    if submission.findings:
        return "fraud_probable"
    if submission.leads_not_pursued:
        return "clean_with_leads"
    return "clean"


def _to_state(run: dict[str, Any], *, last_seq: int = 0) -> RunState:
    started_at: dt.datetime | None = run["started_at"]
    return RunState(
        run_id=run["id"],
        status=run["status"],
        filename=run["filename"],
        created_at=run["created_at"],
        started_at=started_at,
        finished_at=run["finished_at"],
        error=ApiErrorBody(**run["error"]) if run["error"] else None,
        last_seq=last_seq,
        counters=RunCounters(**run_events.counters(started_at, run["finished_at"]))
        if started_at
        else None,
    )


async def get_run(pool: asyncpg.Pool, *, run_id: str, user_id: int) -> RunState:
    run = await _get_owned_run(pool, run_id=run_id, user_id=user_id)
    async with pool.acquire() as conn:
        last_seq = await repository.last_event_seq(conn, run_id=run_id)
    return _to_state(run, last_seq=last_seq)


async def get_validation(pool: asyncpg.Pool, *, run_id: str, user_id: int) -> ValidationResult:
    run = await _get_owned_run(pool, run_id=run_id, user_id=user_id)
    return ValidationResult(
        run_id=run["id"],
        status=run["status"],
        filename=run["filename"],
        format=run["format"],
        sha256=run["sha256"],
        **run["validation"],
    )


async def list_runs(pool: asyncpg.Pool, *, user_id: int) -> list[RunSummary]:
    async with pool.acquire() as conn:
        runs = await repository.list_runs(conn, user_id=user_id, limit=RUN_HISTORY_LIMIT)
    summaries = []
    for run in runs:
        submission = run["submission"]
        summaries.append(
            RunSummary(
                run_id=run["id"],
                status=run["status"],
                filename=run["filename"],
                created_at=run["created_at"],
                finished_at=run["finished_at"],
                company_name=run["company_name"],
                verdict=verdict_of(Submission.model_validate(submission)) if submission else None,
                findings_count=run["findings_count"],
                total_exposure=run["total_exposure"],
            )
        )
    return summaries


def _remove_datasets(run_ids: list[str]) -> None:
    for run_id in run_ids:
        shutil.rmtree(run_directory(run_id), ignore_errors=True)


async def delete_run(pool: asyncpg.Pool, *, run_id: str, user_id: int) -> None:
    """Delete the run and its stored dataset. A running run cannot be deleted."""
    async with pool.acquire() as conn, conn.transaction():
        run = await repository.get_run(conn, run_id=run_id, user_id=user_id)
        if run is None:
            raise RunNotFoundError()
        if not await repository.delete_run(conn, run_id=run_id, user_id=user_id):
            raise InvalidRunStateError("A running investigation cannot be deleted.")
    await run_in_threadpool(_remove_datasets, [run_id])


async def delete_runs(pool: asyncpg.Pool, *, user_id: int) -> DeleteRunsResponse:
    """Clear the user's history; runs still in progress are kept."""
    async with pool.acquire() as conn:
        run_ids = await repository.delete_runs(conn, user_id=user_id)
    await run_in_threadpool(_remove_datasets, run_ids)
    return DeleteRunsResponse(deleted=len(run_ids))


async def start_run(pool: asyncpg.Pool, *, run_id: str, user_id: int) -> RunState:
    """Mark the run `running` and clear a previous attempt's log.

    The caller schedules `execute_run` to do the work.
    """
    run = await _get_owned_run(pool, run_id=run_id, user_id=user_id)
    if run["status"] not in ("ready", "failed"):
        raise InvalidRunStateError(f"A run in state {run['status']} cannot be started.")
    if any(table["status"] == "error" for table in run["validation"]["tables"]):
        raise ValidationBlockedError()
    async with pool.acquire() as conn, conn.transaction():
        running = await repository.mark_running(conn, run_id=run_id, user_id=user_id)
    if running is None:  # another request started it in between
        raise InvalidRunStateError("The run is already executing.")
    return _to_state(running)


async def _record_events(
    conn: asyncpg.Connection,
    *,
    run_id: str,
    started_at: dt.datetime | None,
    drafts: list[run_events.EventDraft],
) -> None:
    counters = run_events.counters(started_at)
    await repository.insert_events(
        conn,
        run_id=run_id,
        events=[
            (draft.type, draft.role, {**draft.as_payload(), "counters": counters})
            for draft in drafts
        ],
    )


def _analyze(run_id: str, *, seed: int) -> tuple[FraudAnalysis, run_events.EntityNames, Any]:
    tables_dir = run_directory(run_id) / "tables"
    analysis = fraud_service.analyze_run_tables(tables_dir, seed=seed)
    names = run_events.EntityNames.load(tables_dir)
    try:
        company = identify_company(tables_dir)
    except Exception:  # the company name is a nicety of the history, never a reason to fail
        logger.exception("Could not identify the audited company of run %s", run_id)
        company = (None, None)
    return analysis, names, company


async def execute_run(pool: asyncpg.Pool, *, run_id: str, seed: int) -> None:
    """Audit a `running` run's dataset, log each step and store the outcome. Never raises."""
    started_at: dt.datetime | None = None
    try:
        async with pool.acquire() as conn:
            run = await repository.get_run_by_id(conn, run_id=run_id)
            if run is not None:
                started_at = run["started_at"]
                rows = {t["name"]: int(t["rows"]) for t in run["validation"]["tables"]}
                await _record_events(
                    conn,
                    run_id=run_id,
                    started_at=started_at,
                    drafts=run_events.start_events(rows),
                )
    except Exception:
        logger.exception("Could not log the start of run %s", run_id)

    error: dict[str, Any] | None = None
    analysis: FraudAnalysis | None = None
    names = run_events.EntityNames()
    company: tuple[str | None, str | None] = (None, None)
    try:
        analysis, names, company = await run_in_threadpool(_analyze, run_id, seed=seed)
    except AppError as exc:
        error = {"code": exc.code, "message": exc.message, "details": exc.details}
    except Exception:
        logger.exception("Fraud analysis of run %s crashed", run_id)
        error = {
            "code": "investigation_failed",
            "message": "The investigation failed because of an internal error.",
            "details": None,
        }

    try:
        async with pool.acquire() as conn, conn.transaction():
            if analysis is not None:
                await fraud_repository.save_analysis(conn, run_id=run_id, analysis=analysis)
                await repository.set_company(conn, run_id=run_id, rfc=company[0], name=company[1])
                await _record_events(
                    conn,
                    run_id=run_id,
                    started_at=started_at,
                    drafts=run_events.analysis_events(analysis, run_id=run_id, names=names),
                )
                await repository.mark_finished(conn, run_id=run_id, status="completed")
            else:
                assert error is not None
                await _record_events(
                    conn,
                    run_id=run_id,
                    started_at=started_at,
                    drafts=[run_events.failed_event(error)],
                )
                await repository.mark_finished(conn, run_id=run_id, status="failed", error=error)
    except Exception:
        logger.exception("Could not store the fraud analysis of run %s", run_id)
        storage_error = {
            "code": "database_unavailable",
            "message": "The investigation result could not be saved.",
            "details": None,
        }
        try:
            async with pool.acquire() as conn, conn.transaction():
                await _record_events(
                    conn,
                    run_id=run_id,
                    started_at=started_at,
                    drafts=[run_events.failed_event(storage_error)],
                )
                await repository.mark_finished(
                    conn, run_id=run_id, status="failed", error=storage_error
                )
        except Exception:
            logger.exception("Run %s is left running: the database is unreachable", run_id)


async def get_result(pool: asyncpg.Pool, *, run_id: str, user_id: int) -> FraudAnalysis:
    run = await _get_owned_run(pool, run_id=run_id, user_id=user_id)
    if run["status"] != "completed":
        raise RunResultNotAvailableError()
    async with pool.acquire() as conn:
        analysis = await fraud_repository.get_analysis(conn, run_id=run_id)
    if analysis is None:
        raise RunResultNotAvailableError()
    return analysis


# ---------------------------------------------------------------------------
# Investigation log
# ---------------------------------------------------------------------------


async def get_log(
    pool: asyncpg.Pool,
    *,
    run_id: str,
    user_id: int,
    role: AgentRole | None = None,
    entity: str | None = None,
) -> list[RunEvent]:
    await _get_owned_run(pool, run_id=run_id, user_id=user_id)
    async with pool.acquire() as conn:
        rows = await repository.list_events(conn, run_id=run_id, role=role, entity=entity)
    return [RunEvent.model_validate(row) for row in rows]


def _sse_frame(event: RunEvent) -> str:
    data = json.dumps(event.model_dump(mode="json"), ensure_ascii=False)
    return f"id: {event.seq}\nevent: {event.type}\ndata: {data}\n\n"


async def open_event_stream(
    pool: asyncpg.Pool, *, run_id: str, user_id: int, last_seq: int
) -> AsyncIterator[str]:
    """Check ownership now (so errors keep the JSON envelope), then stream the run's events.

    The stream replays every event after `last_seq`, then follows new ones until the
    run's terminal event. It ends on its own when the run is not running and has
    nothing newer, so a finished or never-started run does not hold a connection.
    """
    await _get_owned_run(pool, run_id=run_id, user_id=user_id)
    return _follow_events(pool, run_id=run_id, last_seq=last_seq)


async def _follow_events(pool: asyncpg.Pool, *, run_id: str, last_seq: int) -> AsyncIterator[str]:
    seq = last_seq
    loop = asyncio.get_running_loop()
    last_write = loop.time()
    while True:
        async with pool.acquire() as conn:
            rows = await repository.list_events(conn, run_id=run_id, after_seq=seq)
            status = await repository.get_run_status(conn, run_id=run_id) if not rows else None
        for row in rows:
            event = RunEvent.model_validate(row)
            seq = event.seq
            yield _sse_frame(event)
            last_write = loop.time()
            if event.type in _TERMINAL_EVENTS:
                return
        if not rows and status != "running":
            return
        if loop.time() - last_write >= EVENT_HEARTBEAT_SECONDS:
            yield ": ping\n\n"
            last_write = loop.time()
        await asyncio.sleep(EVENT_POLL_SECONDS)
