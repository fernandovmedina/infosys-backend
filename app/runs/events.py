"""The investigation log of a run, as the ordered events the frontend replays.

The engine audits a dataset in one call, so the log is written in two moments:
the start events when `execute_run` begins, and -- once the engine returns --
one event per detector, warning, finding and declined lead, then the official
validation and the outcome. Nothing here decides anything: every event restates
what the engine concluded, in Spanish, for the live feed, the log and search.

Pure and synchronous; `service.execute_run` stores what these functions build.
"""

from __future__ import annotations

import csv
import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.fraud.engine.catalogo import FAMILIA, FRASE_FAMILIA, NOMBRE_ESQUEMA, REGLAS_INTEGRIDAD
from app.fraud.schemas import FraudAnalysis
from app.runs.schemas import AgentRole, RunEventType

MAX_EVENT_ENTITIES = 5


@dataclass(slots=True)
class EventDraft:
    """An event before it gets its `seq` and timestamp from the database."""

    type: RunEventType
    role: AgentRole
    message: str
    payload: dict[str, Any] = field(default_factory=dict)

    def as_payload(self) -> dict[str, Any]:
        """Everything but seq/ts/type/role, without empty values."""
        return {
            "message": self.message,
            **{key: value for key, value in self.payload.items() if value is not None},
        }


def counters(started_at: dt.datetime | None, until: dt.datetime | None = None) -> dict[str, Any]:
    elapsed = 0.0
    if started_at is not None:
        end = until or dt.datetime.now(dt.UTC)
        elapsed = max((end - started_at).total_seconds(), 0.0)
    return {"llm_calls": 0, "mxn_cost": 0.0, "elapsed_seconds": round(elapsed, 1)}


def _money(amount: float) -> str:
    return f"${amount:,.2f}"


def _plural(count: int, singular: str, plural: str) -> str:
    return f"{count:,} {singular if count == 1 else plural}"


# ---------------------------------------------------------------------------
# Entity names
# ---------------------------------------------------------------------------


def _employee_id(emp_id: str) -> str:
    value = emp_id.strip()
    return f"EMP:{value.split(':', 1)[1]}" if value.upper().startswith("EMP:") else f"EMP:{value}"


@dataclass(slots=True)
class EntityNames:
    """Readable names of vendors and employees, read from the run's stored tables."""

    vendors: dict[str, str] = field(default_factory=dict)  # "RFC:X" -> legal name
    employees: dict[str, str] = field(default_factory=dict)  # "EMP:X" -> name
    employee_by_name: dict[str, str] = field(default_factory=dict)

    @classmethod
    def load(cls, tables_dir: Path) -> EntityNames:
        names = cls()
        for row in _read_csv(tables_dir / "vendors.csv"):
            rfc = (row.get("rfc") or "").strip().upper()
            if rfc:
                names.vendors[f"RFC:{rfc}"] = (row.get("legal_name") or "").strip() or f"RFC:{rfc}"
        for row in _read_csv(tables_dir / "employees.csv"):
            emp_id = (row.get("emp_id") or "").strip()
            if emp_id:
                name = (row.get("name") or "").strip()
                names.employees[_employee_id(emp_id)] = name or _employee_id(emp_id)
                if name:
                    names.employee_by_name.setdefault(name, _employee_id(emp_id))
        return names

    def entity_id(self, raw: str | None) -> str | None:
        """A signal's raw `entity_id` (RFC, employee id or name) as a prefixed id, if known."""
        value = (raw or "").strip()
        if not value:
            return None
        if value.upper().startswith(("RFC:", "EMP:")):
            return value
        if f"RFC:{value.upper()}" in self.vendors:
            return f"RFC:{value.upper()}"
        if _employee_id(value) in self.employees:
            return _employee_id(value)
        return self.employee_by_name.get(value)

    def names_for(self, entity_ids: list[str]) -> dict[str, str]:
        return {
            entity_id: self.vendors.get(entity_id) or self.employees.get(entity_id) or entity_id
            for entity_id in entity_ids
        }


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------


