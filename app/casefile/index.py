"""In-memory index of a completed run: its stored estate tables joined with the fraud analysis.

Every case-file view (report, records, entities, graph, timeline, search) reads
from one `CaseIndex`. It is built from what the run already stored -- the
diagnosed tables under `storage/runs/<run_id>/tables` and the `fraud_analysis`
row -- and never re-runs the engine.

The tables are loaded with the same tolerant loader the engine used
(`app.fraud.loader.load_run_tables`), and the audited company is identified by the
engine's own `Estate`, so the case file sees exactly the estate the engine audited.

Everything here is synchronous (DuckDB); callers run it in a worker thread.
"""

from __future__ import annotations

import datetime as dt
import re
import threading
from collections import OrderedDict, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import duckdb

from app.casefile.schemas import CellValue, EntityKind, EntityStatus
from app.fraud.engine.catalogo import AMOUNT_COLUMN, REGLAS_INTEGRIDAD, TABLE_PK
from app.fraud.engine.estate import Estate
from app.fraud.loader import load_run_tables
from app.fraud.schemas import FraudAnalysis
from app.runs.estate import SourceTable

# Presentation order of the tables (the same the case file uses for exhibits).
TABLE_ORDER: tuple[SourceTable, ...] = (
    "invoices",
    "bank_txns",
    "ledger",
    "purchase_orders",
    "contracts",
    "vendors",
    "employees",
    "efos_list",
)

DATE_FIELD: dict[str, str] = {
    "invoices": "issue_date",
    "bank_txns": "date",
    "ledger": "date",
    "purchase_orders": "date",
    "contracts": "start_date",
    "vendors": "registered_date",
    "employees": "hire_date",
    "efos_list": "publication_date",
}
ID_FIELD: dict[str, str] = TABLE_PK
AMOUNT_FIELD: dict[str, str] = AMOUNT_COLUMN
MONEY_COLUMNS = frozenset({"subtotal", "iva", "total", "amount", "debit", "credit", "value"})
RFC_COLUMNS = frozenset({"issuer_rfc", "receiver_rfc", "vendor_rfc", "rfc"})
CLABE_COLUMNS = frozenset({"from_clabe", "to_clabe", "bank_clabe"})

_REFERENCE_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9:_-]*")


def record_key(table: str, record_id: str) -> str:
    return f"{table}:{record_id}"


def employee_entity_id(emp_id: str) -> str:
    """`EMP:0001` or `0001` -> `EMP:0001`, the prefixed id the engine cites."""
    value = emp_id.strip()
    canonical = value.split(":", 1)[1] if value.upper().startswith("EMP:") else value
    return f"EMP:{canonical}"


def split_trail_label(label: str) -> list[str]:
    """A money-trail endpoint can name several owners of one account: `EMP:1 / RFC:X`."""
    return [part.strip() for part in label.split(" / ") if part.strip()]


def _text(value: CellValue) -> str:
    return "" if value is None else str(value).strip()


@dataclass(slots=True)
class EntityBase:
    kind: EntityKind
    name: str
    role: str | None = None
    bank_clabe: str | None = None
    is_audited_company: bool = False
    profile: tuple[SourceTable, str] | None = None


@dataclass(frozen=True, slots=True)
class RunInfo:
    run_id: str
    filename: str
    sha256: str
    created_at: dt.datetime
    finished_at: dt.datetime | None
    tables: list[dict[str, Any]]


