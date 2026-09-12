"""Guards that the search stays index-backed as the dataset and query evolve.

These assert on the query plan rather than on wall-clock time, so they are
stable on slow or loaded machines.
"""

from __future__ import annotations

import asyncpg

from app.sat.repository import SEARCH_SQL
from tests.conftest import requires_database

pytestmark = requires_database


async def _plan(
    pool: asyncpg.Pool,
    rfcs: list[str],
    names: list[str] | None = None,
    cores: list[str] | None = None,
) -> str:
    size = len(rfcs)
    rows = await pool.fetch(
        "EXPLAIN (ANALYZE, FORMAT TEXT) " + SEARCH_SQL,
        list(range(size)),
        rfcs,
        names if names is not None else [""] * size,
        cores if cores is not None else [""] * size,
    )
    return "\n".join(row[0] for row in rows)


async def test_rfc_search_uses_the_rfc_index(pool: asyncpg.Pool) -> None:
    rows = await pool.fetch(
        "SELECT rfc_normalized FROM sat_blacklist_record WHERE NOT is_redacted LIMIT 100"
    )
    plan = await _plan(pool, [row["rfc_normalized"] for row in rows])

    assert "sat_blacklist_record_rfc_normalized_idx" in plan
    assert "Seq Scan on sat_blacklist_record" not in plan


async def test_name_search_uses_the_name_indexes(pool: asyncpg.Pool) -> None:
    rows = await pool.fetch(
        "SELECT name_normalized, name_core FROM sat_blacklist_record "
        "WHERE NOT is_redacted LIMIT 100"
    )
    plan = await _plan(
        pool,
        [""] * len(rows),
        [row["name_normalized"] for row in rows],
        [row["name_core"] for row in rows],
    )

    assert "sat_blacklist_record_name_normalized_idx" in plan
    assert "sat_blacklist_record_name_core_idx" in plan
    assert "Seq Scan on sat_blacklist_record" not in plan


async def test_fuzzy_search_uses_the_trigram_index(pool: asyncpg.Pool) -> None:
    """Truncated names miss both exact stages and fall through to pg_trgm."""
    rows = await pool.fetch(
        "SELECT name_core FROM sat_blacklist_record "
        "WHERE NOT is_redacted AND length(name_core) > 20 LIMIT 25"
    )
    truncated = [row["name_core"][:-3] for row in rows]
    plan = await _plan(pool, [""] * len(rows), [""] * len(rows), truncated)

    assert "sat_blacklist_record_name_core_trgm_idx" in plan
    assert "Seq Scan on sat_blacklist_record" not in plan


async def test_batch_size_does_not_change_the_query_count(pool: asyncpg.Pool) -> None:
    """One query serves the whole batch: N companies must not mean N queries."""
    from app.sat.repository import search_blacklist

    class CountingPool:
        """Delegates to the real pool while counting fetches.

        asyncpg's Pool uses __slots__, so it cannot be monkeypatched in place.
        """

        def __init__(self, inner: asyncpg.Pool) -> None:
            self.inner = inner
            self.calls = 0

        async def fetch(self, *args: object, **kwargs: object) -> object:
            self.calls += 1
            return await self.inner.fetch(*args, **kwargs)

    rows = await pool.fetch(
        "SELECT rfc_normalized FROM sat_blacklist_record WHERE NOT is_redacted LIMIT 250"
    )
    rfcs = [row["rfc_normalized"] for row in rows]
    counting = CountingPool(pool)

    results = await search_blacklist(
        counting,
        list(range(len(rfcs))),
        rfcs,
        [""] * len(rfcs),
        [""] * len(rfcs),
    )

    assert counting.calls == 1
    assert len(results) >= len(rfcs)


async def test_redacted_rows_are_excluded_from_every_index(pool: asyncpg.Pool) -> None:
    """The partial indexes must not contain the suppressed rows at all."""
    indexed = await pool.fetchval(
        """
        SELECT count(*) FROM sat_blacklist_record
        WHERE is_redacted AND rfc_normalized = 'XXXXXXXXXXXX'
        """
    )
    assert indexed > 0, "expected redacted rows to be present in the table"

    from app.sat.repository import search_blacklist

    results = await search_blacklist(pool, [0], ["XXXXXXXXXXXX"], [""], [""])
    assert results == []
