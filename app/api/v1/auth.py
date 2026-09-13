"""Auth API routes: register, sign-in, and the session cookie.

No email verification: registering logs the account in immediately, the same
way signing in does.
"""

from __future__ import annotations

from typing import Annotated

import asyncpg
from fastapi import APIRouter, Depends, Response, status

from app.auth import service
from app.auth.schemas import LoginRequest, RegisterRequest, SessionResponse, UserPublic
from app.core.config import Settings, get_settings
from app.core.database import get_pool
from app.core.session import get_session_token

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


@router.post(
    "/register",
    response_model=SessionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an account and start a session",
)
async def register(
    payload: RegisterRequest,
    response: Response,
    pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> SessionResponse:
    user = await service.register(
        pool, name=payload.name, email=payload.email, password=payload.password
    )
    token, _ = await service.create_session(pool, user_id=user.id)
    _set_session_cookie(response, token=token, settings=settings)
    return SessionResponse(user=user)


@router.post(
    "/login",
    response_model=SessionResponse,
    summary="Sign in with email and password",
)
async def login(
    payload: LoginRequest,
    response: Response,
    pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> SessionResponse:
    user = await service.login(pool, email=payload.email, password=payload.password)
    token, _ = await service.create_session(pool, user_id=user.id)
    _set_session_cookie(response, token=token, settings=settings)
    return SessionResponse(user=user)


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="End the current session",
)
async def logout(
    response: Response,
    pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    settings: Annotated[Settings, Depends(get_settings)],
    session_token: Annotated[str | None, Depends(get_session_token)],
) -> None:
    await service.logout(pool, session_token=session_token)
    response.delete_cookie(key=settings.auth_session_cookie_name, path="/")


@router.get(
    "/me",
    response_model=UserPublic,
    summary="The currently signed-in user",
)
async def me(
    pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    session_token: Annotated[str | None, Depends(get_session_token)],
) -> UserPublic:
    return await service.get_current_user(pool, session_token=session_token)
