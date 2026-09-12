"""asyncpg connection-pool lifecycle and the FastAPI dependency that exposes it."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import asyncpg
from fastapi import Request

from app.core.config import Settings, get_settings
from app.core.errors import DatabaseUnavailableError

logger = logging.getLogger(__name__)


async def create_pool(settings: Settings | None = None) -> asyncpg.Pool:
    """Create a connection pool.

    Used by the API at startup and standalone by the importer CLI.
    """
    settings = settings or get_settings()
    threshold = settings.blacklist_name_similarity_threshold

    async def init_connection(connection: asyncpg.Connection) -> None:
        """Pin the trigram threshold once per connection.

        The fuzzy name search uses the `%` operator so that the GIN trigram
        index can serve it; `%` reads its cutoff from this GUC. Setting it at
        connection setup keeps the search query down to a single round trip.
        """
        await connection.execute(f"SET pg_trgm.similarity_threshold = {threshold:.4f}")

    return await asyncpg.create_pool(
        dsn=settings.database_url,
        min_size=settings.database_pool_min_size,
        max_size=settings.database_pool_max_size,
        command_timeout=30,
        init=init_connection,
    )


@asynccontextmanager
async def pool_context(settings: Settings | None = None) -> AsyncIterator[asyncpg.Pool]:
    """Own a pool for the duration of a block, closing it on the way out."""
    pool = await create_pool(settings)
    try:
        yield pool
    finally:
        await pool.close()


def get_pool(request: Request) -> asyncpg.Pool:
    """FastAPI dependency returning the pool created during startup."""
    pool: asyncpg.Pool | None = getattr(request.app.state, "pool", None)
    if pool is None:
        raise DatabaseUnavailableError()
    return pool
