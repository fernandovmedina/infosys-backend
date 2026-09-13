"""End-to-end tests for POST /api/v1/sat/blacklist/check.

Fixtures are real records taken from `black_list.csv`.
"""

from __future__ import annotations

from typing import Any

import asyncpg
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.dependencies import get_pool
from app.core.errors import DatabaseUnavailableError
from app.main import create_app
from tests.conftest import requires_database

ENDPOINT = "/api/v1/sat/blacklist/check"

# --- Real rows from black_list.csv -------------------------------------------
# RFC 'AAA080808HL8' -> "ASESORES EN AVALÚOS Y ACTIVOS, S.A. DE C.V." (Sentencia Favorable)
KNOWN_RFC = "AAA080808HL8"
KNOWN_NAME = "ASESORES EN AVALÚOS Y ACTIVOS, S.A. DE C.V."
# RFC 'AAA100303L51' -> "INGENIOS SANTOS, S.A. DE C.V." (Desvirtuado)
KNOWN_RFC_2 = "AAA100303L51"
KNOWN_NAME_2 = "INGENIOS SANTOS, S.A. DE C.V."
# RFC 'CACL7806172Y1' -> "CARMONA CÁRDENAS LINO", two procedures (Presunto + Definitivo)
MULTI_PROCEDURE_RFC = "CACL7806172Y1"
# An accented individual: "ZUÑIGA RAMIREZ CAROLINA" (Definitivo)
ACCENTED_NAME = "ZUÑIGA RAMIREZ CAROLINA"

# Structurally valid but absent from the listing (SAT's generic foreign-entity RFC).
ABSENT_RFC = "XAXX010101000"


async def _check(client: AsyncClient, companies: list[dict[str, Any]]) -> Any:
    return await client.post(ENDPOINT, json={"companies": companies})


pytestmark = requires_database


# --- 1. Existing RFC ----------------------------------------------------------
async def test_existing_rfc_is_blacklisted(client: AsyncClient) -> None:
    response = await _check(client, [{"rfc": KNOWN_RFC}])
    assert response.status_code == 200

    (result,) = response.json()["results"]
    assert result["blacklisted"] is True
    assert result["match_type"] == "rfc"
    assert result["match"]["rfc"] == KNOWN_RFC
    assert result["match"]["name"] == KNOWN_NAME
    assert result["match"]["situacion"] == "Sentencia Favorable"


async def test_rfc_match_is_case_and_punctuation_insensitive(client: AsyncClient) -> None:
    response = await _check(client, [{"rfc": "aaa-080808-hl8"}])
    (result,) = response.json()["results"]
    assert result["blacklisted"] is True
    assert result["match"]["rfc"] == KNOWN_RFC


async def test_response_preserves_source_fields(client: AsyncClient) -> None:
    """Useful SAT columns must survive into the response, not just rfc/name."""
    response = await _check(client, [{"rfc": KNOWN_RFC}])
    match = response.json()["results"][0]["match"]
    assert match["presuncion_sat_oficio"] == "500-05-2018-16632 de fecha 01 de junio de 2018"
    assert match["presuncion_sat_publicacion"] == "2018-06-01"
    assert match["sentencia_dof_publicacion"] == "2019-04-16"


# --- 2. Non-existing RFC ------------------------------------------------------
async def test_absent_rfc_is_not_blacklisted(client: AsyncClient) -> None:
    response = await _check(client, [{"rfc": ABSENT_RFC}])
    assert response.status_code == 200

    (result,) = response.json()["results"]
    assert result["blacklisted"] is False
    assert result["match_type"] is None
    assert result["match"] is None
    assert result["matches"] == []
    assert result["match_count"] == 0


# --- 3/4/5. Company-name matching --------------------------------------------
async def test_exact_company_name(client: AsyncClient) -> None:
    response = await _check(client, [{"name": KNOWN_NAME_2}])
    (result,) = response.json()["results"]
    assert result["blacklisted"] is True
    assert result["match_type"] == "name_exact"
    assert result["match"]["rfc"] == KNOWN_RFC_2


async def test_company_name_with_different_capitalization(client: AsyncClient) -> None:
    response = await _check(client, [{"name": "ingenios santos, s.a. de c.v."}])
    (result,) = response.json()["results"]
    assert result["blacklisted"] is True
    assert result["match"]["rfc"] == KNOWN_RFC_2


