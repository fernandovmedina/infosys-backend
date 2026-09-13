"""Case-file view models built from a `CaseIndex`: pure functions, no I/O.

Each function answers one endpoint of the interactive case file. They explain
what the engine concluded -- which records it cited, how the money moved, who
was accused or cleared -- and never add accusations of their own.
"""

from __future__ import annotations

import itertools
import unicodedata
from collections.abc import Iterable
from typing import Literal

from app.casefile.index import (
    AMOUNT_FIELD,
    CLABE_COLUMNS,
    DATE_FIELD,
    RFC_COLUMNS,
    TABLE_ORDER,
    CaseIndex,
    employee_entity_id,
    record_key,
    split_trail_label,
)
from app.casefile.schemas import (
    AuditPeriod,
    CaseHeader,
    CellValue,
    Citation,
    DatasetInfo,
    Entity,
    EntityListItem,
    EntityPage,
    EntityStatus,
    EntityTimeline,
    FindingExtra,
    GraphData,
    GraphEdge,
    GraphNode,
    GraphScope,
    MethodAndLimits,
    OtherTableSum,
    Reconciliation,
    ReconciliationLine,
    RecordPage,
    RecordRef,
    RecordRow,
    RecordView,
    Report,
    ReportRun,
    ReportSummary,
    Reproduce,
    SearchHit,
    SearchLocation,
    SearchResponse,
    SharedEntity,
    TimelineAnnotation,
    TimelineEvent,
    TimelineLane,
    TimelineTotals,
)
from app.fraud.engine.catalogo import NOMBRE_ESQUEMA, PRIORIDAD_MONTO, TOLERANCIA_PESOS
from app.fraud.schemas import Finding
from app.fraud.service import ENGINE_VERSION
from app.runs.estate import TABLE_SPECS, SourceTable
from app.runs.schemas import RunEvent, TableDiagnostic
from app.runs.service import verdict_of

MAX_RELATED = 8
DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 500
SEARCH_ENTITY_LIMIT = 8
SEARCH_LOG_LIMIT = 5

TABLE_LABEL: dict[str, str] = {
    "invoices": "Invoice",
    "bank_txns": "Bank transfer",
    "ledger": "Ledger entry",
    "purchase_orders": "Purchase order",
    "contracts": "Contract",
    "vendors": "Vendor",
    "employees": "Employee",
    "efos_list": "Article 69-B list",
}
STATUS_LABEL: dict[str, str] = {
    "accused": "Accused",
    "declined": "Cleared",
    "clear": "No signals",
}
_DATED_TABLES = frozenset({"invoices", "bank_txns", "purchase_orders", "contracts", "ledger"})
_STATUS_ORDER: dict[str, int] = {"accused": 0, "declined": 1, "clear": 2}


def _money(amount: float) -> str:
    return f"${amount:,.2f}"


def _round2(value: float) -> float:
    return round(value + 0.0, 2)


def normalize(text: str) -> str:
    """Case- and accent-insensitive form for search and filters."""
    decomposed = unicodedata.normalize("NFD", text.lower())
    return "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")


def _text(value: CellValue) -> str:
    return "" if value is None else str(value).strip()


def _period(period: tuple[str, str]) -> AuditPeriod:
    return AuditPeriod.model_validate({"from": period[0], "to": period[1]})


def _scheme_name(finding: Finding) -> str:
    return NOMBRE_ESQUEMA.get(finding.scheme_type, finding.scheme_type)


# ---------------------------------------------------------------------------
# Entities
# ---------------------------------------------------------------------------


def entity_view(index: CaseIndex, entity_id: str) -> Entity:
    base = index.entity(entity_id)
    return Entity(
        kind=base.kind,
        name=base.name,
        status=index.entity_status(entity_id),
        role=base.role,
        bank_clabe=base.bank_clabe,
        is_audited_company=True if base.is_audited_company else None,
        signals=index.signals.get(entity_id, []),
        finding_indexes=index.finding_indexes.get(entity_id, []),
        lead_index=index.lead_index.get(entity_id),
    )


def entity_population(index: CaseIndex) -> list[str]:
    """Every entity the case file can list: the catalogs plus whoever the analysis names.

    The audited company is left out (it is the subject of the audit, not a
    counterparty), so the entity list, its status counts and the graph's hidden
    count all describe the same population.
    """
    ids = dict.fromkeys([*index.entities, *index.status])
    return [entity_id for entity_id in ids if entity_id != index.company_id]


def _page_bounds(cursor: str | None, limit: int | None) -> tuple[int, int]:
    try:
        offset = max(int(cursor or 0), 0)
    except ValueError:
        offset = 0
    size = min(max(limit or DEFAULT_PAGE_SIZE, 1), MAX_PAGE_SIZE)
    return offset, size


def _next_cursor(offset: int, size: int, total: int) -> str | None:
    return str(offset + size) if offset + size < total else None


