"""Reusable type aliases for FastAPI dependencies."""

from __future__ import annotations

from typing import Annotated

import asyncpg
from fastapi import Depends, Request

from app.auth import service as auth_service
from app.auth.entities import User
from app.core.config import Settings, get_settings
from app.core.errors import DatabaseUnavailableError


def get_pool(request: Request) -> asyncpg.Pool:
    """Return the connection pool created during application startup."""
    pool: asyncpg.Pool | None = getattr(request.app.state, "pool", None)
    if pool is None:
        raise DatabaseUnavailableError()
    return pool


def get_session_token(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> str | None:
    """Read the configured session cookie from the current request."""
    return request.cookies.get(settings.auth_session_cookie_name)


PoolDependency = Annotated[asyncpg.Pool, Depends(get_pool)]
SettingsDependency = Annotated[Settings, Depends(get_settings)]
SessionTokenDependency = Annotated[str | None, Depends(get_session_token)]


async def get_current_user(pool: PoolDependency, session_token: SessionTokenDependency) -> User:
    """The signed-in user; raises `not_authenticated` without a valid session cookie."""
    return await auth_service.get_current_user(pool, session_token=session_token)


CurrentUserDependency = Annotated[User, Depends(get_current_user)]
