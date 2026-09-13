"""Framework-independent asyncpg connection-pool lifecycle helpers."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import asyncpg

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)


async def create_pool(settings: Settings | None = None) -> asyncpg.Pool:
    """Create a connection pool.

    Used by the API at startup and standalone by the importer CLI.
    """
    settings = settings or get_settings()
    return await asyncpg.create_pool(
        dsn=settings.database_url,
        min_size=settings.database_pool_min_size,
        max_size=settings.database_pool_max_size,
        command_timeout=30,
        timeout=settings.database_connect_timeout_seconds,
    )


@asynccontextmanager
async def pool_context(settings: Settings | None = None) -> AsyncIterator[asyncpg.Pool]:
    """Own a pool for the duration of a block, closing it on the way out."""
    pool = await create_pool(settings)
    try:
        yield pool
    finally:
        await pool.close()