@dataclass(slots=True)
class CaseIndex:
    run: RunInfo
    analysis: FraudAnalysis
    company_rfc: str | None
    company_clabes: frozenset[str]
    period: tuple[str, str]
    tables: dict[SourceTable, list[dict[str, CellValue]]]
    rows: dict[SourceTable, dict[str, dict[str, CellValue]]] = field(default_factory=dict)
    entities: dict[str, EntityBase] = field(default_factory=dict)
    clabe_owners: dict[str, list[str]] = field(default_factory=dict)
    employees_by_name: dict[str, str] = field(default_factory=dict)
    status: dict[str, EntityStatus] = field(default_factory=dict)
    finding_indexes: dict[str, list[int]] = field(default_factory=dict)
    lead_index: dict[str, int] = field(default_factory=dict)
    cited_in: dict[str, list[tuple[int, str]]] = field(default_factory=dict)
    signals: dict[str, list[str]] = field(default_factory=dict)
    # Reverse lookups for `related` records and timelines.
    ledger_by_invoice: dict[str, list[str]] = field(default_factory=dict)
    txns_by_token: dict[str, list[str]] = field(default_factory=dict)
    by_vendor: dict[tuple[SourceTable, str], list[str]] = field(default_factory=dict)

    # --- entities -------------------------------------------------------------

    @property
    def company_id(self) -> str | None:
        return f"RFC:{self.company_rfc}" if self.company_rfc else None

    def entity(self, entity_id: str) -> EntityBase:
        """The entity, or a placeholder for an id the catalogs don't know (customer, account)."""
        known = self.entities.get(entity_id)
        if known is not None:
            return known
        prefix = entity_id.split(":", 1)[0]
        kind: EntityKind = {"EMP": "employee", "CLABE": "account"}.get(prefix, "unknown")  # type: ignore[assignment]
        return EntityBase(kind=kind, name=entity_id)

    def entity_status(self, entity_id: str) -> EntityStatus:
        return self.status.get(entity_id, "clear")

    def is_known(self, entity_id: str) -> bool:
        return entity_id in self.entities or entity_id in self.status

    def clabe_owner(self, clabe: str) -> str:
        """Entity that holds `clabe`: the company, a vendor or employee, else the bare account."""
        clabe = clabe.strip()
        if clabe in self.company_clabes and self.company_id:
            return self.company_id
        owners = self.clabe_owners.get(clabe)
        return owners[0] if owners else f"CLABE:{clabe}"

    def resolve(self, raw: str | None) -> list[str]:
        """Prefixed ids for a signal's heterogeneous `entity_id` (RFC, CLABE, emp id, name)."""
        value = (raw or "").strip()
        if not value:
            return []
        upper = value.upper()
        if upper.startswith("RFC:"):
            return [f"RFC:{upper[4:].strip()}"]
        if upper.startswith("CLABE:"):
            return [self.clabe_owner(value[6:])]
        if f"RFC:{upper}" in self.entities:
            return [f"RFC:{upper}"]
        employee = employee_entity_id(value)
        if employee in self.entities:
            return [employee]
        if value in self.clabe_owners or value in self.company_clabes:
            return [self.clabe_owner(value)]
        if value in self.employees_by_name:
            return [self.employees_by_name[value]]
        return []

    # --- records --------------------------------------------------------------

    def row(self, table: SourceTable, record_id: str) -> dict[str, CellValue] | None:
        by_id = self.rows.get(table, {})
        found = by_id.get(record_id)
        if found is None and table in ("vendors", "efos_list"):
            found = by_id.get(record_id.strip().upper())
        return found

    def record_id(self, table: SourceTable, row: dict[str, CellValue]) -> str:
        return _text(row.get(ID_FIELD[table]))

    def row_amount(self, table: SourceTable, row: dict[str, CellValue]) -> float | None:
        column = AMOUNT_FIELD.get(table)
        value = row.get(column) if column else None
        return float(value) if isinstance(value, int | float) else None

    def row_entity(self, table: SourceTable, row: dict[str, CellValue]) -> str | None:
        """The counterparty a record is about, seen from the audited company."""
        match table:
            case "invoices":
                issuer = _text(row.get("issuer_rfc")).upper()
                receiver = _text(row.get("receiver_rfc")).upper()
                other = receiver if issuer == self.company_rfc else issuer
                return f"RFC:{other}" if other else None
            case "bank_txns":
                origin = _text(row.get("from_clabe"))
                target = _text(row.get("to_clabe"))
                if origin in self.company_clabes:
                    return self.clabe_owner(target) if target else None
                if target in self.company_clabes:
                    return self.clabe_owner(origin) if origin else None
                return self.clabe_owner(target) if target else None
            case "ledger":
                invoice = self.row("invoices", _text(row.get("invoice_uuid")))
                return self.row_entity("invoices", invoice) if invoice else None
            case "purchase_orders" | "contracts":
                rfc = _text(row.get("vendor_rfc")).upper()
                return f"RFC:{rfc}" if rfc else None
            case "vendors" | "efos_list":
                rfc = _text(row.get("rfc")).upper()
                return f"RFC:{rfc}" if rfc else None
            case "employees":
                emp_id = _text(row.get("emp_id"))
                return employee_entity_id(emp_id) if emp_id else None
        return None

    def direction(self, row: dict[str, CellValue]) -> str:
        """`salida` when the money leaves a company account, else `entrada`."""
        return "salida" if _text(row.get("from_clabe")) in self.company_clabes else "entrada"


