"""Business logic for registration, sign-in, and sessions.

Passwords never leave this module unhashed; the repository only ever sees the
PBKDF2 hash.
"""

from __future__ import annotations

import datetime as dt

import asyncpg

from app.auth import repository
from app.auth.schemas import UserPublic, normalize_email
from app.auth.security import (
    generate_session_token,
    hash_password,
    hash_session_token,
    verify_password,
)
from app.core.config import get_settings
from app.core.errors import (
    EmailAlreadyRegisteredError,
    InvalidCredentialsError,
    NotAuthenticatedError,
)


def _to_user_public(row: dict[str, object]) -> UserPublic:
    return UserPublic(
        id=row["id"],  # type: ignore[arg-type]
        name=row["name"],  # type: ignore[arg-type]
        email=row["email"],  # type: ignore[arg-type]
    )


async def register(pool: asyncpg.Pool, *, name: str, email: str, password: str) -> UserPublic:
    """Create the account. No email verification: the account is usable right away."""
    email_normalized = normalize_email(email)
    password_hash = hash_password(password)

    async with pool.acquire() as conn:
        try:
            user = await repository.create_user(
                conn,
                name=name,
                email=email,
                email_normalized=email_normalized,
                password_hash=password_hash,
            )
        except asyncpg.UniqueViolationError as exc:
            raise EmailAlreadyRegisteredError() from exc

    return _to_user_public(user)


async def login(pool: asyncpg.Pool, *, email: str, password: str) -> UserPublic:
    email_normalized = normalize_email(email)

    async with pool.acquire() as conn:
        user = await repository.get_user_by_email(conn, email_normalized=email_normalized)
        if user is None or not verify_password(password, user["password_hash"]):
            raise InvalidCredentialsError()

        return _to_user_public(user)


async def create_session(pool: asyncpg.Pool, *, user_id: int) -> tuple[str, dt.datetime]:
    """Issue a new session token and return it (plaintext) with its expiry."""
    settings = get_settings()
    token = generate_session_token()
    expires_at = dt.datetime.now(dt.UTC) + dt.timedelta(days=settings.auth_session_ttl_days)

    async with pool.acquire() as conn:
        await repository.create_session(
            conn, user_id=user_id, token_hash=hash_session_token(token), expires_at=expires_at
        )

    return token, expires_at


async def get_current_user(pool: asyncpg.Pool, *, session_token: str | None) -> UserPublic:
    if not session_token:
        raise NotAuthenticatedError()

    async with pool.acquire() as conn:
        row = await repository.get_session_user(conn, token_hash=hash_session_token(session_token))

    if row is None:
        raise NotAuthenticatedError()

    return _to_user_public(row)


async def logout(pool: asyncpg.Pool, *, session_token: str | None) -> None:
    if not session_token:
        return

    async with pool.acquire() as conn:
        await repository.revoke_session(conn, token_hash=hash_session_token(session_token))
