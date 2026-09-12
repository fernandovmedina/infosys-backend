"""Shared fixtures.

The endpoint tests run against a real PostgreSQL instance seeded from
`black_list.csv` (see README.md -> Getting started). They are skipped, not
failed, when no database is reachable, so the pure-Python tests still run in an
environment without Docker.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator

import asyncpg
import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import get_settings
from app.core.database import create_pool
from app.main import create_app


def _database_available() -> bool:
    async def probe() -> bool:
        try:
            pool = await create_pool()
        except OSError, asyncpg.PostgresError:
            return False
        try:
            await pool.fetchval("SELECT count(*) FROM sat_blacklist_record")
            return True
        except asyncpg.PostgresError:
            return False
        finally:
            await pool.close()

    try:
        return asyncio.run(probe())
    except Exception:  # pragma: no cover - defensive
        return False


DATABASE_AVAILABLE = _database_available()

requires_database = pytest.mark.skipif(
    not DATABASE_AVAILABLE,
    reason=(
        "No seeded PostgreSQL reachable at DATABASE_URL. "
        "Run: docker compose up -d && uv run sat-blacklist-import"
    ),
)


@pytest.fixture(scope="session")
def settings() -> Iterator[object]:
    yield get_settings()


@pytest.fixture
async def pool() -> AsyncIterator[asyncpg.Pool]:
    """A connection pool for tests that talk to the repository directly."""
    pool = await create_pool()
    try:
        yield pool
    finally:
        await pool.close()


@pytest.fixture
async def client(pool: asyncpg.Pool) -> AsyncIterator[AsyncClient]:
    """An HTTP client bound to the app, sharing the test's pool."""
    app = create_app()
    app.state.pool = pool
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client
