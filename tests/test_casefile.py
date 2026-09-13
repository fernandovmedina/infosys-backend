"""Interactive case file and investigation log: view models, events, endpoints and SSE.

The pure tests build a `CaseIndex` from the seed 1301 fixture without a database;
the endpoint tests upload the same estate, run it and read every case-file route.
"""

from __future__ import annotations

import datetime as dt
import io
import uuid
import zipfile
from collections.abc import AsyncIterator
from pathlib import Path

import asyncpg
import pytest
from httpx import AsyncClient

from app.casefile import views
from app.casefile.explainability import redacted_case_brief
from app.casefile.index import CaseIndex, RunInfo, build_index, split_trail_label
from app.core.config import get_settings
from app.fraud import service as fraud_service
from app.fraud.engine.esquema import TABLES
from app.fraud.schemas import Finding, LeadNotPursued, RunMetadata, Submission
from app.runs import events
from app.runs.service import verdict_of
from tests.conftest import requires_database
from tests.test_fraud.conftest import ESCENARIO_1301

SEED = 1301


@pytest.fixture(scope="module")
def index() -> CaseIndex:
    analysis = fraud_service.analyze_run_tables(ESCENARIO_1301, seed=SEED)
    run = RunInfo(
        run_id="run_test",
        filename="seed1301.zip",
        sha256="0" * 64,
        created_at=dt.datetime(2026, 9, 13, tzinfo=dt.UTC),
        finished_at=dt.datetime(2026, 9, 13, 0, 1, tzinfo=dt.UTC),
        tables=[
            {
                "name": table,
                "rows": 1,
                "status": "ok",
                "warnings": [],
                "source_file": f"{table}.csv",
                "missing": False,
            }
            for table in TABLES
        ],
    )
    return build_index(ESCENARIO_1301, run, analysis)


# ---------------------------------------------------------------------------
# View models (no database)
# ---------------------------------------------------------------------------


def test_report_restates_the_submission(index: CaseIndex) -> None:
    report = views.build_report(index)
    submission = index.analysis.submission

    assert report.submission == submission
    assert report.summary.findings_count == len(submission.findings) > 0
    assert report.summary.verdict == verdict_of(submission)
    assert report.summary.total_exposure == index.analysis.total_exposure
    assert report.case_header.company_rfc == index.company_rfc
    for finding, extra in zip(submission.findings, report.findings_extra, strict=True):
        # The official validator already accepted every peso_amount.
        assert extra.reconciliation.within_tolerance, extra.reconciliation
        for entity_id in finding.entities:
            assert report.entities[entity_id].status == "accused"
        for exhibit in finding.exhibits:
            record = report.records[f"{exhibit.source_table}:{exhibit.record_id}"]
            assert any(c.exhibit_id == exhibit.exhibit_id for c in record.cited_in)


def test_optional_fields_are_omitted_and_nullable_ones_kept(index: CaseIndex) -> None:
    data = views.build_report(index).model_dump(mode="json")
    entity = next(e for e in data["entities"].values() if not e.get("is_audited_company"))

    assert "lead_index" in entity  # `number | null`: always present
    assert "role" in entity or entity["kind"] != "employee"
    assert "is_audited_company" not in entity  # optional: left out when false
    assert set(data["case_header"]["audit_period"]) == {"from", "to"}


def test_records_filter_and_paginate(index: CaseIndex) -> None:
    first = views.records_page(index, table="invoices", limit=10)
    assert len(first.items) == 10 and first.total == len(index.tables["invoices"])
    second = views.records_page(index, table="invoices", limit=10, cursor=first.next_cursor)
    assert {i.record_id for i in first.items}.isdisjoint({i.record_id for i in second.items})

    cited = views.records_page(index, table="invoices", cited=True, limit=500)
    assert cited.total == len({k for k in index.cited_in if k.startswith("invoices:")})
    assert all(item.cited_in and item.highlight_fields for item in cited.items)

    accused = views.records_page(index, table="bank_txns", risk="accused", limit=500)
    assert all(item.risk == "accused" and item.entity for item in accused.items)


