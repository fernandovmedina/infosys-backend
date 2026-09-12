"""SAT blacklist API routes."""

from __future__ import annotations

from typing import Annotated

import asyncpg
from fastapi import APIRouter, Depends, status

from app.core.database import get_pool
from app.sat.schemas import BlacklistCheckRequest, BlacklistCheckResponse
from app.sat.service import check_companies

router = APIRouter(prefix="/sat/blacklist", tags=["SAT blacklist"])


@router.post(
    "/check",
    response_model=BlacklistCheckResponse,
    status_code=status.HTTP_200_OK,
    summary="Check companies against the SAT blacklist",
    response_description="One result per requested company, in request order.",
)
async def check_blacklist(
    payload: BlacklistCheckRequest,
    pool: Annotated[asyncpg.Pool, Depends(get_pool)],
) -> BlacklistCheckResponse:
    """Check one or more companies against the SAT Art. 69-B listing.

    Each company is identified by `rfc`, `name`, or both. The whole batch is
    resolved in a single database query.

    A company is matched by exact RFC first; failing that by exact company name
    (with and without its corporate suffix); failing that by trigram similarity.
    `match_type` reports which of those produced the match.

    `blacklisted` means the company appears in the listing at all. Check
    `effective_situacion` and `cleared` to tell an open procedure ("Presunto",
    "Definitivo") from one the taxpayer already rebutted ("Desvirtuado",
    "Sentencia Favorable").
    """
    results = await check_companies(pool, payload.companies)
    return BlacklistCheckResponse(results=results)
