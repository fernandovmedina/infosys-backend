"""Database access for accounts and sessions."""

from __future__ import annotations

import datetime as dt

import asyncpg

from app.auth.entities import User, UserWithPassword


def _to_user(row: asyncpg.Record) -> User:
    """Map a database record to the domain object exposed by this repository."""
    return User(id=row["id"], name=row["name"], email=row["email"])


def _to_user_with_password(row: asyncpg.Record) -> UserWithPassword:
    """Map the credential-bearing projection used only during login."""
    return UserWithPassword(
        id=row["id"],
        name=row["name"],
        email=row["email"],
        password_hash=row["password_hash"],
    )


async def create_user(
    conn: asyncpg.Connection, *, name: str, email: str, email_normalized: str, password_hash: str
) -> User:
    """Insert a new account. Raises `asyncpg.UniqueViolationError` on a duplicate email."""
    row = await conn.fetchrow(
        """
        INSERT INTO app_user (name, email, email_normalized, password_hash)
        VALUES ($1, $2, $3, $4)
        RETURNING id, name, email
        """,
        name,
        email,
        email_normalized,
        password_hash,
    )
    if row is None:  # pragma: no cover - INSERT ... RETURNING always yields one row
        raise RuntimeError("User insert completed without returning the created user.")
    return _to_user(row)


async def get_user_by_email(
    conn: asyncpg.Connection, *, email_normalized: str
) -> UserWithPassword | None:
    row = await conn.fetchrow(
        """
        SELECT id, name, email, password_hash
        FROM app_user
        WHERE email_normalized = $1
        """,
        email_normalized,
    )
    return _to_user_with_password(row) if row else None


async def create_session(
    conn: asyncpg.Connection,
    *,
    user_id: int,
    token_hash: str,
    expires_at: dt.datetime,
) -> None:
    await conn.execute(
        """
        INSERT INTO auth_session (user_id, token_hash, expires_at)
        VALUES ($1, $2, $3)
        """,
        user_id,
        token_hash,
        expires_at,
    )


async def get_session_user(conn: asyncpg.Connection, *, token_hash: str) -> User | None:
    """The user a live, unexpired, unrevoked session token belongs to."""
    row = await conn.fetchrow(
        """
        SELECT u.id, u.name, u.email
        FROM auth_session s
        JOIN app_user u ON u.id = s.user_id
        WHERE s.token_hash = $1
          AND s.revoked_at IS NULL
          AND s.expires_at > now()
        """,
        token_hash,
    )
    return _to_user(row) if row else None


async def revoke_session(conn: asyncpg.Connection, *, token_hash: str) -> None:
    await conn.execute(
        "UPDATE auth_session SET revoked_at = now() WHERE token_hash = $1 AND revoked_at IS NULL",
        token_hash,
    )
