"""Business logic for registration, sign-in, and sessions.

Passwords never leave this module unhashed; the repository only ever sees the
PBKDF2 hash.
"""

from __future__ import annotations

import datetime as dt

import asyncpg

from app.auth import repository
from app.auth.entities import IssuedSession, User
from app.auth.security import (
    generate_session_token,
    hash_password,
    hash_session_token,
    verify_password,
)
from app.core.errors import (
    EmailAlreadyRegisteredError,
    InvalidCredentialsError,
    NotAuthenticatedError,
)


def _normalize_email(email: str) -> str:
    """Case-fold and trim an email so lookups do not depend on its presentation."""
    return email.strip().lower()


async def register(pool: asyncpg.Pool, *, name: str, email: str, password: str) -> User:
    """Create the account. No email verification: the account is usable right away."""
    email_normalized = _normalize_email(email)
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

    return user


async def login(pool: asyncpg.Pool, *, email: str, password: str) -> User:
    email_normalized = _normalize_email(email)

    async with pool.acquire() as conn:
        user = await repository.get_user_by_email(conn, email_normalized=email_normalized)
        if user is None or not verify_password(password, user.password_hash):
            raise InvalidCredentialsError()

        return User(id=user.id, name=user.name, email=user.email)


async def create_session(
    pool: asyncpg.Pool, *, user_id: int, ttl: dt.timedelta
) -> IssuedSession:
    """Issue a new session token with an explicitly supplied lifetime."""
    token = generate_session_token()
    expires_at = dt.datetime.now(dt.UTC) + ttl

    async with pool.acquire() as conn:
        await repository.create_session(
            conn, user_id=user_id, token_hash=hash_session_token(token), expires_at=expires_at
        )

    return IssuedSession(token=token, expires_at=expires_at)


async def get_current_user(pool: asyncpg.Pool, *, session_token: str | None) -> User:
    if not session_token:
        raise NotAuthenticatedError()

    async with pool.acquire() as conn:
        row = await repository.get_session_user(conn, token_hash=hash_session_token(session_token))

    if row is None:
        raise NotAuthenticatedError()

    return row


async def logout(pool: asyncpg.Pool, *, session_token: str | None) -> None:
    if not session_token:
        return

    async with pool.acquire() as conn:
        await repository.revoke_session(conn, token_hash=hash_session_token(session_token))
