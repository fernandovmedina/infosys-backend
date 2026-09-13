"""Investigation-run API routes: dataset upload, validation and run lifecycle."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Body, Depends, File, Response, UploadFile, status

from app.api.dependencies import CurrentUserDependency, PoolDependency
from app.core.config import Settings, get_settings
from app.core.errors import UploadRejectedError
from app.fraud.schemas import FraudAnalysis, StartRunRequest
from app.runs import service
from app.runs.ingest import UploadedFile
from app.runs.schemas import (
    CreateRunResponse,
    DeleteRunsResponse,
    RunState,
    RunSummary,
    ValidationResult,
)

router = APIRouter(prefix="/runs", tags=["runs"])

_READ_CHUNK_BYTES = 1024 * 1024

Pool = PoolDependency
CurrentUser = CurrentUserDependency


async def _read_uploads(files: list[UploadFile], max_bytes: int) -> list[UploadedFile]:
    """Read every part into memory, refusing the upload as soon as it passes `max_bytes`."""
    uploads: list[UploadedFile] = []
    total = 0
    for upload in files:
        chunks: list[bytes] = []
        while chunk := await upload.read(_READ_CHUNK_BYTES):
            total += len(chunk)
            if total > max_bytes:
                raise UploadRejectedError(
                    "file_too_large",
                    f"El dataset supera el máximo de {max_bytes // (1024 * 1024)} MB.",
                    details={"max_bytes": max_bytes},
                    status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                )
            chunks.append(chunk)
        uploads.append(UploadedFile(upload.filename or "archivo", b"".join(chunks)))
    return uploads


@router.post(
    "",
    response_model=CreateRunResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a dataset (one .zip or several .csv) and validate it",
)
async def create_run(
    pool: Pool,
    user: CurrentUser,
    settings: Annotated[Settings, Depends(get_settings)],
    files: Annotated[list[UploadFile] | None, File()] = None,
) -> CreateRunResponse:
    """Create a run from the uploaded dataset.

    Send either exactly one `.zip` with one CSV per estate table, or one or more
    `.csv` files, in the repeated multipart field `files`. The tables are
    matched by file name (falling back to header columns) and diagnosed before
    this returns; read the result from `GET /runs/{run_id}/validation`.
    """
    uploads = await _read_uploads(files or [], settings.runs_max_upload_bytes)
    return await service.create_run(pool, user_id=user.id, files=uploads)


@router.get("", response_model=list[RunSummary], summary="The current user's runs, newest first")
async def list_runs(pool: Pool, user: CurrentUser) -> list[RunSummary]:
    return await service.list_runs(pool, user_id=user.id)


@router.delete(
    "",
    response_model=DeleteRunsResponse,
    summary="Clear the current user's run history (runs in progress are kept)",
)
async def delete_runs(pool: Pool, user: CurrentUser) -> DeleteRunsResponse:
    return await service.delete_runs(pool, user_id=user.id)


@router.get("/{run_id}", response_model=RunState, summary="A run's lifecycle state")
async def get_run(run_id: str, pool: Pool, user: CurrentUser) -> RunState:
    return await service.get_run(pool, run_id=run_id, user_id=user.id)


@router.get(
    "/{run_id}/validation",
    response_model=ValidationResult,
    summary="The dataset diagnostics of a run",
)
async def get_validation(run_id: str, pool: Pool, user: CurrentUser) -> ValidationResult:
    return await service.get_validation(pool, run_id=run_id, user_id=user.id)


@router.post(
    "/{run_id}/start",
    response_model=RunState,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start the fraud investigation of a validated dataset",
)
async def start_run(
    run_id: str,
    pool: Pool,
    user: CurrentUser,
    background_tasks: BackgroundTasks,
    payload: Annotated[StartRunRequest | None, Body()] = None,
) -> RunState:
    """Move the run to `running` and audit its dataset with the fraud engine.

    Returns immediately; poll `GET /runs/{run_id}` until the status is
    `completed` (read `GET /runs/{run_id}/result`) or `failed` (see `error`).
    A failed run can be started again.
    """
    state = await service.start_run(pool, run_id=run_id, user_id=user.id)
    seed = payload.seed if payload else 0
    background_tasks.add_task(service.execute_run, pool, run_id=run_id, seed=seed)
    return state


@router.get(
    "/{run_id}/result",
    response_model=FraudAnalysis,
    summary="The fraud analysis of a completed run",
)
async def get_result(run_id: str, pool: Pool, user: CurrentUser) -> FraudAnalysis:
    return await service.get_result(pool, run_id=run_id, user_id=user.id)


@router.delete(
    "/{run_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Delete a run and its uploaded dataset",
)
async def delete_run(run_id: str, pool: Pool, user: CurrentUser) -> None:
    await service.delete_run(pool, run_id=run_id, user_id=user.id)