def test_entities_list_accused_first_without_the_company(index: CaseIndex) -> None:
    page = views.entities_page(index, status=None, limit=500, cursor=None)
    statuses = [item.status for item in page.items]
    assert statuses == sorted(statuses, key=["accused", "declined", "clear"].index)
    assert index.company_id not in {item.id for item in page.items}
    only_declined = views.entities_page(index, status="declined", limit=500, cursor=None)
    assert only_declined.total == sum(1 for s in statuses if s == "declined")

    counts = views.build_report(index).summary.entities_by_status
    assert sum(counts.values()) == page.total
    assert counts["accused"] == statuses.count("accused")


def test_graph_edges_join_existing_nodes_and_mark_trails(index: CaseIndex) -> None:
    for scope in ("flagged", "all"):
        graph = views.build_graph(index, scope)
        node_ids = {node.id for node in graph.nodes}
        assert all(edge.from_ in node_ids and edge.to in node_ids for edge in graph.edges)
    graph = views.build_graph(index, "flagged")
    trail_pairs = {
        (origin, target)
        for finding in index.analysis.submission.findings
        for step in finding.money_trail
        for origin in split_trail_label(step.from_)
        for target in split_trail_label(step.to)
    }
    marked = {(edge.from_, edge.to) for edge in graph.edges if edge.finding_indexes}
    assert marked and marked <= trail_pairs


def test_timelines_exist_for_every_flagged_entity(index: CaseIndex) -> None:
    for entity_id in index.status:
        timeline = views.build_timeline(index, entity_id)
        assert timeline is not None and timeline.entity.status == index.status[entity_id]
        assert timeline.entity_id == entity_id
        assert timeline.entity.name == index.entity(entity_id).name
        start, end = index.period
        for lane in timeline.lanes:
            assert all(start <= event.date <= end for event in lane.events)
    assert views.build_timeline(index, "RFC:NOEXISTE000") is None


def test_search_finds_exhibits_and_entities(index: CaseIndex) -> None:
    finding = index.analysis.submission.findings[0]
    exhibit = finding.exhibits[0]
    hits = views.search(index, exhibit.record_id, []).hits
    assert any(hit.kind == "exhibit" and hit.id == exhibit.exhibit_id for hit in hits)

    entity_id = finding.entities[0]
    entity_hit = next(h for h in views.search(index, entity_id, []).hits if h.id == entity_id)
    assert entity_hit.status == "accused"
    assert any(location.kind == "finding" for location in entity_hit.appears_in)
    assert views.search(index, "   ", []).hits == []


def test_markdown_export_lists_findings_and_leads(index: CaseIndex) -> None:
    markdown = views.render_markdown(index)
    submission = index.analysis.submission
    assert markdown.count("### Finding #") == len(submission.findings)
    assert all(lead.entity in markdown for lead in submission.leads_not_pursued)


def test_explanation_brief_contains_only_cited_records_and_masks_sensitive_fields(
    index: CaseIndex,
) -> None:
    brief = redacted_case_brief(index)
    assert brief["case_summary"]["findings_count"] == len(index.analysis.submission.findings)
    assert "private" not in str(brief).lower()
    cited = {
        f"{exhibit.source_table}:{exhibit.record_id}"
        for finding in index.analysis.submission.findings
        for exhibit in finding.exhibits
    }
    returned = {
        f"{record['source_table']}:{record['record_id']}"
        for finding in brief["findings"]
        for record in finding["cited_records"]
    }
    assert returned <= cited
    for finding in brief["findings"]:
        for record in finding["cited_records"]:
            assert record["fields"].get("bank_clabe") in (None, "[redacted]")


# ---------------------------------------------------------------------------
# Events and verdict (no database)
# ---------------------------------------------------------------------------