def start_events(table_rows: dict[str, int]) -> list[EventDraft]:
    present = {name: rows for name, rows in table_rows.items() if rows > 0}
    return [
        EventDraft("step", "system", "Investigación iniciada", {"kind": "start"}),
        EventDraft(
            "step",
            "system",
            "Cargando dataset",
            {
                "kind": "load",
                "result": (
                    f"{_plural(len(present), 'tabla', 'tablas')}, "
                    f"{_plural(sum(present.values()), 'registro', 'registros')}"
                ),
                "result_status": "ok",
            },
        ),
    ]


def _with_entities(payload: dict[str, Any], entity_ids: list[str], names: EntityNames) -> None:
    ids = list(dict.fromkeys(entity_ids))
    if ids:
        payload["entities"] = ids
        payload["entity_names"] = names.names_for(ids)


def analysis_events(
    analysis: FraudAnalysis, *, run_id: str, names: EntityNames
) -> list[EventDraft]:
    """Detectors, warnings, findings, declined leads, validation and completion, in that order."""
    events: list[EventDraft] = []

    signal_entities: dict[str, list[str]] = {}
    for signal in analysis.signals:
        entity_id = names.entity_id(signal.entity_id)
        if entity_id:
            bucket = signal_entities.setdefault(signal.rule_id, [])
            if entity_id not in bucket:
                bucket.append(entity_id)

    for rule_id, count in analysis.signals_per_rule.items():
        family = FAMILIA.get(rule_id)
        payload: dict[str, Any] = {
            "kind": "data_quality" if rule_id in REGLAS_INTEGRIDAD else "rule",
            "tool": rule_id,
            "detail": FRASE_FAMILIA.get(family) if family else None,
            "result": _plural(count, "señal", "señales") if count else "sin señales",
            "result_status": "warning" if count else "ok",
        }
        _with_entities(payload, signal_entities.get(rule_id, [])[:MAX_EVENT_ENTITIES], names)
        events.append(EventDraft("detector_result", "detector", f"Detector {rule_id}", payload))

    for warning in analysis.warnings:
        events.append(
            EventDraft(
                "warning", "system", warning, {"kind": "rule_failure", "result_status": "error"}
            )
        )

    submission = analysis.submission
    for number, finding in enumerate(submission.findings, start=1):
        scheme = NOMBRE_ESQUEMA.get(finding.scheme_type, finding.scheme_type)
        payload = {
            "kind": finding.scheme_type,
            "detail": finding.rule_broken,
            "result": "probado" if finding.confidence == "proven" else "probable",
            "result_status": "error" if finding.confidence == "proven" else "warning",
        }
        _with_entities(payload, finding.entities, names)
        events.append(
            EventDraft(
                "finding_draft",
                "investigator",
                f"Hallazgo #{number} · {scheme} por {_money(finding.peso_amount)}",
                payload,
            )
        )

    for lead in submission.leads_not_pursued:
        payload = {
            "kind": "lead",
            "entity": lead.entity,
            "detail": lead.reason,
            "result": "descartado",
            "result_status": "ok",
        }
        _with_entities(payload, [lead.entity], names)
        events.append(EventDraft("lead_closed", lead.closed_by, lead.signal, payload))

    events.append(
        EventDraft(
            "validation",
            "validator",
            "Submission validada con el validador oficial",
            {
                "kind": "official_validator",
                "result": (
                    f"{_plural(len(submission.findings), 'hallazgo', 'hallazgos')}, "
                    + _plural(
                        len(submission.leads_not_pursued), "caso descartado", "casos descartados"
                    )
                ),
                "result_status": "ok",
            },
        )
    )
    events.append(
        EventDraft(
            "completed",
            "system",
            "Investigación terminada",
            {"run_id": run_id, "report_url": f"/api/v1/runs/{run_id}/report"},
        )
    )
    return events


def failed_event(error: dict[str, Any]) -> EventDraft:
    return EventDraft(
        "failed", "system", str(error.get("message") or "La investigación falló."), {"error": error}
    )