def entities_page(
    index: CaseIndex, *, status: EntityStatus | None, limit: int | None, cursor: str | None
) -> EntityPage:
    """Vendors, employees and every entity the analysis mentions; accused first."""
    items = [
        EntityListItem(id=entity_id, **entity_view(index, entity_id).model_dump())
        for entity_id in entity_population(index)
    ]
    if status:
        items = [item for item in items if item.status == status]
    items.sort(key=lambda item: (_STATUS_ORDER[item.status], normalize(item.name), item.id))
    offset, size = _page_bounds(cursor, limit)
    return EntityPage(
        items=items[offset : offset + size],
        next_cursor=_next_cursor(offset, size, len(items)),
        total=len(items),
    )


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


def _related(index: CaseIndex, table: SourceTable, row: dict[str, CellValue]) -> list[RecordRef]:
    refs: list[RecordRef] = []
    seen: set[str] = set()

    def add(source_table: SourceTable, record_ids: Iterable[str]) -> None:
        for record_id in record_ids:
            key = record_key(source_table, record_id)
            if record_id and key not in seen and index.row(source_table, record_id) is not None:
                seen.add(key)
                refs.append(RecordRef(source_table=source_table, record_id=record_id))

    def rows_where(source_table: SourceTable, column: str, value: str) -> list[str]:
        if not value:
            return []
        return [
            index.record_id(source_table, other)
            for other in index.tables[source_table]
            if _text(other.get(column)) == value
        ]

    match table:
        case "invoices":
            uuid = _text(row.get("uuid"))
            add("ledger", index.ledger_by_invoice.get(uuid, []))
            add("bank_txns", index.txns_by_token.get(uuid, []))
        case "bank_txns":
            tokens = _text(row.get("reference")).replace(",", " ").split()
            add("invoices", tokens)
            add("purchase_orders", tokens)
        case "ledger":
            add("invoices", [_text(row.get("invoice_uuid"))])
        case "vendors":
            rfc = _text(row.get("rfc")).upper()
            clabe = _text(row.get("bank_clabe"))
            add("efos_list", [rfc])
            add("contracts", index.by_vendor.get(("contracts", rfc), []))
            add("employees", rows_where("employees", "bank_clabe", clabe))
            same_account = rows_where("vendors", "bank_clabe", clabe)
            same_address = rows_where("vendors", "address", _text(row.get("address")))
            add("vendors", [r for r in same_account + same_address if r.upper() != rfc])
            add("purchase_orders", index.by_vendor.get(("purchase_orders", rfc), []))
        case "efos_list":
            add("vendors", [_text(row.get("rfc")).upper()])
        case "employees":
            add("vendors", rows_where("vendors", "bank_clabe", _text(row.get("bank_clabe"))))
        case "purchase_orders":
            rfc = _text(row.get("vendor_rfc")).upper()
            add("vendors", [rfc])
            add("contracts", index.by_vendor.get(("contracts", rfc), []))
            add("bank_txns", index.txns_by_token.get(_text(row.get("po_id")), []))
        case "contracts":
            rfc = _text(row.get("vendor_rfc")).upper()
            add("vendors", [rfc])
            add("purchase_orders", index.by_vendor.get(("purchase_orders", rfc), []))
    return refs[:MAX_RELATED]


def _highlights(
    index: CaseIndex, table: SourceTable, row: dict[str, CellValue], citations: list[Citation]
) -> list[str]:
    """Fields that make a cited record evidence: its amount, date and the accused parties."""
    if not citations:
        return []
    accused: set[str] = set()
    for citation in citations:
        accused.update(index.analysis.submission.findings[citation.finding_index].entities)
    fields = [f for f in (AMOUNT_FIELD.get(table), DATE_FIELD.get(table)) if f and f in row]
    for column, value in row.items():
        text = _text(value)
        if not text:
            continue
        if _names_accused(index, column, text, accused):
            fields.append(column)
    return list(dict.fromkeys(fields))


def _names_accused(index: CaseIndex, column: str, value: str, accused: set[str]) -> bool:
    """Whether a cell points at one of the accused parties (by RFC, account, id or name)."""
    if column in RFC_COLUMNS:
        return f"RFC:{value.upper()}" in accused
    if column in CLABE_COLUMNS:
        return index.clabe_owner(value) in accused
    if column == "emp_id":
        return employee_entity_id(value) in accused
    if column in ("approver", "requester"):
        return index.employees_by_name.get(value) in accused
    return False


def record_view(index: CaseIndex, table: SourceTable, record_id: str) -> RecordView | None:
    row = index.row(table, record_id)
    if row is None:
        return None
    record_id = index.record_id(table, row)
    citations = [
        Citation(finding_index=finding_index, exhibit_id=exhibit_id)
        for finding_index, exhibit_id in index.cited_in.get(record_key(table, record_id), [])
    ]
    return RecordView(
        source_table=table,
        record_id=record_id,
        data=dict(row),
        highlight_fields=_highlights(index, table, row, citations),
        cited_in=citations,
        related=_related(index, table, row),
    )


