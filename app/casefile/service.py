"""Case-file business logic: ownership, availability and the cached index behind every view.

Only completed runs have a case file. Each request checks that the run belongs
to the caller, then reads the run's `CaseIndex` -- built once per completion from
the stored tables and the stored analysis -- and hands it to a pure view in
`views`. Building the index and the views block (DuckDB, big dicts), so they run
in a worker thread.
"""

from __future__ import annotations

from typing import Any

import asyncpg
from starlette.concurrency import run_in_threadpool

from app.casefile import index as case_index
from app.casefile import views
from app.casefile.index import CaseIndex, RunInfo
from app.casefile.schemas import (
    EntityPage,
    EntityStatus,
    EntityTimeline,
    ExportFormat,
    GraphData,
    GraphScope,
    RecordPage,
    RecordView,
    Report,
    SearchResponse,
)
from app.core.errors import (
    EntityNotFoundError,
    RecordNotFoundError,
    RunNotFoundError,
    RunResultNotAvailableError,
)
from app.fraud import repository as fraud_repository
from app.fraud.schemas import Submission
from app.runs import repository as runs_repository
from app.runs.estate import SourceTable
from app.runs.schemas import RunEvent
from app.runs.service import run_directory


async def _owned_run(pool: asyncpg.Pool, *, run_id: str, user_id: int) -> dict[str, Any]:
    async with pool.acquire() as conn:
        run = await runs_repository.get_run(conn, run_id=run_id, user_id=user_id)
    if run is None:
        raise RunNotFoundError()
    return run


async def _completed_index(pool: asyncpg.Pool, *, run_id: str, user_id: int) -> CaseIndex:
    run = await _owned_run(pool, run_id=run_id, user_id=user_id)
    if run["status"] != "completed":
        raise RunResultNotAvailableError(details={"status": run["status"]})
    info = RunInfo(
        run_id=run["id"],
        filename=run["filename"],
        sha256=run["sha256"],
        created_at=run["created_at"],
        finished_at=run["finished_at"],
        tables=run["validation"]["tables"],
    )
    hit = case_index.cached(info)
    if hit is not None:
        return hit
    async with pool.acquire() as conn:
        analysis = await fraud_repository.get_analysis(conn, run_id=run_id)
    if analysis is None:
        raise RunResultNotAvailableError(details={"status": run["status"]})
    built = await run_in_threadpool(
        case_index.build_index, run_directory(run_id) / "tables", info, analysis
    )
    case_index.remember(built)
    return built


async def get_report(pool: asyncpg.Pool, *, run_id: str, user_id: int) -> Report:
    index = await _completed_index(pool, run_id=run_id, user_id=user_id)
    return await run_in_threadpool(views.build_report, index)


async def get_submission(pool: asyncpg.Pool, *, run_id: str, user_id: int) -> Submission:
    index = await _completed_index(pool, run_id=run_id, user_id=user_id)
    return index.analysis.submission


async def get_records(
    pool: asyncpg.Pool, *, run_id: str, user_id: int, table: SourceTable, filters: dict[str, Any]
) -> RecordPage:
    index = await _completed_index(pool, run_id=run_id, user_id=user_id)
    return await run_in_threadpool(lambda: views.records_page(index, table=table, **filters))


async def get_record(
    pool: asyncpg.Pool, *, run_id: str, user_id: int, table: SourceTable, record_id: str
) -> RecordView:
    index = await _completed_index(pool, run_id=run_id, user_id=user_id)
    view = views.record_view(index, table, record_id)
    if view is None:
        raise RecordNotFoundError(f"No existe el registro {table}/{record_id}.")
    return view


async def get_entities(
    pool: asyncpg.Pool,
    *,
    run_id: str,
    user_id: int,
    status: EntityStatus | None,
    limit: int | None,
    cursor: str | None,
) -> EntityPage:
    index = await _completed_index(pool, run_id=run_id, user_id=user_id)
    return await run_in_threadpool(
        lambda: views.entities_page(index, status=status, limit=limit, cursor=cursor)
    )


async def get_graph(
    pool: asyncpg.Pool, *, run_id: str, user_id: int, scope: GraphScope
) -> GraphData:
    index = await _completed_index(pool, run_id=run_id, user_id=user_id)
    return await run_in_threadpool(views.build_graph, index, scope)


async def get_timeline(
    pool: asyncpg.Pool, *, run_id: str, user_id: int, entity_id: str
) -> EntityTimeline:
    index = await _completed_index(pool, run_id=run_id, user_id=user_id)
    timeline = await run_in_threadpool(views.build_timeline, index, entity_id)
    if timeline is None:
        raise EntityNotFoundError(f"No existe la entidad {entity_id}.")
    return timeline


async def search(pool: asyncpg.Pool, *, run_id: str, user_id: int, query: str) -> SearchResponse:
    if not query.strip():
        await _owned_run(pool, run_id=run_id, user_id=user_id)
        return SearchResponse(query=query, hits=[])
    index = await _completed_index(pool, run_id=run_id, user_id=user_id)
    async with pool.acquire() as conn:
        rows = await runs_repository.list_events(conn, run_id=run_id)
    events = [RunEvent.model_validate(row) for row in rows]
    return await run_in_threadpool(views.search, index, query, events)


async def export_case_file(
    pool: asyncpg.Pool, *, run_id: str, user_id: int, format: ExportFormat
) -> str:
    """Export the legacy static HTML snapshot or the current Markdown case file."""
    index = await _completed_index(pool, run_id=run_id, user_id=user_id)
    if format == "html":
        return index.analysis.case_file_html
    return await run_in_threadpool(views.render_markdown, index)
