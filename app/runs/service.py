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

import dataclasses
import logging
import secrets
import shutil
from pathlib import Path
from typing import Any

import asyncpg
from starlette.concurrency import run_in_threadpool

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
from app.fraud.schemas import FraudAnalysis
from app.runs import repository
from app.runs.ingest import Dataset, UploadedFile, ingest, write_tables
from app.runs.schemas import (
    ApiErrorBody,
    CreateRunResponse,
    DeleteRunsResponse,
    RunState,
    RunSummary,
    ValidationResult,
)

RUN_HISTORY_LIMIT = 100

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


def _to_state(run: dict[str, Any]) -> RunState:
    return RunState(
        run_id=run["id"],
        status=run["status"],
        filename=run["filename"],
        created_at=run["created_at"],
        started_at=run["started_at"],
        finished_at=run["finished_at"],
        error=ApiErrorBody(**run["error"]) if run["error"] else None,
    )


async def get_run(pool: asyncpg.Pool, *, run_id: str, user_id: int) -> RunState:
    return _to_state(await _get_owned_run(pool, run_id=run_id, user_id=user_id))


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
    return [
        RunSummary(
            run_id=run["id"],
            status=run["status"],
            filename=run["filename"],
            created_at=run["created_at"],
            finished_at=run["finished_at"],
        )
        for run in runs
    ]


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
            raise InvalidRunStateError("No se puede eliminar una corrida en curso.")
    await run_in_threadpool(_remove_datasets, [run_id])


async def delete_runs(pool: asyncpg.Pool, *, user_id: int) -> DeleteRunsResponse:
    """Clear the user's history; runs still in progress are kept."""
    async with pool.acquire() as conn:
        run_ids = await repository.delete_runs(conn, user_id=user_id)
    await run_in_threadpool(_remove_datasets, run_ids)
    return DeleteRunsResponse(deleted=len(run_ids))


async def start_run(pool: asyncpg.Pool, *, run_id: str, user_id: int) -> RunState:
    """Mark the run `running`. The caller schedules `execute_run` to do the work."""
    run = await _get_owned_run(pool, run_id=run_id, user_id=user_id)
    if run["status"] not in ("ready", "failed"):
        raise InvalidRunStateError(f"No se puede iniciar una corrida en estado {run['status']}.")
    if any(table["status"] == "error" for table in run["validation"]["tables"]):
        raise ValidationBlockedError()
    async with pool.acquire() as conn:
        running = await repository.mark_running(conn, run_id=run_id, user_id=user_id)
    if running is None:  # another request started it in between
        raise InvalidRunStateError("La corrida ya se está ejecutando.")
    return _to_state(running)


async def execute_run(pool: asyncpg.Pool, *, run_id: str, seed: int) -> None:
    """Audit a `running` run's dataset and store the outcome. Never raises."""
    error: dict[str, Any] | None = None
    analysis: FraudAnalysis | None = None
    try:
        analysis = await run_in_threadpool(
            fraud_service.analyze_run_tables, run_directory(run_id) / "tables", seed=seed
        )
    except AppError as exc:
        error = {"code": exc.code, "message": exc.message, "details": exc.details}
    except Exception:
        logger.exception("Fraud analysis of run %s crashed", run_id)
        error = {
            "code": "investigation_failed",
            "message": "La investigación falló por un error interno.",
            "details": None,
        }

    try:
        async with pool.acquire() as conn, conn.transaction():
            if analysis is not None:
                await fraud_repository.save_analysis(conn, run_id=run_id, analysis=analysis)
                await repository.mark_finished(conn, run_id=run_id, status="completed")
            else:
                await repository.mark_finished(conn, run_id=run_id, status="failed", error=error)
    except Exception:
        logger.exception("Could not store the fraud analysis of run %s", run_id)
        try:
            async with pool.acquire() as conn:
                await repository.mark_finished(
                    conn,
                    run_id=run_id,
                    status="failed",
                    error={
                        "code": "database_unavailable",
                        "message": "No se pudo guardar el resultado de la investigación.",
                        "details": None,
                    },
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
