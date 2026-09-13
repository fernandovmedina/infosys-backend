"""Database access for investigation runs."""

from __future__ import annotations

import json
from typing import Any

import asyncpg

_RUN_COLUMNS = """
    id, user_id, status, filename, format, sha256, validation, error,
    created_at, started_at, finished_at, company_rfc, company_name
"""


def _qualified(alias: str) -> str:
    return ", ".join(f"{alias}.{column.strip()}" for column in _RUN_COLUMNS.split(","))


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


async def get_run_by_id(conn: asyncpg.Connection, *, run_id: str) -> dict[str, Any] | None:
    """The run regardless of owner, for background work that already checked ownership."""
    row = await conn.fetchrow(f"SELECT {_RUN_COLUMNS} FROM investigation_run WHERE id = $1", run_id)
    return _to_dict(row) if row else None


async def list_runs(conn: asyncpg.Connection, *, user_id: int, limit: int) -> list[dict[str, Any]]:
    """The user's runs, newest first, with the headline numbers of completed ones."""
    rows = await conn.fetch(
        f"""
        SELECT {_qualified("r")},
               a.findings_count, a.total_exposure, a.submission
        FROM investigation_run r
        LEFT JOIN fraud_analysis a ON a.run_id = r.id AND r.status = 'completed'
        WHERE r.user_id = $1
        ORDER BY r.created_at DESC
        LIMIT $2
        """,
        user_id,
        limit,
    )
    runs = []
    for row in rows:
        run = _to_dict(row)
        if isinstance(run["submission"], str):
            run["submission"] = json.loads(run["submission"])
        runs.append(run)
    return runs


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


async def mark_running(
    conn: asyncpg.Connection, *, run_id: str, user_id: int
) -> dict[str, Any] | None:
    """Move a ready or failed run to `running`. None if it was not in one of those states."""
    row = await conn.fetchrow(
        f"""
        UPDATE investigation_run
        SET status = 'running', started_at = now(), finished_at = NULL, error = NULL
        WHERE id = $1 AND user_id = $2 AND status IN ('ready', 'failed')
        RETURNING {_RUN_COLUMNS}
        """,
        run_id,
        user_id,
    )
    if row is None:
        return None
    # A retry starts a new log.
    await conn.execute("DELETE FROM run_event WHERE run_id = $1", run_id)
    return _to_dict(row)


async def mark_finished(
    conn: asyncpg.Connection, *, run_id: str, status: str, error: dict[str, Any] | None = None
) -> None:
    """Close a running run as `completed` or `failed` (with its ApiErrorBody)."""
    await conn.execute(
        """
        UPDATE investigation_run
        SET status = $2, finished_at = now(), error = $3::jsonb
        WHERE id = $1 AND status = 'running'
        """,
        run_id,
        status,
        None if error is None else json.dumps(error, ensure_ascii=False),
    )


# ---------------------------------------------------------------------------
# Investigation log
# ---------------------------------------------------------------------------

_EVENT_COLUMNS = "seq, ts, type, role, payload"


def _event_to_dict(row: asyncpg.Record) -> dict[str, Any]:
    event = dict(row)
    payload = event.pop("payload")
    return {**(json.loads(payload) if isinstance(payload, str) else payload), **event}


async def insert_events(
    conn: asyncpg.Connection, *, run_id: str, events: list[tuple[str, str, dict[str, Any]]]
) -> None:
    """Append `(type, role, payload)` events after the run's last `seq`.

    Serialized per run by locking its row, so concurrent writers never reuse a `seq`.
    """
    if not events:
        return
    async with conn.transaction():
        await conn.execute("SELECT 1 FROM investigation_run WHERE id = $1 FOR UPDATE", run_id)
        last = await conn.fetchval(
            "SELECT COALESCE(MAX(seq), 0) FROM run_event WHERE run_id = $1", run_id
        )
        await conn.executemany(
            """
            INSERT INTO run_event (run_id, seq, type, role, payload)
            VALUES ($1, $2, $3, $4, $5::jsonb)
            """,
            [
                (run_id, last + offset, type_, role, json.dumps(payload, ensure_ascii=False))
                for offset, (type_, role, payload) in enumerate(events, start=1)
            ],
        )


async def list_events(
    conn: asyncpg.Connection,
    *,
    run_id: str,
    after_seq: int = 0,
    role: str | None = None,
    entity: str | None = None,
) -> list[dict[str, Any]]:
    """The run's events after `after_seq`, oldest first; optionally one role or one entity."""
    rows = await conn.fetch(
        f"""
        SELECT {_EVENT_COLUMNS}
        FROM run_event
        WHERE run_id = $1
          AND seq > $2
          AND ($3::text IS NULL OR role = $3)
          AND ($4::text IS NULL
               OR payload->>'entity' = $4
               OR COALESCE(payload->'entities', '[]'::jsonb) ? $4)
        ORDER BY seq
        """,
        run_id,
        after_seq,
        role,
        entity,
    )
    return [_event_to_dict(row) for row in rows]


async def last_event_seq(conn: asyncpg.Connection, *, run_id: str) -> int:
    value = await conn.fetchval(
        "SELECT COALESCE(MAX(seq), 0) FROM run_event WHERE run_id = $1", run_id
    )
    return int(value)


async def set_company(
    conn: asyncpg.Connection, *, run_id: str, rfc: str | None, name: str | None
) -> None:
    await conn.execute(
        "UPDATE investigation_run SET company_rfc = $2, company_name = $3 WHERE id = $1",
        run_id,
        rfc,
        name,
    )


async def get_run_status(conn: asyncpg.Connection, *, run_id: str) -> str | None:
    status: str | None = await conn.fetchval(
        "SELECT status FROM investigation_run WHERE id = $1", run_id
    )
    return status
