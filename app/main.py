"""FastAPI application factory and lifespan wiring."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.router import api_router
from app.core.config import get_settings
from app.core.database import create_pool
from app.core.errors import register_exception_handlers

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Open the connection pool on startup and close it on shutdown."""
    settings = get_settings()
    app.state.pool = await create_pool(settings)
    logger.info("Database pool ready")
    try:
        yield
    finally:
        pool = getattr(app.state, "pool", None)
        if pool is not None:
            await pool.close()
            logger.info("Database pool closed")


def create_app() -> FastAPI:
    """Build the application."""
    app = FastAPI(
        title="infosys-backend",
        version="0.1.0",
        description="Backend de infosys.",
        lifespan=lifespan,
    )
    register_exception_handlers(app)
    app.include_router(api_router)

    @app.get("/health", tags=["health"], summary="Liveness probe")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