def records_page(
    index: CaseIndex,
    *,
    table: SourceTable,
    entity: str | None = None,
    risk: EntityStatus | None = None,
    cited: bool | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    amount_min: float | None = None,
    amount_max: float | None = None,
    status: str | None = None,
    channel: str | None = None,
    limit: int | None = None,
    cursor: str | None = None,
) -> RecordPage:
    date_field = DATE_FIELD[table]
    needle = normalize(entity.strip()) if entity else ""
    matches: list[tuple[str, str, dict[str, CellValue], str | None, EntityStatus | None]] = []

    for row in index.tables[table]:
        record_id = index.record_id(table, row)
        entity_id = index.row_entity(table, row)
        row_risk = (
            index.entity_status(entity_id) if entity_id and index.is_known(entity_id) else None
        )
        date = _text(row.get(date_field))
        amount = index.row_amount(table, row)

        if needle:
            name = normalize(index.entity(entity_id).name) if entity_id else ""
            if not entity_id or (needle not in normalize(entity_id) and needle not in name):
                continue
        if risk and row_risk != risk:
            continue
        if cited and record_key(table, record_id) not in index.cited_in:
            continue
        if date_from and date < date_from:
            continue
        if date_to and date > date_to:
            continue
        if amount_min is not None and (amount is None or amount < amount_min):
            continue
        if amount_max is not None and (amount is None or amount > amount_max):
            continue
        if status and _text(row.get("status")) != status:
            continue
        if channel and _text(row.get("channel")) != channel:
            continue
        matches.append((date, record_id, row, entity_id, row_risk))

    matches.sort(key=lambda match: (match[0], match[1]))
    offset, size = _page_bounds(cursor, limit)
    items = []
    for _, record_id, _row, entity_id, row_risk in matches[offset : offset + size]:
        view = record_view(index, table, record_id)
        assert view is not None
        items.append(RecordRow(**view.model_dump(), entity=entity_id, risk=row_risk))
    return RecordPage(
        items=items, next_cursor=_next_cursor(offset, size, len(matches)), total=len(matches)
    )


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def _reconciliation(index: CaseIndex, finding: Finding) -> Reconciliation:
    """Re-add the cited amounts per table, the way the official validator checks peso_amount."""
    lines: dict[SourceTable, list[ReconciliationLine]] = {}
    for exhibit in finding.exhibits:
        if exhibit.source_table not in AMOUNT_FIELD:
            continue
        row = index.row(exhibit.source_table, exhibit.record_id)
        amount = index.row_amount(exhibit.source_table, row) if row else None
        if amount is None:
            continue
        lines.setdefault(exhibit.source_table, []).append(
            ReconciliationLine(
                exhibit_id=exhibit.exhibit_id, record_id=exhibit.record_id, amount=amount
            )
        )
    sums = {table: _round2(sum(line.amount for line in rows)) for table, rows in lines.items()}
    claimed = finding.peso_amount
    preference = PRIORIDAD_MONTO.get(finding.scheme_type, list(AMOUNT_FIELD))

    if sums:
        table_used: SourceTable = min(
            sums,
            key=lambda t: (
                abs(claimed - sums[t]),
                preference.index(t) if t in preference else len(preference),
            ),
        )
    else:
        table_used = finding.exhibits[0].source_table if finding.exhibits else "invoices"
    total = sums.get(table_used, 0.0)
    diff = _round2(total - claimed)
    return Reconciliation(
        table_used=table_used,
        lines=lines.get(table_used, []),
        sum=total,
        claimed=claimed,
        diff=diff,
        diff_pct=_round2(diff / claimed * 100) if claimed else 0.0,
        within_tolerance=bool(sums) and abs(claimed - total) <= TOLERANCIA_PESOS * max(total, 1),
        other_tables=[
            OtherTableSum(
                table=table,
                sum=sums[table],
                exhibit_ids=[line.exhibit_id for line in lines[table]],
            )
            for table in TABLE_ORDER
            if table in sums and table != table_used
        ],
    )


def _finding_annotations(
    index: CaseIndex, finding_number: int, finding: Finding
) -> list[TimelineAnnotation]:
    """One mark per dated exhibit about an accused party, for the entity timelines."""
    annotations: dict[tuple[str, str], TimelineAnnotation] = {}
    for exhibit in finding.exhibits:
        row = index.row(exhibit.source_table, exhibit.record_id)
        if row is None:
            continue
        if exhibit.source_table not in _DATED_TABLES:
            continue  # a registration or hire date is profile data, not part of the scheme
        date = _text(row.get(DATE_FIELD[exhibit.source_table]))
        entity_id = index.row_entity(exhibit.source_table, row)
        if not date or entity_id not in finding.entities:
            continue
        label = (
            f"Hallazgo #{finding_number + 1} · {exhibit.exhibit_id} "
            f"{TABLE_LABEL[exhibit.source_table].lower()} {exhibit.record_id}"
        )
        annotations.setdefault(
            (date, exhibit.exhibit_id),
            TimelineAnnotation(date=date, entity=entity_id, label=label),
        )
    return sorted(annotations.values(), key=lambda a: (a.date, a.label))