async def test_company_name_without_accents_still_matches(client: AsyncClient) -> None:
    """'ZUNIGA' must find 'ZUÑIGA'."""
    response = await _check(client, [{"name": "zuniga ramirez carolina"}])
    (result,) = response.json()["results"]
    assert result["blacklisted"] is True
    assert result["match"]["name"] == ACCENTED_NAME


async def test_company_name_with_extra_whitespace_and_punctuation(client: AsyncClient) -> None:
    response = await _check(client, [{"name": "  INGENIOS   SANTOS   S A   DE  C V  "}])
    (result,) = response.json()["results"]
    assert result["blacklisted"] is True
    assert result["match"]["rfc"] == KNOWN_RFC_2


async def test_company_name_without_corporate_suffix_matches(client: AsyncClient) -> None:
    """'INGENIOS SANTOS' must find 'INGENIOS SANTOS, S.A. DE C.V.'."""
    response = await _check(client, [{"name": "INGENIOS SANTOS"}])
    (result,) = response.json()["results"]
    assert result["blacklisted"] is True
    assert result["match_type"] == "name_exact"


async def test_misspelled_company_name_matches_fuzzily(client: AsyncClient) -> None:
    response = await _check(client, [{"name": "INGENIOS SANTO"}])
    (result,) = response.json()["results"]
    assert result["blacklisted"] is True
    assert result["match_type"] == "name_fuzzy"
    assert result["similarity"] is not None and 0 < result["similarity"] <= 1


async def test_unrelated_name_is_not_blacklisted(client: AsyncClient) -> None:
    response = await _check(client, [{"name": "EMPRESA COMPLETAMENTE LIMPIA E INEXISTENTE"}])
    (result,) = response.json()["results"]
    assert result["blacklisted"] is False
    assert result["match_type"] is None


# --- 6/7. Batches and mixed identifiers --------------------------------------
async def test_multiple_companies_in_one_request(client: AsyncClient) -> None:
    companies = [
        {"rfc": KNOWN_RFC},
        {"rfc": ABSENT_RFC},
        {"name": KNOWN_NAME_2},
        {"name": "EMPRESA COMPLETAMENTE LIMPIA E INEXISTENTE"},
    ]
    response = await _check(client, companies)
    results = response.json()["results"]

    assert len(results) == len(companies)
    assert [r["blacklisted"] for r in results] == [True, False, True, False]
    # Results must come back in request order.
    assert [r["query"] for r in results] == [
        {"rfc": KNOWN_RFC, "name": None},
        {"rfc": ABSENT_RFC, "name": None},
        {"rfc": None, "name": KNOWN_NAME_2},
        {"rfc": None, "name": "EMPRESA COMPLETAMENTE LIMPIA E INEXISTENTE"},
    ]


async def test_mixed_rfc_and_name_agreeing(client: AsyncClient) -> None:
    response = await _check(client, [{"rfc": KNOWN_RFC, "name": KNOWN_NAME}])
    (result,) = response.json()["results"]
    assert result["blacklisted"] is True
    assert result["match_type"] == "rfc_and_name"


async def test_mixed_rfc_and_name_disagreeing_reports_plain_rfc_match(
    client: AsyncClient,
) -> None:
    """RFC wins, but the weaker match_type signals the name did not corroborate."""
    response = await _check(
        client, [{"rfc": KNOWN_RFC, "name": "UNA RAZON SOCIAL COMPLETAMENTE DISTINTA"}]
    )
    (result,) = response.json()["results"]
    assert result["blacklisted"] is True
    assert result["match_type"] == "rfc"


# --- Multiple procedures under one RFC ---------------------------------------
async def test_rfc_with_several_procedures_returns_all_ranked_by_severity(
    client: AsyncClient,
) -> None:
    response = await _check(client, [{"rfc": MULTI_PROCEDURE_RFC}])
    (result,) = response.json()["results"]

    assert result["match_count"] >= 2
    assert len(result["matches"]) == result["match_count"]
    # The most severe status represents the taxpayer.
    assert result["effective_situacion"] == "Definitivo"
    assert result["match"]["situacion"] == "Definitivo"
    assert {m["situacion"] for m in result["matches"]} >= {"Presunto", "Definitivo"}


