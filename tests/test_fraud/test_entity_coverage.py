"""The engine must not publish entities without documentary involvement."""

from typing import Any

import pytest

from app.fraud.engine import ensamblador as ensamblador_module
from app.fraud.engine.cobertura import EntityCoverageFailure, validate_entity_coverage
from app.fraud.engine.entidades import Entidad
from app.fraud.engine.estate import Estate
from app.fraud.engine.pipeline import auditar_conexion


def _exhibit(table: str, row: dict[str, Any]) -> dict[str, Any]:
    return {"source_table": table, "_fila": row}


def test_vendor_profile_alone_does_not_prove_operational_involvement(
    con: Any, insertar: Any
) -> None:
    insertar(
        "vendors",
        {"rfc": "VEN010101AAA", "legal_name": "Proveedor", "bank_clabe": "111"},
    )
    estate = Estate(con)
    entity = Entidad("rfc", "VEN010101AAA")

    failures = validate_entity_coverage(
        estate,
        [entity],
        [_exhibit("vendors", {"rfc": "VEN010101AAA", "bank_clabe": "111"})],
    )

    assert [failure.entity for failure in failures] == [entity]
    assert "transaction" in failures[0].requirement


def test_invoice_supports_vendor_by_exact_rfc(con: Any, insertar: Any) -> None:
    insertar(
        "vendors",
        {"rfc": "VEN010101AAA", "legal_name": "Proveedor", "bank_clabe": "111"},
    )
    estate = Estate(con)

    failures = validate_entity_coverage(
        estate,
        [Entidad("rfc", "VEN010101AAA")],
        [
            _exhibit(
                "invoices",
                {"issuer_rfc": "VEN010101AAA", "receiver_rfc": "EMP010101AAA"},
            )
        ],
    )

    assert failures == []


def test_employee_requires_identity_and_action_exhibits(con: Any, insertar: Any) -> None:
    insertar(
        "employees",
        {"emp_id": "EMP:0001", "name": "Ana Auditora", "bank_clabe": "222"},
    )
    estate = Estate(con)
    entity = Entidad("employee", "0001")
    profile = _exhibit(
        "employees", {"emp_id": "EMP:0001", "name": "Ana Auditora", "bank_clabe": "222"}
    )

    failures = validate_entity_coverage(estate, [entity], [profile])
    assert [failure.entity for failure in failures] == [entity]
    assert "payment, approval, or request" in failures[0].requirement

    failures = validate_entity_coverage(
        estate,
        [entity],
        [
            profile,
            _exhibit(
                "purchase_orders",
                {"requester": "Otra persona", "approver": "Ana Auditora"},
            ),
        ],
    )
    assert failures == []


def test_unsupported_entity_becomes_a_declined_lead(
    con_1301: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unsupported(
        _estate: Any, entities: list[Entidad], _exhibits: list[dict[str, Any]]
    ) -> list[EntityCoverageFailure]:
        return [EntityCoverageFailure(entities[0], "un vínculo documental")]

    monkeypatch.setattr(ensamblador_module, "validate_entity_coverage", unsupported)

    result = auditar_conexion(con_1301, seed=1301)

    assert result.validacion_ok, result.errores_validacion
    assert result.submission["findings"] == []
    assert any(
        "vínculo documental" in lead["reason"]
        for lead in result.submission["leads_not_pursued"]
    )
