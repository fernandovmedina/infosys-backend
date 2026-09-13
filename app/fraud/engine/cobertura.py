"""Semantic check that every accused entity is supported by an exhibit.

The official format validator can prove that a cited record exists, but it
cannot tell whether that record actually involves each entity named in a
finding.  This module is deliberately stricter: it uses exact RFC, employee
id, name, and CLABE relationships from the estate and never infers a link from
a bank prefix or fuzzy name match.
"""

from __future__ import annotations

from dataclasses import dataclass

from .entidades import Entidad
from .estate import Estate


@dataclass(frozen=True)
class EntityCoverageFailure:
    entity: Entidad
    requirement: str


def _text(value: object) -> str:
    return str(value or "").strip()


def _upper(value: object) -> str:
    return _text(value).upper()


def _employee_id(value: object) -> str:
    text = _text(value)
    return text.split(":", 1)[1] if text.upper().startswith("EMP:") else text


def _rfc_in_row(row: dict, rfc: str) -> bool:
    return any(
        _upper(row.get(column)) == rfc
        for column in ("rfc", "issuer_rfc", "receiver_rfc", "vendor_rfc")
    )


def _bank_involves(row: dict, clabes: set[str]) -> bool:
    return _text(row.get("from_clabe")) in clabes or _text(row.get("to_clabe")) in clabes


def _employee_action(row: dict, employee_id: str, employee_name: str, clabes: set[str]) -> bool:
    table = row["_source_table"]
    if table == "bank_txns":
        return _bank_involves(row, clabes)
    if table in {"purchase_orders", "ledger"}:
        return any(
            _upper(row.get(column)) in {_upper(employee_id), _upper(employee_name)}
            for column in ("requester", "approver")
        )
    return False


def validate_entity_coverage(
    estate: Estate, entities: list[Entidad], exhibits: list[dict]
) -> list[EntityCoverageFailure]:
    """Return every accused entity without an exhibit proving its involvement.

    An RFC/company needs one role-bearing record.  An employee needs both its
    catalog identity and a separate action/payment record.  The distinction
    prevents an employee profile from being treated as proof of misconduct.
    """
    rows = [{**ex["_fila"], "_source_table": ex["source_table"]} for ex in exhibits]
    failures: list[EntityCoverageFailure] = []

    for entity in entities:
        if entity.tipo in {"rfc", "empresa"}:
            rfc = _upper(entity.canonico)
            clabes = (
                {_text(row.get("bank_clabe")) for row in estate.vendors_por_rfc(rfc)}
                if entity.tipo == "rfc"
                else set(estate.empresa_clabes)
            )
            clabes.discard("")
            supported = any(
                (row["_source_table"] != "vendors" and _rfc_in_row(row, rfc))
                or (row["_source_table"] == "bank_txns" and _bank_involves(row, clabes))
                for row in rows
            )
            if not supported:
                failures.append(
                    EntityCoverageFailure(entity, "a record linking it to the transaction")
                )
        elif entity.tipo == "employee":
            employee_id = _employee_id(entity.canonico)
            profiles = estate.employee_por_id(employee_id) or estate.employee_por_id(
                f"EMP:{employee_id}"
            )
            profile_ids = {_employee_id(row.get("emp_id")) for row in profiles}
            names = {_text(row.get("name")) for row in profiles}
            clabes = {_text(row.get("bank_clabe")) for row in profiles}
            clabes.discard("")
            identified = any(
                row["_source_table"] == "employees"
                and _employee_id(row.get("emp_id")) in profile_ids
                for row in rows
            )
            acted = any(
                _employee_action(row, employee_id, next(iter(sorted(names)), ""), clabes)
                for row in rows
            )
            if not identified or not acted:
                requirement = (
                    "their employee profile and a linked payment, approval, or request"
                    if not identified and not acted
                    else "their employee profile"
                    if not identified
                    else "a linked payment, approval, or request"
                )
                failures.append(EntityCoverageFailure(entity, requirement))
    return failures