# ---------------------------------------------------------------------------
# Building
# ---------------------------------------------------------------------------


def _cell(column: str, value: Any) -> CellValue:
    if value is None:
        return None
    if column in MONEY_COLUMNS and isinstance(value, int | float):
        # REAL columns come back as float32: round to centavos.
        return round(float(value), 2)
    if isinstance(value, str | int | float):
        return value
    return str(value)


def _fetch_table(con: duckdb.DuckDBPyConnection, table: SourceTable) -> list[dict[str, CellValue]]:
    # `table` comes from TABLE_ORDER (a closed list), never from the request.
    cursor = con.execute(f"SELECT * FROM {table} ORDER BY {ID_FIELD[table]}")
    columns = [d[0] for d in cursor.description]
    return [
        {column: _cell(column, value) for column, value in zip(columns, row, strict=True)}
        for row in cursor.fetchall()
    ]


def build_index(directory: Path, run: RunInfo, analysis: FraudAnalysis) -> CaseIndex:
    """Load the run's stored tables and join them with its analysis."""
    with duckdb.connect() as con:
        load_run_tables(con, directory)
        estate = Estate(con)
        start, end = estate.periodo()
        index = CaseIndex(
            run=run,
            analysis=analysis,
            company_rfc=estate.empresa_rfc,
            company_clabes=frozenset(c for c in estate.empresa_clabes if c),
            period=(start or "", end or ""),
            tables={table: _fetch_table(con, table) for table in TABLE_ORDER},
        )
    _index_rows(index)
    _index_entities(index)
    _index_analysis(index)
    return index


def identify_company(directory: Path) -> tuple[str | None, str | None]:
    """(RFC, legal name) of the audited company, found the way the engine finds it."""
    with duckdb.connect() as con:
        load_run_tables(con, directory)
        estate = Estate(con)
        if not estate.empresa_rfc:
            return None, None
        vendors = estate.vendors_por_rfc(estate.empresa_rfc)
        name = _text(vendors[0].get("legal_name")) if vendors else ""
        return estate.empresa_rfc, name or None


def _index_rows(index: CaseIndex) -> None:
    for table in TABLE_ORDER:
        by_id: dict[str, dict[str, CellValue]] = {}
        for row in index.tables[table]:
            record_id = index.record_id(table, row)
            by_id.setdefault(record_id, row)
            if table in ("vendors", "efos_list"):
                by_id.setdefault(record_id.upper(), row)
        index.rows[table] = by_id

    ledger_by_invoice: defaultdict[str, list[str]] = defaultdict(list)
    for row in index.tables["ledger"]:
        uuid = _text(row.get("invoice_uuid"))
        if uuid:
            ledger_by_invoice[uuid].append(index.record_id("ledger", row))
    index.ledger_by_invoice = dict(ledger_by_invoice)

    txns_by_token: defaultdict[str, list[str]] = defaultdict(list)
    for row in index.tables["bank_txns"]:
        for token in set(_REFERENCE_TOKEN.findall(_text(row.get("reference")))):
            txns_by_token[token].append(index.record_id("bank_txns", row))
    index.txns_by_token = dict(txns_by_token)

    by_vendor: defaultdict[tuple[SourceTable, str], list[str]] = defaultdict(list)
    for table in ("purchase_orders", "contracts"):
        for row in index.tables[table]:
            rfc = _text(row.get("vendor_rfc")).upper()
            by_vendor[(table, rfc)].append(index.record_id(table, row))
    index.by_vendor = dict(by_vendor)


