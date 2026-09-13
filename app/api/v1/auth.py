"""Auth API routes: register, sign-in, and the session cookie.

No email verification: registering logs the account in immediately, the same
way signing in does.
"""

from __future__ import annotations

import datetime as dt

import asyncpg
from fastapi import APIRouter, Response, status

from app.api.dependencies import PoolDependency, SessionTokenDependency, SettingsDependency
from app.auth import service
from app.auth.entities import User
from app.auth.schemas import LoginRequest, RegisterRequest, SessionResponse, UserPublic
from app.core.config import Settings

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_session_cookie(response: Response, *, token: str, settings: Settings) -> None:
    response.set_cookie(
        key=settings.auth_session_cookie_name,
        value=token,
        max_age=settings.auth_session_ttl_days * 24 * 60 * 60,
        httponly=True,
        secure=settings.auth_session_cookie_secure,
        samesite="lax",
        path="/",
    )


async def _start_session(
    response: Response,
    *,
    user: User,
    pool: asyncpg.Pool,
    settings: Settings,
) -> SessionResponse:
    """Create a session and translate it into the shared HTTP response."""
    session = await service.create_session(
        pool,
        user_id=user.id,
        ttl=dt.timedelta(days=settings.auth_session_ttl_days),
    )
    _set_session_cookie(response, token=session.token, settings=settings)
    return SessionResponse(user=UserPublic.from_domain(user))


@router.post(
    "/register",
    response_model=SessionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an account and start a session",
)
async def register(
    payload: RegisterRequest,
    response: Response,
    pool: PoolDependency,
    settings: SettingsDependency,
) -> SessionResponse:
    user = await service.register(
        pool, name=payload.name, email=payload.email, password=payload.password
    )
    return await _start_session(response, user=user, pool=pool, settings=settings)


@router.post(
    "/login",
    response_model=SessionResponse,
    summary="Sign in with email and password",
)
async def login(
    payload: LoginRequest,
    response: Response,
    pool: PoolDependency,
    settings: SettingsDependency,
) -> SessionResponse:
    user = await service.login(pool, email=payload.email, password=payload.password)
    return await _start_session(response, user=user, pool=pool, settings=settings)


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="End the current session",
)
async def logout(
    response: Response,
    pool: PoolDependency,
    settings: SettingsDependency,
    session_token: SessionTokenDependency,
) -> None:
    await service.logout(pool, session_token=session_token)
    response.delete_cookie(key=settings.auth_session_cookie_name, path="/")


@router.get(
    "/me",
    response_model=UserPublic,
    summary="The currently signed-in user",
)
async def me(
    pool: PoolDependency,
    session_token: SessionTokenDependency,
) -> UserPublic:
    user = await service.get_current_user(pool, session_token=session_token)
    return UserPublic.from_domain(user)
