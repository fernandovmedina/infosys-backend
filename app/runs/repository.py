"""Database access for investigation runs."""

from __future__ import annotations

import json
from typing import Any

import asyncpg

_RUN_COLUMNS = """
    id, user_id, status, filename, format, sha256, validation, error,
    created_at, started_at, finished_at
"""


def _to_dict(row: asyncpg.Record) -> dict[str, Any]:
    run = dict(row)
    for key in ("validation", "error"):
        if isinstance(run[key], str):
            run[key] = json.loads(run[key])
    return run


async def create_run(
    conn: asyncpg.Connection,
    *,
    run_id: str,
    user_id: int,
    status: str,
    filename: str,
    format: str,
    sha256: str,
    validation: dict[str, Any],
) -> dict[str, Any]:
    row = await conn.fetchrow(
        f"""
        INSERT INTO investigation_run (id, user_id, status, filename, format, sha256, validation)
        VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb)
        RETURNING {_RUN_COLUMNS}
        """,
        run_id,
        user_id,
        status,
        filename,
        format,
        sha256,
        json.dumps(validation),
    )
    assert row is not None
    return _to_dict(row)


async def get_run(conn: asyncpg.Connection, *, run_id: str, user_id: int) -> dict[str, Any] | None:
    """The run, only if it belongs to `user_id`."""
    row = await conn.fetchrow(
        f"SELECT {_RUN_COLUMNS} FROM investigation_run WHERE id = $1 AND user_id = $2",
        run_id,
        user_id,
    )
    return _to_dict(row) if row else None


async def list_runs(conn: asyncpg.Connection, *, user_id: int, limit: int) -> list[dict[str, Any]]:
    rows = await conn.fetch(
        f"""
        SELECT {_RUN_COLUMNS}
        FROM investigation_run
        WHERE user_id = $1
        ORDER BY created_at DESC
        LIMIT $2
        """,
        user_id,
        limit,
    )
    return [_to_dict(row) for row in rows]


async def delete_run(conn: asyncpg.Connection, *, run_id: str, user_id: int) -> bool:
    """Delete the run if it belongs to `user_id` and is not running. True if a row was deleted."""
    deleted = await conn.fetchval(
        """
        DELETE FROM investigation_run
        WHERE id = $1 AND user_id = $2 AND status <> 'running'
        RETURNING id
        """,
        run_id,
        user_id,
    )
    return deleted is not None


async def delete_runs(conn: asyncpg.Connection, *, user_id: int) -> list[str]:
    """Delete every run of `user_id` except running ones; returns the deleted ids."""
    rows = await conn.fetch(
        """
        DELETE FROM investigation_run
        WHERE user_id = $1 AND status <> 'running'
        RETURNING id
        """,
        user_id,
    )
    return [row["id"] for row in rows]