def findings_extra(index: CaseIndex) -> list[FindingExtra]:
    findings = index.analysis.submission.findings
    extras = []
    for number, finding in enumerate(findings):
        shared = [
            SharedEntity(entity=entity_id, other_finding_index=other)
            for entity_id in finding.entities
            for other in index.finding_indexes.get(entity_id, [])
            if other != number
        ]
        extras.append(
            FindingExtra(
                finding_index=number,
                reconciliation=_reconciliation(index, finding),
                shared_entities=shared,
                timeline_annotations=_finding_annotations(index, number, finding),
            )
        )
    return extras


def headline(index: CaseIndex) -> str:
    submission = index.analysis.submission
    findings, leads = submission.findings, submission.leads_not_pursued
    records = sum(len(rows) for rows in index.tables.values())
    declined = (
        f"We reviewed {len(leads)} suspicious case{'s' if len(leads) != 1 else ''}; "
        "none met the accusation threshold."
    )
    if not findings:
        if leads:
            return f"We found no fraud in {records:,} records. {declined}"
        return f"We found no fraud signals in {records:,} records."
    total = sum(f.peso_amount for f in findings)
    parts = ", ".join(f"{_scheme_name(f)} for {_money(f.peso_amount)}" for f in findings)
    noun = "finding" if len(findings) == 1 else "findings"
    text = f"We found {len(findings)} {noun} with exposure of {_money(total)}: {parts}."
    if leads:
        text += f" Additionally, {declined[0].lower()}{declined[1:]}"
    return text


def _method_and_limits(index: CaseIndex) -> MethodAndLimits:
    analysis = index.analysis
    specs = {spec.name: spec for spec in TABLE_SPECS}
    out_of_scope = [
        "Only the company's bank accounts are visible; movements between third parties are not.",
        "Data-quality signals are reported separately and never accuse on their own.",
    ]
    for table in index.run.tables:
        if table.get("missing"):
            loss = specs[table["name"]].capability_loss
            out_of_scope.append(f"Without table {table['name']}: {loss}.")
    out_of_scope.extend(analysis.warnings)
    return MethodAndLimits(
        architecture=(
            f"Deterministic engine with no language models: {analysis.rules_evaluated} "
            "fiscal and accounting rule-based detectors inspect the 8 tables and emit "
            "signals with the exact supporting record. An assembler groups signals by "
            "entity and accuses only when at least two independent evidence families "
            "agree (or one independently sufficient rule does); everything else is "
            "documented as a cleared case. Before publication, the official validator "
            "confirms that every exhibit exists and that the claimed amount reconciles "
            f"within {TOLERANCIA_PESOS:.0%} of the cited records."
        ),
        out_of_scope=out_of_scope,
        cannot_detect=[
            "Cash payments with no accounting or bank record.",
            "Agreements or bribes that never pass through the company's books.",
            "Phantom vendors with consistently documented contracts, purchase orders, "
            "and registration.",
            "Schemes with only one signal: without independent corroborating evidence, "
            "they are cleared.",
        ],
        reproduce=Reproduce(
            seed=analysis.seed,
            version=ENGINE_VERSION,
            dataset_sha256=index.run.sha256,
            command=(
                f'POST /api/v1/runs/{index.run.run_id}/start {{"seed": {analysis.seed}}}'
                " (same dataset, same result)"
            ),
        ),
    )


