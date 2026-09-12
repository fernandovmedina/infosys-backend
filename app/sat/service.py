"""Business logic for the SAT blacklist check.

Turns a batch of requested companies into one result each, preserving request
order. Duplicate companies in the same request are collapsed before the query
runs and expanded again afterwards, so repeating a company costs nothing extra
in the database but still produces its own entry in the response.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from typing import Any

import asyncpg

from app.sat.normalization import name_core, normalize_name, normalize_rfc
from app.sat.repository import search_blacklist
from app.sat.schemas import BlacklistRecord, CompanyQuery, CompanyResult, MatchType

# Ordered most to least severe; mirrors the ranking applied in the SQL.
SITUACION_SEVERITY: dict[str, int] = {
    "Definitivo": 0,
    "Presunto": 1,
    "Desvirtuado": 2,
    "Sentencia Favorable": 3,
}

_RECORD_FIELDS = tuple(BlacklistRecord.model_fields)


def _normalize_query(company: CompanyQuery) -> tuple[str, str, str]:
    """Reduce a requested company to the three keys the search matches on."""
    rfc = normalize_rfc(company.rfc)
    name = normalize_name(company.name)
    return rfc, name, name_core(company.name)


def _to_record(row: dict[str, Any]) -> BlacklistRecord:
    return BlacklistRecord(**{field: row[field] for field in _RECORD_FIELDS})


def _resolve_match_type(
    raw_match_type: str, normalized_name: str, core: str, row: dict[str, Any]
) -> MatchType:
    """Promote an RFC match to 'rfc_and_name' when the supplied name agrees.

    Distinguishes "we found this RFC" from the stronger "RFC and company name
    both point at the same record", which is what a caller supplying both
    fields actually wants to know.
    """
    if raw_match_type != "rfc" or not normalized_name:
        return raw_match_type  # type: ignore[return-value]
    if normalize_name(row["name"]) == normalized_name or name_core(row["name"]) == core:
        return "rfc_and_name"
    return "rfc"


def _build_result(
    company: CompanyQuery,
    normalized_name: str,
    core: str,
    rows: Sequence[dict[str, Any]],
) -> CompanyResult:
    """Assemble the response entry for one company from its matching rows."""
    if not rows:
        return CompanyResult(query=company, blacklisted=False, match_count=0)

    # Rows arrive pre-ranked by the query: most severe first.
    primary = rows[0]
    records = [_to_record(row) for row in rows]

    return CompanyResult(
        query=company,
        blacklisted=True,
        match_type=_resolve_match_type(primary["match_type"], normalized_name, core, primary),
        similarity=(
            round(float(primary["similarity"]), 4) if primary["similarity"] is not None else None
        ),
        effective_situacion=primary["situacion"],
        cleared=all(record.is_cleared for record in records),
        match=records[0],
        matches=records,
        match_count=len(records),
    )


async def check_companies(
    pool: asyncpg.Pool, companies: Sequence[CompanyQuery]
) -> list[CompanyResult]:
    """Check every requested company against the blacklist in one query."""
    if not companies:
        return []

    normalized = [_normalize_query(company) for company in companies]

    # Collapse duplicates: identical normalized keys share one search slot.
    slot_of_key: dict[tuple[str, str, str], int] = {}
    slot_of_company: list[int] = []
    for keys in normalized:
        slot = slot_of_key.setdefault(keys, len(slot_of_key))
        slot_of_company.append(slot)

    indexes = list(range(len(slot_of_key)))
    rfcs, names, cores = (list(values) for values in zip(*slot_of_key, strict=True))

    rows = await search_blacklist(pool, indexes, rfcs, names, cores)

    rows_by_slot: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        rows_by_slot[row["idx"]].append(row)

    return [
        _build_result(
            company,
            normalized[position][1],
            normalized[position][2],
            rows_by_slot.get(slot_of_company[position], []),
        )
        for position, company in enumerate(companies)
    ]
