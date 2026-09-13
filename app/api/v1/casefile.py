"""Interactive case-file API routes: report, drill-down, graph, timeline, search and export.

Every route needs a session and a *completed* run owned by the caller: an
unknown run is `404 run_not_found`, one without a finished analysis is
`409 result_not_available`.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response

from app.api.dependencies import CurrentUserDependency, PoolDependency
from app.casefile import service
from app.casefile.explainability import ExplainAnswer, ExplainQuestion
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
from app.core.config import Settings, get_settings
from app.fraud.schemas import Submission
from app.runs.estate import SourceTable

router = APIRouter(prefix="/runs/{run_id}", tags=["case file"])

Pool = PoolDependency
CurrentUser = CurrentUserDependency
PageLimit = Annotated[int | None, Query(ge=1, le=500)]
Cursor = Annotated[str | None, Query(description="Opaque cursor from `next_cursor`.")]

_EXPORT_MEDIA_TYPES: dict[str, str] = {
    "html": "text/html; charset=utf-8",
    "md": "text/markdown; charset=utf-8",
}


@router.get("/report", response_model=Report, summary="The full case-file view model")
async def get_report(run_id: str, pool: Pool, user: CurrentUser) -> Report:
    return await service.get_report(pool, run_id=run_id, user_id=user.id)


@router.get(
    "/submission",
    response_model=Submission,
    summary="The official submission JSON, as a download",
)
async def get_submission(run_id: str, pool: Pool, user: CurrentUser) -> Response:
    submission = await service.get_submission(pool, run_id=run_id, user_id=user.id)
    return Response(
        content=submission.model_dump_json(indent=2),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{run_id}.submission.json"'},
    )


@router.get(
    "/export",
    summary="Export the legacy static HTML snapshot or the current Markdown case file",
    responses={200: {"content": {"text/html": {}, "text/markdown": {}}}},
)
async def export_case_file(
    run_id: str,
    pool: Pool,
    user: CurrentUser,
    format: Annotated[ExportFormat, Query()] = "html",
) -> Response:
    document = await service.export_case_file(pool, run_id=run_id, user_id=user.id, format=format)
    return Response(
        content=document,
        media_type=_EXPORT_MEDIA_TYPES[format],
        headers={"Content-Disposition": f'attachment; filename="{run_id}.case_file.{format}"'},
    )


@router.get(
    "/records",
    response_model=RecordPage,
    summary="One estate table of the run, filtered and paginated",
)
async def get_records(
    run_id: str,
    pool: Pool,
    user: CurrentUser,
    table: Annotated[SourceTable, Query()],
    entity: Annotated[str | None, Query(description="Entity id or name, partial match.")] = None,
    risk: Annotated[EntityStatus | None, Query()] = None,
    cited: Annotated[bool | None, Query(description="Only records cited as exhibits.")] = None,
    date_from: Annotated[
        str | None, Query(alias="from", description="ISO date, inclusive.")
    ] = None,
    date_to: Annotated[str | None, Query(alias="to", description="ISO date, inclusive.")] = None,
    amount_min: Annotated[float | None, Query()] = None,
    amount_max: Annotated[float | None, Query()] = None,
    status: Annotated[str | None, Query(description="Value of the `status` column.")] = None,
    channel: Annotated[str | None, Query(description="Value of the `channel` column.")] = None,
    limit: PageLimit = None,
    cursor: Cursor = None,
) -> RecordPage:
    return await service.get_records(
        pool,
        run_id=run_id,
        user_id=user.id,
        table=table,
        filters={
            "entity": entity,
            "risk": risk,
            "cited": cited,
            "date_from": date_from,
            "date_to": date_to,
            "amount_min": amount_min,
            "amount_max": amount_max,
            "status": status,
            "channel": channel,
            "limit": limit,
            "cursor": cursor,
        },
    )


@router.get(
    "/records/{table}/{record_id}",
    response_model=RecordView,
    summary="One record with its citations and related records",
)
async def get_record(
    run_id: str, table: SourceTable, record_id: str, pool: Pool, user: CurrentUser
) -> RecordView:
    return await service.get_record(
        pool, run_id=run_id, user_id=user.id, table=table, record_id=record_id
    )


@router.get(
    "/entities",
    response_model=EntityPage,
    summary="Vendors, employees and flagged entities; accused first",
)
async def get_entities(
    run_id: str,
    pool: Pool,
    user: CurrentUser,
    status: Annotated[EntityStatus | None, Query()] = None,
    limit: PageLimit = None,
    cursor: Cursor = None,
) -> EntityPage:
    return await service.get_entities(
        pool, run_id=run_id, user_id=user.id, status=status, limit=limit, cursor=cursor
    )


@router.get(
    "/entities/{entity_id}/timeline",
    response_model=EntityTimeline,
    summary="Contracts, orders, invoices, payments and registration of one entity",
)
async def get_timeline(
    run_id: str, entity_id: str, pool: Pool, user: CurrentUser
) -> EntityTimeline:
    return await service.get_timeline(pool, run_id=run_id, user_id=user.id, entity_id=entity_id)


@router.get("/graph", response_model=GraphData, summary="Entities and the money between them")
async def get_graph(
    run_id: str,
    pool: Pool,
    user: CurrentUser,
    scope: Annotated[GraphScope, Query()] = "flagged",
) -> GraphData:
    return await service.get_graph(pool, run_id=run_id, user_id=user.id, scope=scope)


@router.get(
    "/search",
    response_model=SearchResponse,
    summary='"Why?" search over entities and exhibits',
)
async def search(
    run_id: str,
    pool: Pool,
    user: CurrentUser,
    q: Annotated[str, Query(max_length=200)] = "",
) -> SearchResponse:
    return await service.search(pool, run_id=run_id, user_id=user.id, query=q)


@router.post(
    "/explain",
    response_model=ExplainAnswer,
    summary="Ask the local model to explain the completed, evidence-backed case file",
)
async def explain_case_file(
    run_id: str,
    request: ExplainQuestion,
    pool: Pool,
    user: CurrentUser,
    settings: Annotated[Settings, Depends(get_settings)],
) -> ExplainAnswer:
    return await service.explain(
        pool,
        run_id=run_id,
        user_id=user.id,
        question=request.question,
        settings=settings,
    )