def test_analysis_events_follow_the_engine_output(index: CaseIndex) -> None:
    analysis = index.analysis
    names = events.EntityNames.load(ESCENARIO_1301)
    drafts = events.analysis_events(analysis, run_id="run_x", names=names)
    types = [draft.type for draft in drafts]

    assert types.count("detector_result") == len(analysis.signals_per_rule)
    assert types.count("finding_draft") == len(analysis.submission.findings)
    assert types.count("lead_closed") == len(analysis.submission.leads_not_pursued)
    assert types[-2:] == ["validation", "completed"]
    assert drafts[-1].as_payload()["report_url"] == "/api/v1/runs/run_x/report"
    finding_event = next(d for d in drafts if d.type == "finding_draft").as_payload()
    assert all(name != entity for entity, name in finding_event["entity_names"].items())

    failed = events.failed_event({"code": "boom", "message": "Falló", "details": None})
    assert failed.type == "failed" and failed.as_payload()["error"]["code"] == "boom"


def _submission(*confidences: str, leads: int = 0) -> Submission:
    finding = Finding.model_validate(
        {
            "scheme_type": "kickback",
            "entities": ["RFC:X"],
            "narrative": "n",
            "rule_broken": "r",
            "peso_amount": 1.0,
            "exhibits": [],
            "confidence": "proven",
        }
    )
    return Submission(
        seed=0,
        findings=[finding.model_copy(update={"confidence": c}) for c in confidences],
        leads_not_pursued=[LeadNotPursued(entity="RFC:Y", signal="s", reason="r")] * leads,
        run_metadata=RunMetadata(llm_calls=0, mxn_cost=0, wall_clock_seconds=0),
    )


