"""Response models of the interactive case file (report, drill-down, graph, search).

Field names mirror the frontend's `lib/runs/types.ts` (EXAMPLE.md §8-§10). The
TypeScript contract tells apart *optional* fields (`finished_at?: string`, left
out of the JSON when there is no value) from *nullable* ones (`lead_index:
number | null`, always present). Optional fields here use `omitted()`, so they
disappear from the response instead of arriving as `null`.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.fraud.schemas import Submission
from app.runs.estate import SourceTable
from app.runs.schemas import RunEvent, RunStatus, TableDiagnostic, Verdict, omitted

type EntityStatus = Literal["accused", "declined", "clear"]
type EntityKind = Literal["company", "vendor", "employee", "account", "unknown"]
type Confidence = Literal["proven", "probable"]
type ClosedBy = Literal["investigator", "challenger", "validator"]
type ExportFormat = Literal["html", "md"]
type GraphScope = Literal["flagged", "all"]
type TimelineLaneKey = Literal[
    "contracts", "purchase_orders", "invoices", "bank_txns", "registration"
]
type CellValue = str | int | float | None


# ---------------------------------------------------------------------------
# Entities and records
# ---------------------------------------------------------------------------


class Entity(BaseModel):
    kind: EntityKind
    name: str
    status: EntityStatus
    role: str | None = omitted()
    bank_clabe: str | None = omitted()
    is_audited_company: bool | None = omitted()
    signals: list[str] = Field(description="Ids of the engine rules that flagged the entity.")
    finding_indexes: list[int]
    lead_index: int | None


class EntityListItem(Entity):
    id: str


class RecordRef(BaseModel):
    source_table: SourceTable
    record_id: str


class Citation(BaseModel):
    finding_index: int
    exhibit_id: str


class RecordView(BaseModel):
    source_table: SourceTable
    record_id: str
    data: dict[str, CellValue]
    highlight_fields: list[str]
    cited_in: list[Citation]
    related: list[RecordRef]


class RecordRow(RecordView):
    entity: str | None
    risk: EntityStatus | None


class RecordPage(BaseModel):
    items: list[RecordRow]
    next_cursor: str | None
    total: int


class EntityPage(BaseModel):
    items: list[EntityListItem]
    next_cursor: str | None
    total: int


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


class ReconciliationLine(BaseModel):
    exhibit_id: str
    record_id: str
    amount: float


class OtherTableSum(BaseModel):
    table: SourceTable
    sum: float
    exhibit_ids: list[str]


class Reconciliation(BaseModel):
    table_used: SourceTable
    lines: list[ReconciliationLine]
    sum: float
    claimed: float
    diff: float
    diff_pct: float
    within_tolerance: bool
    other_tables: list[OtherTableSum]


class SharedEntity(BaseModel):
    entity: str
    other_finding_index: int


class TimelineAnnotation(BaseModel):
    date: str
    entity: str
    label: str


class FindingExtra(BaseModel):
    finding_index: int
    reconciliation: Reconciliation
    shared_entities: list[SharedEntity]
    timeline_annotations: list[TimelineAnnotation]


class DatasetInfo(BaseModel):
    filename: str
    sha256: str
    tables: list[TableDiagnostic]


class ReportRun(BaseModel):
    run_id: str
    status: RunStatus
    created_at: str
    finished_at: str | None = omitted()
    dataset: DatasetInfo


class AuditPeriod(BaseModel):
    from_: str = Field(alias="from", serialization_alias="from")
    to: str

    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)


class CaseHeader(BaseModel):
    company_name: str
    company_rfc: str
    audit_period: AuditPeriod


class ReportSummary(BaseModel):
    verdict: Verdict
    headline: str
    findings_count: int
    findings_by_confidence: dict[Confidence, int]
    total_exposure: float
    leads_closed_count: int
    entities_by_status: dict[EntityStatus, int]


class Reproduce(BaseModel):
    seed: int
    version: str
    dataset_sha256: str
    command: str


class MethodAndLimits(BaseModel):
    architecture: str
    out_of_scope: list[str]
    cannot_detect: list[str]
    reproduce: Reproduce


class Report(BaseModel):
    run: ReportRun
    case_header: CaseHeader
    summary: ReportSummary
    submission: Submission
    findings_extra: list[FindingExtra]
    entities: dict[str, Entity]
    records: dict[str, RecordView] = Field(description='Keyed by "<source_table>:<record_id>".')
    method_and_limits: MethodAndLimits


# ---------------------------------------------------------------------------
# Graph and timeline
# ---------------------------------------------------------------------------


class GraphNode(BaseModel):
    id: str
    kind: EntityKind
    name: str
    status: EntityStatus
    finding_indexes: list[int]
    lead_index: int | None


class GraphEdge(BaseModel):
    id: str
    from_: str = Field(alias="from", serialization_alias="from")
    to: str
    amount: float | None
    count: int
    kind: Literal["payment", "invoice", "relation"]
    label: str | None = omitted()
    in_cycle: bool
    finding_indexes: list[int]

    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)


class GraphData(BaseModel):
    scope: GraphScope
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    hidden_count: int


class TimelineEvent(BaseModel):
    date: str
    amount: float | None
    label: str
    record: RecordRef


class TimelineLane(BaseModel):
    key: TimelineLaneKey
    label: str
    events: list[TimelineEvent]
    note: str | None = omitted()


class TimelineTotals(BaseModel):
    invoiced: float
    paid: float
    received: float


class EntityTimeline(BaseModel):
    entity_id: str
    entity: Entity
    range: AuditPeriod
    lanes: list[TimelineLane]
    annotations: list[TimelineAnnotation]
    profile: RecordView | None = omitted()
    totals: TimelineTotals


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


class SearchLocation(BaseModel):
    kind: Literal["finding", "lead", "exhibit"]
    finding_index: int | None = omitted()
    lead_index: int | None = omitted()
    exhibit_id: str | None = omitted()
    label: str


class SearchHit(BaseModel):
    kind: Literal["entity", "exhibit"]
    id: str
    title: str
    subtitle: str
    status: EntityStatus | None
    appears_in: list[SearchLocation]
    lead_reason: str | None = omitted()
    closed_by: ClosedBy | None = omitted()
    log: list[RunEvent]


class SearchResponse(BaseModel):
    query: str
    hits: list[SearchHit]