def build_report(index: CaseIndex) -> Report:
    submission = index.analysis.submission
    findings = submission.findings

    ids: list[str] = [index.company_id] if index.company_id else []
    for finding in findings:
        ids.extend(finding.entities)
        for step in finding.money_trail:
            ids.extend(split_trail_label(step.from_) + split_trail_label(step.to))
    ids.extend(lead.entity for lead in submission.leads_not_pursued)
    entities = {entity_id: entity_view(index, entity_id) for entity_id in dict.fromkeys(ids)}

    records: dict[str, RecordView] = {}
    for finding in findings:
        for exhibit in finding.exhibits:
            view = record_view(index, exhibit.source_table, exhibit.record_id)
            if view is None:
                continue
            records[record_key(exhibit.source_table, exhibit.record_id)] = view
            for related in view.related:
                key = record_key(related.source_table, related.record_id)
                if key not in records:
                    related_view = record_view(index, related.source_table, related.record_id)
                    if related_view is not None:
                        records[key] = related_view

    population = entity_population(index)
    statuses = [index.entity_status(entity_id) for entity_id in population]
    accused, declined = statuses.count("accused"), statuses.count("declined")
    company = index.entity(index.company_id) if index.company_id else None

    return Report(
        run=ReportRun(
            run_id=index.run.run_id,
            status="completed",
            created_at=index.run.created_at.isoformat(),
            finished_at=index.run.finished_at.isoformat() if index.run.finished_at else None,
            dataset=DatasetInfo(
                filename=index.run.filename,
                sha256=index.run.sha256,
                tables=[TableDiagnostic.model_validate(t) for t in index.run.tables],
            ),
        ),
        case_header=CaseHeader(
            company_name=company.name if company else "Empresa auditada",
            company_rfc=index.company_rfc or "",
            audit_period=_period(index.period),
        ),
        summary=ReportSummary(
            verdict=verdict_of(submission),
            headline=headline(index),
            findings_count=len(findings),
            findings_by_confidence={
                "proven": sum(1 for f in findings if f.confidence == "proven"),
                "probable": sum(1 for f in findings if f.confidence == "probable"),
            },
            total_exposure=index.analysis.total_exposure,
            leads_closed_count=len(submission.leads_not_pursued),
            entities_by_status={
                "accused": accused,
                "declined": declined,
                "clear": len(population) - accused - declined,
            },
        ),
        submission=submission,
        findings_extra=findings_extra(index),
        entities=entities,
        records=records,
        method_and_limits=_method_and_limits(index),
    )


# ---------------------------------------------------------------------------
# Graph
# ---------------------------------------------------------------------------


def build_graph(index: CaseIndex, scope: GraphScope) -> GraphData:
    """Company, flagged entities (every vendor and employee for `all`) and money between them."""
    findings = index.analysis.submission.findings
    node_ids: dict[str, None] = {}
    if index.company_id:
        node_ids[index.company_id] = None
    for entity_id in index.status:
        node_ids[entity_id] = None

    trail_findings: dict[tuple[str, str], list[int]] = {}
    cycle_pairs: set[tuple[str, str]] = set()
    for number, finding in enumerate(findings):
        for step in finding.money_trail:
            for origin in split_trail_label(step.from_):
                for target in split_trail_label(step.to):
                    node_ids.setdefault(origin, None)
                    node_ids.setdefault(target, None)
                    pair = (origin, target)
                    if number not in trail_findings.setdefault(pair, []):
                        trail_findings[pair].append(number)
                    if finding.scheme_type == "round_tripping":
                        cycle_pairs.add(pair)
    if scope == "all":
        for entity_id, base in index.entities.items():
            if base.kind in ("vendor", "employee"):
                node_ids.setdefault(entity_id, None)

    edges: dict[str, GraphEdge] = {}

    def add_edge(
        origin: str,
        target: str,
        amount: float | None,
        kind: Literal["payment", "invoice", "relation"],
        label: str | None = None,
    ) -> None:
        if origin == target or origin not in node_ids or target not in node_ids:
            return
        edge_id = f"{kind}:{origin}>{target}"
        existing = edges.get(edge_id)
        if existing is not None:
            existing.count += 1
            if amount is not None:
                existing.amount = _round2((existing.amount or 0.0) + amount)
            return
        edges[edge_id] = GraphEdge.model_validate(
            {
                "id": edge_id,
                "from": origin,
                "to": target,
                "amount": amount,
                "count": 1,
                "kind": kind,
                "label": label,
                "in_cycle": (origin, target) in cycle_pairs,
                "finding_indexes": trail_findings.get((origin, target), []),
            }
        )

    for row in index.tables["bank_txns"]:
        origin = _text(row.get("from_clabe"))
        target = _text(row.get("to_clabe"))
        if origin and target:
            add_edge(
                index.clabe_owner(origin),
                index.clabe_owner(target),
                index.row_amount("bank_txns", row),
                "payment",
            )

    for owners in index.clabe_owners.values():
        for first, second in itertools.pairwise(owners):
            add_edge(first, second, None, "relation", "Misma CLABE")
    by_address: dict[str, list[str]] = {}
    for row in index.tables["vendors"]:
        address = normalize(_text(row.get("address")))
        if address:
            by_address.setdefault(address, []).append(f"RFC:{_text(row.get('rfc')).upper()}")
    for owners in by_address.values():
        for first, second in itertools.pairwise(owners):
            add_edge(first, second, None, "relation", "Mismo domicilio")
    if index.company_id:
        for entity_id in node_ids:
            if index.entity(entity_id).kind == "employee":
                add_edge(index.company_id, entity_id, None, "relation", "Empleado")

    nodes = []
    for entity_id in node_ids:
        entity = entity_view(index, entity_id)
        nodes.append(
            GraphNode(
                id=entity_id,
                kind=entity.kind,
                name=entity.name,
                status=entity.status,
                finding_indexes=entity.finding_indexes,
                lead_index=entity.lead_index,
            )
        )
    return GraphData(
        scope=scope,
        nodes=nodes,
        edges=list(edges.values()),
        hidden_count=sum(1 for entity_id in entity_population(index) if entity_id not in node_ids),
    )