def test_verdict() -> None:
    assert verdict_of(_submission("probable", "proven")) == "fraud_proven"
    assert verdict_of(_submission("probable")) == "fraud_probable"
    assert verdict_of(_submission(leads=2)) == "clean_with_leads"
    assert verdict_of(_submission()) == "clean"


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@pytest.fixture
async def signed_in(
    client: AsyncClient, pool: asyncpg.Pool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[AsyncClient]:
    monkeypatch.setattr(get_settings(), "runs_storage_dir", str(tmp_path))
    email = f"casefile-{uuid.uuid4().hex[:10]}@example.com"
    response = await client.post(
        "/api/v1/auth/register",
        json={"name": "Case File Test", "email": email, "password": "password123"},
    )
    assert response.status_code == 201
    try:
        yield client
    finally:
        await pool.execute("DELETE FROM app_user WHERE email_normalized = $1", email)


async def _completed_run(client: AsyncClient) -> str:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for table in TABLES:
            archive.write(ESCENARIO_1301 / f"{table}.csv", f"seed1301/{table}.csv")
    upload = await client.post(
        "/api/v1/runs", files=[("files", ("seed1301.zip", buffer.getvalue(), "application/zip"))]
    )
    assert upload.status_code == 201, upload.text
    run_id = str(upload.json()["run_id"])

    early = await client.get(f"/api/v1/runs/{run_id}/report")
    assert early.status_code == 409 and early.json()["error"]["code"] == "result_not_available"
    assert (await client.get(f"/api/v1/runs/{run_id}/log")).json() == []

    started = await client.post(f"/api/v1/runs/{run_id}/start", json={"seed": SEED})
    assert started.status_code == 202, started.text
    # The background task has finished by the time the next request is served.
    return run_id


def _frames(body: str) -> list[dict[str, str]]:
    frames = []
    for block in body.strip().split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
        if "event" in fields:
            frames.append(fields)
    return frames


@requires_database
async def test_log_and_event_stream(signed_in: AsyncClient, pool: asyncpg.Pool) -> None:
    run_id = await _completed_run(signed_in)

    log = (await signed_in.get(f"/api/v1/runs/{run_id}/log")).json()
    assert [event["seq"] for event in log] == list(range(1, len(log) + 1))
    assert log[0]["type"] == "step" and log[-1]["type"] == "completed"
    assert all(event["counters"]["llm_calls"] == 0 for event in log)

    state = (await signed_in.get(f"/api/v1/runs/{run_id}")).json()
    assert state["last_seq"] == len(log) and state["counters"]["elapsed_seconds"] >= 0

    detectors = (await signed_in.get(f"/api/v1/runs/{run_id}/log?role=detector")).json()
    assert detectors and {event["role"] for event in detectors} == {"detector"}
    lead = next(event for event in log if event["type"] == "lead_closed")
    by_entity = (await signed_in.get(f"/api/v1/runs/{run_id}/log?entity={lead['entity']}")).json()
    assert lead in by_entity

    stream = await signed_in.get(f"/api/v1/runs/{run_id}/events")
    assert stream.headers["content-type"].startswith("text/event-stream")
    frames = _frames(stream.text)
    assert len(frames) == len(log) and frames[-1]["event"] == "completed"
    resumed = _frames(
        (await signed_in.get(f"/api/v1/runs/{run_id}/events", headers={"Last-Event-ID": "3"})).text
    )
    assert resumed[0]["id"] == "4" and len(resumed) == len(log) - 3

    # A retry starts a new log.
    await pool.execute("UPDATE investigation_run SET status = 'failed' WHERE id = $1", run_id)
    assert (await signed_in.post(f"/api/v1/runs/{run_id}/start")).status_code == 202
    retried = (await signed_in.get(f"/api/v1/runs/{run_id}/log")).json()
    assert retried[0]["seq"] == 1 and len(retried) == len(log)


@requires_database
async def test_case_file_endpoints(signed_in: AsyncClient, client: AsyncClient) -> None:
    run_id = await _completed_run(signed_in)
    base = f"/api/v1/runs/{run_id}"

    report = (await signed_in.get(f"{base}/report")).json()
    assert report["run"]["run_id"] == run_id and report["summary"]["findings_count"] > 0
    finding = report["submission"]["findings"][0]
    exhibit = finding["exhibits"][0]

    records = await signed_in.get(f"{base}/records?table={exhibit['source_table']}&cited=true")
    assert records.status_code == 200 and records.json()["total"] >= 1
    record = await signed_in.get(f"{base}/records/{exhibit['source_table']}/{exhibit['record_id']}")
    assert record.json()["cited_in"]
    missing = await signed_in.get(f"{base}/records/invoices/NOEXISTE")
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "record_not_found"
    bad_table = await signed_in.get(f"{base}/records?table=nope")
    assert bad_table.status_code == 422

    entities = (await signed_in.get(f"{base}/entities?status=accused&limit=2")).json()
    assert entities["items"][0]["status"] == "accused" and entities["total"] >= 1
    timeline = await signed_in.get(f"{base}/entities/{finding['entities'][0]}/timeline")
    assert timeline.status_code == 200 and timeline.json()["lanes"]
    unknown = await signed_in.get(f"{base}/entities/RFC:NOEXISTE/timeline")
    assert unknown.json()["error"]["code"] == "entity_not_found"

    graph = (await signed_in.get(f"{base}/graph?scope=all")).json()
    assert graph["scope"] == "all" and graph["nodes"]
    hits = (await signed_in.get(f"{base}/search?q={exhibit['record_id']}")).json()["hits"]
    assert any(hit["kind"] == "exhibit" for hit in hits)

    html = await signed_in.get(f"{base}/export?format=html")
    assert html.headers["content-type"].startswith("text/html") and "<html" in html.text
    markdown = await signed_in.get(f"{base}/export?format=md")
    assert markdown.text.startswith("# Case file forense")
    submission = await signed_in.get(f"{base}/submission")
    assert "attachment" in submission.headers["content-disposition"]
    assert submission.json() == report["submission"]

    history = (await signed_in.get("/api/v1/runs")).json()
    row = next(run for run in history if run["run_id"] == run_id)
    assert row["verdict"] == report["summary"]["verdict"]
    assert row["findings_count"] == report["summary"]["findings_count"]

    await signed_in.post("/api/v1/auth/logout")
    assert (await client.get(f"{base}/report")).status_code == 401