def _index_entities(index: CaseIndex) -> None:
    clabe_owners: defaultdict[str, list[str]] = defaultdict(list)
    vendor_rows = {_text(row.get("rfc")).upper(): row for row in index.tables["vendors"]}

    for rfc, row in vendor_rows.items():
        if not rfc:
            continue
        entity_id = f"RFC:{rfc}"
        clabe = _text(row.get("bank_clabe")) or None
        index.entities[entity_id] = EntityBase(
            kind="company" if rfc == index.company_rfc else "vendor",
            name=_text(row.get("legal_name")) or entity_id,
            bank_clabe=clabe,
            is_audited_company=rfc == index.company_rfc,
            profile=("vendors", index.record_id("vendors", row)),
        )
        if clabe:
            clabe_owners[clabe].append(entity_id)

    for row in index.tables["employees"]:
        emp_id = _text(row.get("emp_id"))
        if not emp_id:
            continue
        entity_id = employee_entity_id(emp_id)
        clabe = _text(row.get("bank_clabe")) or None
        name = _text(row.get("name")) or entity_id
        index.entities[entity_id] = EntityBase(
            kind="employee",
            name=name,
            role=_text(row.get("role")) or None,
            bank_clabe=clabe,
            profile=("employees", emp_id),
        )
        index.employees_by_name.setdefault(name, entity_id)
        if clabe:
            clabe_owners[clabe].append(entity_id)

    if index.company_id and index.company_id not in index.entities:
        index.entities[index.company_id] = EntityBase(
            kind="company",
            name="Empresa auditada",
            bank_clabe=min(index.company_clabes) if index.company_clabes else None,
            is_audited_company=True,
        )

    # RFCs that only appear on the SAT list or on invoices (customers) keep a readable name.
    for row in index.tables["efos_list"]:
        rfc = _text(row.get("rfc")).upper()
        if rfc and f"RFC:{rfc}" not in index.entities:
            index.entities[f"RFC:{rfc}"] = EntityBase(
                kind="unknown", name=_text(row.get("legal_name")) or f"RFC:{rfc}"
            )
    index.clabe_owners = dict(clabe_owners)


def _index_analysis(index: CaseIndex) -> None:
    submission = index.analysis.submission
    finding_indexes: defaultdict[str, list[int]] = defaultdict(list)
    cited_in: defaultdict[str, list[tuple[int, str]]] = defaultdict(list)

    for lead_number, lead in enumerate(submission.leads_not_pursued):
        index.status[lead.entity] = "declined"
        index.lead_index.setdefault(lead.entity, lead_number)
    for finding_number, finding in enumerate(submission.findings):
        for entity_id in finding.entities:
            index.status[entity_id] = "accused"
            if finding_number not in finding_indexes[entity_id]:
                finding_indexes[entity_id].append(finding_number)
        for exhibit in finding.exhibits:
            key = record_key(exhibit.source_table, exhibit.record_id)
            cited_in[key].append((finding_number, exhibit.exhibit_id))
    index.finding_indexes = dict(finding_indexes)
    index.cited_in = dict(cited_in)

    signals: defaultdict[str, list[str]] = defaultdict(list)
    for signal in index.analysis.signals:
        if signal.rule_id in REGLAS_INTEGRIDAD:
            continue  # data-quality checks are not signals against an entity
        for entity_id in index.resolve(signal.entity_id):
            if signal.rule_id not in signals[entity_id]:
                signals[entity_id].append(signal.rule_id)
    index.signals = dict(signals)


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

_CACHE_SIZE = 8
_cache: OrderedDict[tuple[str, str], CaseIndex] = OrderedDict()
_cache_lock = threading.Lock()


def _cache_key(run: RunInfo) -> tuple[str, str]:
    # A re-run of the same run finishes again, so `finished_at` tells the versions apart.
    return (run.run_id, run.finished_at.isoformat() if run.finished_at else "")


def cached(run: RunInfo) -> CaseIndex | None:
    with _cache_lock:
        hit = _cache.get(_cache_key(run))
        if hit is not None:
            _cache.move_to_end(_cache_key(run))
        return hit


def remember(index: CaseIndex) -> None:
    with _cache_lock:
        for key in [key for key in _cache if key[0] == index.run.run_id]:
            del _cache[key]
        _cache[_cache_key(index.run)] = index
        while len(_cache) > _CACHE_SIZE:
            _cache.popitem(last=False)