# ---------------------------------------------------------------------------
# Timeline
# ---------------------------------------------------------------------------


def _event(
    index: CaseIndex, table: SourceTable, row: dict[str, CellValue], label: str
) -> TimelineEvent | None:
    date = _text(row.get(DATE_FIELD[table]))
    if not date:
        return None
    return TimelineEvent(
        date=date,
        amount=index.row_amount(table, row),
        label=label,
        record=RecordRef(source_table=table, record_id=index.record_id(table, row)),
    )


def build_timeline(index: CaseIndex, entity_id: str) -> EntityTimeline | None:
    """Contracts, orders, invoices, payments and registration of one entity. None if unknown."""
    if entity_id not in index.entities and entity_id not in index.status:
        return None
    base = index.entity(entity_id)
    start, end = index.period

    def in_range(date: str) -> bool:
        return (not start or date >= start) and (not end or date <= end)

    lanes: list[TimelineLane] = []

    def lane(
        key: Literal["contracts", "purchase_orders", "invoices", "bank_txns"],
        label: str,
        events: list[TimelineEvent | None],
        empty_note: str | None = None,
    ) -> None:
        kept = sorted(
            (e for e in events if e is not None and in_range(e.date)), key=lambda e: e.date
        )
        lanes.append(
            TimelineLane(key=key, label=label, events=kept, note=None if kept else empty_note)
        )

    invoiced = paid = received = 0.0
    tables = index.tables

    if base.kind == "employee":
        emp_id = base.profile[1] if base.profile else ""
        names = {base.name}
        orders = [
            row
            for row in tables["purchase_orders"]
            if _text(row.get("approver")) in names or _text(row.get("requester")) in names
        ]
        clabe = base.bank_clabe or ""
        txns = [
            row
            for row in tables["bank_txns"]
            if clabe and clabe in (_text(row.get("from_clabe")), _text(row.get("to_clabe")))
        ]
        lane(
            "purchase_orders",
            "Purchase orders requested or approved",
            [
                _event(
                    index, "purchase_orders", row, f"{row.get('po_id')} · {row.get('vendor_rfc')}"
                )
                for row in orders
            ],
            "did not request or approve purchase orders",
        )
        lane(
            "bank_txns",
            "Payments to their CLABE",
            [_event(index, "bank_txns", row, f"{row.get('txn_id')}") for row in txns],
            "no movements to their account",
        )
        employee = index.row("employees", emp_id) if emp_id else None
        hire = _text(employee.get("hire_date")) if employee else ""
        registration = TimelineLane(key="registration", label="Registration", events=[])
        if hire and in_range(hire):
            registration.events.append(
                TimelineEvent(
                    date=hire,
                    amount=None,
                    label="Hired",
                    record=RecordRef(source_table="employees", record_id=emp_id),
                )
            )
        elif hire:
            registration.note = f"hired on {hire} (before the audited period)"
        lanes.append(registration)
        paid = sum(
            index.row_amount("bank_txns", row) or 0.0
            for row in txns
            if _text(row.get("to_clabe")) == clabe
        )
    elif entity_id.startswith("RFC:"):
        rfc = entity_id[4:]
        is_company = base.is_audited_company
        invoices = [
            row
            for row in tables["invoices"]
            if rfc in (_text(row.get("issuer_rfc")).upper(), _text(row.get("receiver_rfc")).upper())
        ]
        clabes = set(index.company_clabes) if is_company else {base.bank_clabe or ""} - {""}
        txns = [
            row
            for row in tables["bank_txns"]
            if clabes & {_text(row.get("from_clabe")), _text(row.get("to_clabe"))}
        ]
        if not is_company:
            lane(
                "contracts",
                "Contracts",
                [
                    _event(index, "contracts", index.rows["contracts"][cid], f"Contract {cid}")
                    for cid in index.by_vendor.get(("contracts", rfc), [])
                ],
                "no contract",
            )
            lane(
                "purchase_orders",
                "OC",
                [
                    _event(
                        index,
                        "purchase_orders",
                        index.rows["purchase_orders"][po],
                        f"{po} · approved by "
                        f"{index.rows['purchase_orders'][po].get('approver') or '—'}",
                    )
                    for po in index.by_vendor.get(("purchase_orders", rfc), [])
                ],
                "no purchase order",
            )
            lane(
                "invoices",
                "Invoices",
                [
                    _event(
                        index,
                        "invoices",
                        row,
                        f"{row.get('uuid')}"
                        + (" · sale" if _text(row.get("issuer_rfc")) == index.company_rfc else "")
                        + (" · cancelled" if row.get("status") == "cancelado" else ""),
                    )
                    for row in invoices
                ],
            )
        lane(
            "bank_txns",
            "Payments",
            [
                _event(
                    index,
                    "bank_txns",
                    row,
                    f"{row.get('txn_id')} · {_direction(index, row, clabes)}",
                )
                for row in txns
            ],
            "no bank movements",
        )
        if not is_company:
            registration = TimelineLane(key="registration", label="RFC registration", events=[])
            outside: list[str] = []
            vendor = index.row("vendors", rfc)
            efos = index.row("efos_list", rfc)
            if vendor is not None:
                date = _text(vendor.get("registered_date"))
                if date and in_range(date):
                    registration.events.append(
                        TimelineEvent(
                            date=date,
                            amount=None,
                            label="Vendor registration",
                            record=RecordRef(
                                source_table="vendors", record_id=index.record_id("vendors", vendor)
                            ),
                        )
                    )
                elif date:
                    outside.append(f"registered on {date}")
            if efos is not None:
                date = _text(efos.get("publication_date"))
                label = f"Article 69-B list: {efos.get('status') or 'no status'}"
                if date and in_range(date):
                    registration.events.append(
                        TimelineEvent(
                            date=date,
                            amount=None,
                            label=label,
                            record=RecordRef(
                                source_table="efos_list",
                                record_id=index.record_id("efos_list", efos),
                            ),
                        )
                    )
                elif date:
                    outside.append(
                        f"69-B {efos.get('status') or ''} since {date}".replace("  ", " ")
                    )
            if outside:
                registration.note = f"{' · '.join(outside)} (outside the audited period)"
            lanes.append(registration)
            invoiced = sum(
                index.row_amount("invoices", row) or 0.0
                for row in invoices
                if _text(row.get("issuer_rfc")).upper() == rfc and row.get("status") == "vigente"
            )
        paid = sum(
            index.row_amount("bank_txns", row) or 0.0
            for row in txns
            if _direction(index, row, clabes) == "receives"
        )
        received = sum(
            index.row_amount("bank_txns", row) or 0.0
            for row in txns
            if _direction(index, row, clabes) == "sends"
        )
        if is_company:
            paid, received = received, paid

    annotations = [
        annotation
        for extra in findings_extra(index)
        for annotation in extra.timeline_annotations
        if annotation.entity == entity_id
    ]
    profile = record_view(index, base.profile[0], base.profile[1]) if base.profile else None
    return EntityTimeline(
        entity_id=entity_id,
        entity=entity_view(index, entity_id),
        range=_period((start, end)),
        lanes=lanes,
        annotations=annotations,
        profile=profile,
        totals=TimelineTotals(
            invoiced=_round2(invoiced), paid=_round2(paid), received=_round2(received)
        ),
    )


