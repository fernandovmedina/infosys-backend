"""Database access for the SAT blacklist.

The whole batch is resolved in **one** query. Inputs are handed to Postgres as
parallel arrays and expanded with ``unnest``, so checking 1 company and checking
500 costs one round trip either way -- there is no per-company query.

Search strategy (documented in README.md):

1. ``rfc``        -- equality on the indexed ``rfc_normalized`` column.
2. ``name_exact`` -- equality on ``name_normalized`` or on ``name_core`` (the
   name with its corporate suffix removed).
3. ``name_fuzzy`` -- pg_trgm similarity against ``name_core``, using the GIN
   trigram index, only for inputs that matched nothing above.

Each stage only considers inputs that earlier stages left unresolved, and every
index is partial on ``NOT is_redacted`` so suppressed rows are never scanned.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

import asyncpg

from app.core.errors import DatabaseUnavailableError

logger = logging.getLogger(__name__)

# Maximum rows returned per requested company. An RFC may hold several
# procedures; this caps the response so one input cannot dominate the payload.
MAX_MATCHES_PER_COMPANY = 20

# Candidates considered per input on the fuzzy path before ranking.
FUZZY_CANDIDATE_LIMIT = 5

RECORD_COLUMNS = """
    r.id, r.rfc, r.name, r.situacion, r.is_cleared,
    r.presuncion_sat_oficio,  r.presuncion_sat_publicacion,
    r.presuncion_dof_oficio,  r.presuncion_dof_publicacion,
    r.desvirtuado_sat_oficio, r.desvirtuado_sat_publicacion,
    r.desvirtuado_dof_oficio, r.desvirtuado_dof_publicacion,
    r.definitivo_sat_oficio,  r.definitivo_sat_publicacion,
    r.definitivo_dof_oficio,  r.definitivo_dof_publicacion,
    r.sentencia_sat_oficio,   r.sentencia_sat_publicacion,
    r.sentencia_dof_oficio,   r.sentencia_dof_publicacion
"""

SEARCH_SQL = f"""
WITH input AS (
    SELECT *
    FROM unnest($1::int[], $2::text[], $3::text[], $4::text[])
        AS t(idx, rfc_n, name_n, name_c)
),

-- Stage 1: exact RFC. Index scan on sat_blacklist_record_rfc_normalized_idx.
rfc_matches AS (
    SELECT i.idx, 'rfc'::text AS match_type, NULL::real AS similarity, {RECORD_COLUMNS}
    FROM input i
    JOIN sat_blacklist_record r ON r.rfc_normalized = i.rfc_n
    WHERE i.rfc_n <> '' AND NOT r.is_redacted
),
resolved_by_rfc AS (
    SELECT DISTINCT idx FROM rfc_matches
),

-- Stage 2a: exact match on the full normalized name.
name_full_matches AS (
    SELECT i.idx, 'name_exact'::text AS match_type, NULL::real AS similarity,
           {RECORD_COLUMNS}
    FROM input i
    JOIN sat_blacklist_record r ON r.name_normalized = i.name_n
    WHERE i.name_n <> ''
      AND NOT r.is_redacted
      AND i.idx NOT IN (SELECT idx FROM resolved_by_rfc)
),

-- Stage 2b: exact match ignoring the corporate suffix, so that
-- "GRUPO X" finds "GRUPO X, S.A. DE C.V.".
name_core_matches AS (
    SELECT i.idx, 'name_exact'::text AS match_type, NULL::real AS similarity,
           {RECORD_COLUMNS}
    FROM input i
    JOIN sat_blacklist_record r ON r.name_core = i.name_c
    WHERE i.name_c <> ''
      AND NOT r.is_redacted
      AND i.idx NOT IN (SELECT idx FROM resolved_by_rfc)
),
name_matches AS (
    SELECT * FROM name_full_matches
    UNION
    SELECT * FROM name_core_matches
),
resolved_by_name AS (
    SELECT DISTINCT idx FROM name_matches
),

-- Stage 3: trigram similarity, only for inputs still unmatched. The `%`
-- operator is index-backed by sat_blacklist_record_name_core_trgm_idx; the
-- threshold comes from pg_trgm.similarity_threshold, set per connection.
fuzzy_matches AS (
    SELECT i.idx, 'name_fuzzy'::text AS match_type, c.similarity, {RECORD_COLUMNS}
    FROM input i
    JOIN LATERAL (
        SELECT r2.id, similarity(r2.name_core, i.name_c) AS similarity
        FROM sat_blacklist_record r2
        WHERE r2.name_core % i.name_c
          AND NOT r2.is_redacted
        ORDER BY r2.name_core <-> i.name_c
        LIMIT {FUZZY_CANDIDATE_LIMIT}
    ) c ON TRUE
    JOIN sat_blacklist_record r ON r.id = c.id
    WHERE i.name_c <> ''
      AND i.idx NOT IN (SELECT idx FROM resolved_by_rfc)
      AND i.idx NOT IN (SELECT idx FROM resolved_by_name)
),

combined AS (
    SELECT * FROM rfc_matches
    UNION ALL
    SELECT * FROM name_matches
    UNION ALL
    SELECT * FROM fuzzy_matches
),

ranked AS (
    SELECT c.*,
           row_number() OVER (
               PARTITION BY c.idx
               ORDER BY
                   CASE c.situacion
                       WHEN 'Definitivo'          THEN 0
                       WHEN 'Presunto'            THEN 1
                       WHEN 'Desvirtuado'         THEN 2
                       WHEN 'Sentencia Favorable' THEN 3
                       ELSE 4
                   END,
                   c.similarity DESC NULLS LAST,
                   c.id
           ) AS rank
    FROM combined c
)

SELECT * FROM ranked
WHERE rank <= {MAX_MATCHES_PER_COMPANY}
ORDER BY idx, rank
"""


async def search_blacklist(
    pool: asyncpg.Pool,
    indexes: Sequence[int],
    rfcs: Sequence[str],
    names: Sequence[str],
    name_cores: Sequence[str],
) -> list[dict[str, Any]]:
    """Resolve a whole batch of companies in a single query.

    The four sequences are parallel arrays: position *i* of each describes the
    same requested company. Empty strings mean "not provided" and cause that
    stage to be skipped for the input.

    Returns raw match rows ordered by input index then rank; assembling them into
    per-company results is the service layer's job.
    """
    if not indexes:
        return []

    try:
        rows = await pool.fetch(
            SEARCH_SQL, list(indexes), list(rfcs), list(names), list(name_cores)
        )
    except asyncpg.PostgresError as exc:
        logger.exception("Blacklist search query failed")
        raise DatabaseUnavailableError("The blacklist search could not be completed.") from exc
    except (OSError, asyncpg.InterfaceError) as exc:
        logger.exception("Lost connection to the database during blacklist search")
        raise DatabaseUnavailableError() from exc

    return [dict(row) for row in rows]