async def test_cleared_flag_marks_rebutted_taxpayers(client: AsyncClient) -> None:
    """'Sentencia Favorable' means the taxpayer rebutted the presumption."""
    response = await _check(client, [{"rfc": KNOWN_RFC}])
    (result,) = response.json()["results"]
    assert result["blacklisted"] is True
    assert result["cleared"] is True
    assert result["effective_situacion"] == "Sentencia Favorable"


# --- Redacted rows ------------------------------------------------------------
async def test_redacted_placeholder_name_never_matches(client: AsyncClient) -> None:
    """The 238 suppressed rows must not be reachable by searching their placeholder."""
    response = await _check(client, [{"name": "Información suprimida"}])
    (result,) = response.json()["results"]
    assert result["blacklisted"] is False


# --- 8. Duplicate input -------------------------------------------------------
async def test_duplicate_companies_each_get_their_own_result(client: AsyncClient) -> None:
    companies = [{"rfc": KNOWN_RFC}, {"rfc": KNOWN_RFC}, {"rfc": "aaa-080808-hl8"}]
    response = await _check(client, companies)
    results = response.json()["results"]

    assert len(results) == 3
    assert all(r["blacklisted"] for r in results)
    assert len({r["match"]["id"] for r in results}) == 1  # same underlying record


# --- 9. Empty input -----------------------------------------------------------
async def test_empty_companies_list_is_rejected(client: AsyncClient) -> None:
    response = await _check(client, [])
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


async def test_missing_companies_key_is_rejected(client: AsyncClient) -> None:
    response = await client.post(ENDPOINT, json={})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


async def test_company_without_rfc_or_name_is_rejected(client: AsyncClient) -> None:
    response = await _check(client, [{}])
    assert response.status_code == 422
    detail = response.json()["error"]["details"][0]["msg"]
    assert "at least one of 'rfc' or 'name'" in detail


async def test_company_with_blank_values_is_rejected(client: AsyncClient) -> None:
    response = await _check(client, [{"rfc": "   ", "name": "  "}])
    assert response.status_code == 422


async def test_unknown_field_is_rejected(client: AsyncClient) -> None:
    response = await _check(client, [{"rfc": KNOWN_RFC, "unexpected": "value"}])
    assert response.status_code == 422


# --- 10. Invalid RFC ----------------------------------------------------------
@pytest.mark.parametrize(
    "bad_rfc",
    ["TOO-SHORT", "XXXXXXXXXXXX", "1234567890123", "AAA08O8O8HL8!!", "A" * 100],
)
async def test_invalid_rfc_is_rejected(client: AsyncClient, bad_rfc: str) -> None:
    response = await _check(client, [{"rfc": bad_rfc}])
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


# --- 11. Large batch ----------------------------------------------------------
async def test_large_batch_is_handled(client: AsyncClient, pool: asyncpg.Pool) -> None:
    """A full-size batch of real RFCs resolves in one request."""
    rows = await pool.fetch(
        "SELECT DISTINCT rfc FROM sat_blacklist_record WHERE NOT is_redacted LIMIT 400"
    )
    companies = [{"rfc": row["rfc"]} for row in rows]
    companies += [{"rfc": ABSENT_RFC}] * 50

    response = await _check(client, companies)
    assert response.status_code == 200

    results = response.json()["results"]
    assert len(results) == len(companies)
    assert all(r["blacklisted"] for r in results[: len(rows)])
    assert not any(r["blacklisted"] for r in results[len(rows) :])


async def test_batch_over_the_limit_is_rejected(client: AsyncClient) -> None:
    from app.core.config import get_settings

    limit = get_settings().blacklist_max_companies_per_request
    response = await _check(client, [{"rfc": KNOWN_RFC}] * (limit + 1))

    assert response.status_code == 422
    assert "Too many companies" in str(response.json()["error"]["details"])


# --- 12. Database failure -----------------------------------------------------
class _FailingPool:
    """Stands in for a pool whose queries always fail."""

    async def fetch(self, *args: object, **kwargs: object) -> object:
        raise asyncpg.PostgresConnectionError("connection reset by peer")


async def test_database_failure_returns_503() -> None:
    app: FastAPI = create_app()
    app.dependency_overrides[get_pool] = lambda: _FailingPool()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await _check(client, [{"rfc": KNOWN_RFC}])

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "database_unavailable"


async def test_database_unavailable_error_shape() -> None:
    """The 503 envelope matches every other error response."""
    error = DatabaseUnavailableError()
    assert error.status_code == 503
    assert error.code == "database_unavailable"