def _direction(index: CaseIndex, row: dict[str, CellValue], clabes: set[str]) -> str:
    """From the entity's side: `receives` when money lands on one of its accounts, else `sends`."""
    return "receives" if _text(row.get("to_clabe")) in clabes else "sends"


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


def search(index: CaseIndex, query: str, events: list[RunEvent]) -> SearchResponse:
    """Entities by id or name, and exhibits by id or record id, with where they appear and why."""
    needle = normalize(query.strip())
    if not needle:
        return SearchResponse(query=query, hits=[])
    submission = index.analysis.submission
    findings, leads = submission.findings, submission.leads_not_pursued

    entity_hits: list[SearchHit] = []
    for entity_id in dict.fromkeys([*index.entities, *index.status]):
        base = index.entity(entity_id)
        if needle not in normalize(entity_id) and needle not in normalize(base.name):
            continue
        entity = entity_view(index, entity_id)
        lead = leads[entity.lead_index] if entity.lead_index is not None else None
        appears_in = [
            SearchLocation(
                kind="finding",
                finding_index=number,
                label=f"Hallazgo #{number + 1} · {_scheme_name(findings[number])}",
            )
            for number in entity.finding_indexes
        ]
        if lead is not None:
            appears_in.append(
                SearchLocation(
                    kind="lead",
                    lead_index=entity.lead_index,
                    label=f"Caso descartado · {lead.signal}",
                )
            )
        for number, finding in enumerate(findings):
            for exhibit in finding.exhibits:
                row = index.row(exhibit.source_table, exhibit.record_id)
                if row is not None and index.row_entity(exhibit.source_table, row) == entity_id:
                    appears_in.append(
                        SearchLocation(
                            kind="exhibit",
                            finding_index=number,
                            exhibit_id=exhibit.exhibit_id,
                            label=(
                                f"{exhibit.exhibit_id} · {TABLE_LABEL[exhibit.source_table]} "
                                f"{exhibit.record_id}"
                            ),
                        )
                    )
        entity_hits.append(
            SearchHit(
                kind="entity",
                id=entity_id,
                title=entity.name,
                subtitle=f"{entity_id} · {STATUS_LABEL[entity.status]}",
                status=entity.status,
                appears_in=appears_in,
                lead_reason=lead.reason if lead else None,
                closed_by=lead.closed_by if lead else None,
                log=[
                    event
                    for event in events
                    if entity_id in (event.entities or []) or event.entity == entity_id
                ][:SEARCH_LOG_LIMIT],
            )
        )
    entity_hits.sort(key=lambda hit: _STATUS_ORDER[hit.status or "clear"])

    exhibit_hits: list[SearchHit] = []
    for number, finding in enumerate(findings):
        for exhibit in finding.exhibits:
            if needle not in normalize(exhibit.exhibit_id) and needle not in normalize(
                exhibit.record_id
            ):
                continue
            row = index.row(exhibit.source_table, exhibit.record_id)
            owner = index.row_entity(exhibit.source_table, row) if row else None
            title = (
                f"{exhibit.exhibit_id} · {TABLE_LABEL[exhibit.source_table]} {exhibit.record_id}"
            )
            exhibit_hits.append(
                SearchHit(
                    kind="exhibit",
                    id=exhibit.exhibit_id,
                    title=title,
                    subtitle=exhibit.note,
                    status=index.entity_status(owner) if owner else None,
                    appears_in=[
                        SearchLocation(
                            kind="exhibit",
                            finding_index=number,
                            exhibit_id=exhibit.exhibit_id,
                            label=f"Hallazgo #{number + 1} · {_scheme_name(finding)}",
                        )
                    ],
                    log=[],
                )
            )
    return SearchResponse(query=query, hits=[*exhibit_hits, *entity_hits[:SEARCH_ENTITY_LIMIT]])


