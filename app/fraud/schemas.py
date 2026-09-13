"""Request/response models for the fraud-detection endpoints.

`Submission` and its parts replicate the challenge's `submission_schema.json`
(ported from motor-agente-forense `src/api/modelos.py`); their field names are
the official ones and must not change. The envelope around it (`FraudAnalysis`)
follows this API's English snake_case convention.

Values produced by the engine keep its vocabulary: `severity` is
`alta | media | baja` and `self_sufficiency` is `autosuficiente | presuntiva`,
exactly as the rule catalog (`spec_reglas_deteccion_fraude.md`) defines them.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.runs.estate import SourceTable

type SchemeType = Literal[
    "phantom_vendor", "kickback", "round_tripping", "threshold_splitting", "revenue_inflation"
]
type Severity = Literal["alta", "media", "baja"]
type SelfSufficiency = Literal["autosuficiente", "presuntiva"]


# ---------------------------------------------------------------------------
# Official submission contract
# ---------------------------------------------------------------------------


class Exhibit(BaseModel):
    exhibit_id: str
    source_table: SourceTable
    record_id: str
    note: str


class MoneyTrailStep(BaseModel):
    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)

    from_: str = Field(alias="from")
    to: str
    amount: float
    date: str
    exhibit_id: str


class Finding(BaseModel):
    scheme_type: SchemeType
    entities: list[str] = Field(description="Prefixed ids: RFC:..., EMP:...")
    narrative: str
    rule_broken: str
    peso_amount: float
    money_trail: list[MoneyTrailStep] = []
    exhibits: list[Exhibit]
    confidence: Literal["proven", "probable"]


class LeadNotPursued(BaseModel):
    entity: str
    signal: str
    reason: str
    tool_calls_made: list[str] = []
    closed_by: Literal["investigator", "challenger", "validator"] = "investigator"


class RunMetadata(BaseModel):
    llm_calls: int
    mxn_cost: float
    wall_clock_seconds: float
    cost_by_role: dict[str, float] = {}
    deterministic: bool = True


class Submission(BaseModel):
    seed: int
    findings: list[Finding]
    leads_not_pursued: list[LeadNotPursued]
    run_metadata: RunMetadata


# ---------------------------------------------------------------------------
# Analysis envelope
# ---------------------------------------------------------------------------


class Signal(BaseModel):
    """One row a detector returned: the auditable evidence behind findings and leads."""

    rule_id: str
    scheme_type: SchemeType | None = Field(
        description="Scheme the rule is evidence of; null for data-quality rules."
    )
    evidence_family: str | None
    source_table: SourceTable
    entity_id: str | None
    evidence_id: str | None = Field(description="Primary key of the cited row in source_table.")
    detected_on: str | None
    severity: Severity
    self_sufficiency: SelfSufficiency
    amount: float | None
    context: dict[str, Any] | None = Field(
        description="Rule-specific extra columns (thresholds, related ids, ...)."
    )


class RuleFailure(BaseModel):
    rule: str
    status: Literal["error"] = "error"
    error: str


class FraudAnalysis(BaseModel):
    status: Literal["completed"] = "completed"
    engine_version: str
    seed: int
    rules_evaluated: int = Field(description="Detectors that ran and honored the signal contract.")
    rules_triggered: int = Field(description="Detectors that returned at least one signal.")
    findings_count: int
    total_exposure: float = Field(description="Sum of peso_amount over all findings (MXN).")
    submission: Submission
    signals: list[Signal]
    signals_per_rule: dict[str, int]
    data_quality: dict[str, int] = Field(
        description="Signals per data-integrity rule. Not accusations."
    )
    rule_failures: list[RuleFailure] = Field(
        description="Detectors that raised or broke the contract; the rest still ran."
    )
    warnings: list[str]
    rows_per_table: dict[str, int]
    case_file_html: str = Field(description="Self-contained case file (HTML, no network, no JS).")


class StartRunRequest(BaseModel):
    seed: int = Field(default=0, description="Run identifier copied to submission.seed.")


class RuleInfo(BaseModel):
    rule_id: str
    scheme_type: SchemeType | None
    evidence_family: str | None
    family_description: str | None
    data_quality: bool = Field(description="Data-integrity rule: reported apart, never accuses.")
    implemented: bool
    description: str | None = Field(description="The detector's docstring, when implemented.")


class FraudEngineHealth(BaseModel):
    status: Literal["ok", "degraded"]
    engine_version: str
    rules_loaded: int
    rule_load_errors: list[str]