# ---------------------------------------------------------------------------
# Markdown export
# ---------------------------------------------------------------------------


def render_markdown(index: CaseIndex) -> str:
    """The case file as plain Markdown: header, summary, findings with exhibits, declined leads."""
    report = build_report(index)
    header, summary, submission = report.case_header, report.summary, report.submission
    names = {entity_id: entity.name for entity_id, entity in report.entities.items()}

    def who(entity_id: str) -> str:
        name = names.get(entity_id)
        return f"{name} ({entity_id})" if name and name != entity_id else entity_id

    lines = [
        f"# Forensic case file · {header.company_name}",
        "",
        f"RFC {header.company_rfc or 'not identified'} · Audited period "
        f"{header.audit_period.from_ or '?'} to {header.audit_period.to or '?'} "
        f"· Seed {submission.seed}",
        "",
        "## Summary",
        "",
        summary.headline,
        "",
        f"- Findings: {summary.findings_count} "
        f"({summary.findings_by_confidence['proven']} proven, "
        f"{summary.findings_by_confidence['probable']} probable)",
        f"- Total exposure: {_money(summary.total_exposure)} MXN",
        f"- Cleared cases: {summary.leads_closed_count}",
        "",
        "## Findings",
        "",
    ]
    if not submission.findings:
        lines += ["No findings.", ""]
    for number, finding in enumerate(submission.findings):
        extra = report.findings_extra[number].reconciliation
        lines += [
            f"### Finding #{number + 1} · {_scheme_name(finding)} ({finding.confidence})",
            "",
            f"**Entities:** {', '.join(who(e) for e in finding.entities)}",
            "",
            finding.narrative,
            "",
            f"**Rule breached:** {finding.rule_broken}",
            "",
            f"**Amount:** {_money(finding.peso_amount)} MXN (reconciles with {extra.table_used}: "
            f"{_money(extra.sum)}, difference {extra.diff_pct}%)",
            "",
        ]
        if finding.money_trail:
            lines += ["| Date | From | To | Amount | Exhibit |", "|---|---|---|---:|---|"]
            lines += [
                f"| {s.date} | {s.from_} | {s.to} | {_money(s.amount)} | {s.exhibit_id} |"
                for s in finding.money_trail
            ]
            lines.append("")
        lines += ["| Exhibit | Table | Record | Note |", "|---|---|---|---|"]
        lines += [
            f"| {e.exhibit_id} | {e.source_table} | {e.record_id} | {e.note.replace('|', '/')} |"
            for e in finding.exhibits
        ]
        lines.append("")
    lines += ["## Cleared cases", ""]
    if not submission.leads_not_pursued:
        lines += ["No cleared cases.", ""]
    for lead in submission.leads_not_pursued:
        lines += [
            f"- **{who(lead.entity)}** · {lead.signal} · closed by {lead.closed_by}: {lead.reason}"
        ]
    limits = report.method_and_limits
    lines += [
        "",
        "## Method and limits",
        "",
        limits.architecture,
        "",
        *[f"- {item}" for item in limits.out_of_scope + limits.cannot_detect],
        "",
        f"Reproduce: {limits.reproduce.command} · engine {limits.reproduce.version} · "
        f"dataset sha256 {limits.reproduce.dataset_sha256}",
        "",
    ]
    return "\n".join(lines)
