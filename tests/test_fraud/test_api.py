"""Fraud engine through this API: /fraud endpoints, run execution and persistence.

Adapted from motor-agente-forense `tests/test_api.py` (session cookie instead of
X-API-Key, project error envelope) plus the integration with investigation runs.
"""

from __future__ import annotations

import io
import json
import re
import uuid
import zipfile
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import asyncpg
import pandas as pd
import pytest
from httpx import AsyncClient

from app.core.config import get_settings
from app.core.errors import FraudEngineOutputInvalidError
from app.fraud import service
from app.fraud.engine import pipeline, runner
from app.fraud.engine.esquema import TABLES
from app.fraud.engine.ingesta import archivos_en_carpeta
from app.runs.ingest import UploadedFile, ingest, write_tables
from tests.conftest import requires_database
from tests.test_fraud.conftest import ESCENARIO_1301, RAIZ

ESPERADO = json.loads((RAIZ / "tests" / "fixtures" / "fraud" / "seed_1301.json").read_text())


def _without_clock(submission: dict[str, Any]) -> dict[str, Any]:
    copy = json.loads(json.dumps(submission))
    copy["run_metadata"].pop("wall_clock_seconds")
    return dict(copy)


def _files(**replacements: bytes | None) -> dict[str, tuple[str, bytes, str]]:
    files = {}
    for table in TABLES:
        content = replacements.get(table, (ESCENARIO_1301 / f"{table}.csv").read_bytes())
        if content is not None:
            files[table] = (f"{table}.csv", content, "text/csv")
    return files


def _without_timing(case_file_html: str) -> str:
    """The case file shows wall-clock time, the only field that changes between runs."""
    return re.sub(r"<b>[\d.]+ s</b>", "<b>_ s</b>", case_file_html)


def _header_only(table: str) -> bytes:
    return (ESCENARIO_1301 / f"{table}.csv").read_bytes().splitlines(keepends=True)[0]


@pytest.fixture
async def signed_in(
    client: AsyncClient, pool: asyncpg.Pool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[AsyncClient]:
    monkeypatch.setattr(get_settings(), "runs_storage_dir", str(tmp_path))
    email = f"fraud-{uuid.uuid4().hex[:10]}@example.com"
    response = await client.post(
        "/api/v1/auth/register",
        json={"name": "Fraud Test", "email": email, "password": "password123"},
    )
    assert response.status_code == 201
    try:
        yield client
    finally:
        await pool.execute("DELETE FROM app_user WHERE email_normalized = $1", email)


# ---------------------------------------------------------------------------
# Engine service (no database)
# ---------------------------------------------------------------------------


def test_analysis_matches_reference_and_explains_signals() -> None:
    analysis = service.analyze_files(
        archivos_en_carpeta(ESCENARIO_1301), seed=1301, max_rows=1_000_000
    )

    assert _without_clock(analysis.submission.model_dump(mode="json")) == ESPERADO
    assert analysis.rules_evaluated == 24
    assert analysis.rules_triggered == sum(1 for n in analysis.signals_per_rule.values() if n)
    assert len(analysis.signals) == sum(analysis.signals_per_rule.values())
    assert analysis.total_exposure == round(sum(f["peso_amount"] for f in ESPERADO["findings"]), 2)
    assert analysis.rule_failures == [] and analysis.warnings == []
    assert all(s.evidence_id for s in analysis.signals)
    efos = next(s for s in analysis.signals if s.rule_id == "EFOS_DIRECT_MATCH")
    assert efos.scheme_type == "phantom_vendor"
    assert efos.context == {"efos_status": "definitivo", "efos_publication_date": "2026-01-01"}


def test_run_tables_give_the_same_result_as_strict_ingestion(tmp_path: Path) -> None:
    dataset = ingest([UploadedFile(p.name, p.read_bytes()) for p in ESCENARIO_1301.glob("*.csv")])
    write_tables(dataset, tmp_path)

    from_run = service.analyze_run_tables(tmp_path, seed=1301)
    strict = service.analyze_files(
        archivos_en_carpeta(ESCENARIO_1301), seed=1301, max_rows=1_000_000
    )

    assert _without_clock(from_run.submission.model_dump(mode="json")) == ESPERADO
    assert from_run.signals == strict.signals
    assert _without_timing(from_run.case_file_html) == _without_timing(strict.case_file_html)


def test_run_tables_tolerate_missing_tables_and_columns(tmp_path: Path) -> None:
    for table in ("invoices", "bank_txns"):
        lines = (ESCENARIO_1301 / f"{table}.csv").read_text().splitlines()
        (tmp_path / f"{table}.csv").write_text("\n".join(lines) + "\n")
    # A missing non-key column and an unparseable number degrade to NULL.
    vendors = (ESCENARIO_1301 / "vendors.csv").read_text().splitlines()
    header = vendors[0].split(",")
    keep = [i for i, c in enumerate(header) if c != "contact_email"]
    (tmp_path / "vendors.csv").write_text(
        "\n".join(",".join(r.split(",")[i] for i in keep) for r in vendors[:5]) + "\n"
    )

    analysis = service.analyze_run_tables(tmp_path, seed=7)

    assert analysis.rows_per_table["ledger"] == 0
    assert analysis.rows_per_table["vendors"] == 4
    assert analysis.submission.seed == 7


def test_broken_rule_is_reported_and_the_rest_still_run(monkeypatch: pytest.MonkeyPatch) -> None:
    def rule_broken(con: Any) -> pd.DataFrame:
        raise RuntimeError("boom")

    monkeypatch.setattr(runner, "RULES", [*runner.RULES, rule_broken])

    analysis = service.analyze_files(
        archivos_en_carpeta(ESCENARIO_1301), seed=1301, max_rows=1_000_000
    )

    assert [f.model_dump() for f in analysis.rule_failures] == [
        {"rule": "rule_broken", "status": "error", "error": "RuntimeError: boom"}
    ]
    assert analysis.warnings == ["El detector rule_broken falló y se omitió: RuntimeError: boom"]
    assert analysis.rules_evaluated == 24
    assert _without_clock(analysis.submission.model_dump(mode="json")) == ESPERADO


def test_output_failing_the_official_validator_is_withheld(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pipeline, "validar", lambda con, sub: (False, ["finding[0]: bad"]))

    with pytest.raises(FraudEngineOutputInvalidError) as exc:
        service.analyze_files(archivos_en_carpeta(ESCENARIO_1301), seed=1, max_rows=1_000_000)

    assert exc.value.details == ["finding[0]: bad"]


def test_rule_catalog_and_health() -> None:
    health = service.engine_health()
    catalog = {r.rule_id: r for r in service.rule_catalog()}

    assert health.status == "ok" and health.rules_loaded == 24
    assert sum(r.implemented for r in catalog.values()) == health.rules_loaded
    assert catalog["BANK_TXN_NOT_IN_LEDGER"].scheme_type == "round_tripping"
    assert catalog["MALFORMED_RFC"].data_quality and catalog["MALFORMED_RFC"].scheme_type is None
    assert not catalog["PO_NEAR_THRESHOLD"].implemented
    assert all(r.description for r in catalog.values() if r.implemented)


# ---------------------------------------------------------------------------
# POST /fraud/analyze
# ---------------------------------------------------------------------------


@requires_database
async def test_analyze_endpoint_runs_the_full_engine(signed_in: AsyncClient) -> None:
    response = await signed_in.post("/api/v1/fraud/analyze", files=_files(), data={"seed": "1301"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert _without_clock(body["submission"]) == ESPERADO
    assert sorted(f["scheme_type"] for f in body["submission"]["findings"]) == [
        "kickback",
        "phantom_vendor",
        "revenue_inflation",
        "round_tripping",
        "threshold_splitting",
    ]
    assert body["status"] == "completed"
    assert body["rows_per_table"]["ledger"] == 1900
    assert "<html" in body["case_file_html"]
    assert body["findings_count"] == 5


@requires_database
async def test_analyze_empty_estate_accuses_nobody(signed_in: AsyncClient) -> None:
    files = _files(**{table: _header_only(table) for table in TABLES})

    response = await signed_in.post("/api/v1/fraud/analyze", files=files)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["submission"]["findings"] == []
    assert body["rules_triggered"] == 0 and body["signals"] == []


@requires_database
async def test_analyze_requires_a_session(client: AsyncClient) -> None:
    response = await client.post("/api/v1/fraud/analyze", files=_files())
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "not_authenticated"


@requires_database
async def test_analyze_missing_file(signed_in: AsyncClient) -> None:
    response = await signed_in.post("/api/v1/fraud/analyze", files=_files(contracts=None))

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "invalid_dataset"
    assert error["details"] == [
        {"file": "contracts.csv", "column": None, "message": "falta el archivo"}
    ]


@requires_database
async def test_analyze_without_any_file(signed_in: AsyncClient) -> None:
    response = await signed_in.post("/api/v1/fraud/analyze", data={"seed": "1"})

    assert response.status_code == 422
    assert len(response.json()["error"]["details"]) == len(TABLES)


@requires_database
async def test_analyze_renamed_column_and_bad_value(signed_in: AsyncClient) -> None:
    vendors = (ESCENARIO_1301 / "vendors.csv").read_bytes().replace(b"bank_clabe", b"clabe", 1)
    renamed = await signed_in.post("/api/v1/fraud/analyze", files=_files(vendors=vendors))
    assert renamed.status_code == 422
    assert {(e["file"], e["column"]) for e in renamed.json()["error"]["details"]} == {
        ("vendors.csv", "bank_clabe"),
        ("vendors.csv", "clabe"),
    }

    lines = (ESCENARIO_1301 / "bank_txns.csv").read_text().splitlines()
    lines[1] = lines[1].replace(lines[1].split(",")[4], "abc", 1)
    bad = await signed_in.post(
        "/api/v1/fraud/analyze", files=_files(bank_txns=("\n".join(lines) + "\n").encode())
    )
    assert bad.status_code == 422
    assert [(e["file"], e["column"]) for e in bad.json()["error"]["details"]] == [
        ("bank_txns.csv", "amount")
    ]


@requires_database
async def test_analyze_file_too_large(
    signed_in: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "fraud_max_bytes_per_file", 64 * 1024)

    response = await signed_in.post("/api/v1/fraud/analyze", files=_files())

    assert response.status_code == 413
    error = response.json()["error"]
    assert error["code"] == "file_too_large"
    assert error["details"]["file"].endswith(".csv")


@requires_database
async def test_rules_and_health_endpoints(client: AsyncClient) -> None:
    health = (await client.get("/api/v1/fraud/health")).json()
    rules = {r["rule_id"]: r for r in (await client.get("/api/v1/fraud/rules")).json()}

    assert health["status"] == "ok" and health["rules_loaded"] == 24
    assert rules["BANK_TXN_NOT_IN_LEDGER"]["implemented"]
    assert sum(r["implemented"] for r in rules.values()) == health["rules_loaded"]


# ---------------------------------------------------------------------------
# Investigation runs
# ---------------------------------------------------------------------------


async def _upload_seed(client: AsyncClient, tables: tuple[str, ...] = tuple(TABLES)) -> str:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for table in tables:
            archive.write(ESCENARIO_1301 / f"{table}.csv", f"seed1301/{table}.csv")
        archive.writestr("seed1301/private/answers.json", "{}")
    response = await client.post(
        "/api/v1/runs", files=[("files", ("seed1301.zip", buffer.getvalue(), "application/zip"))]
    )
    assert response.status_code == 201, response.text
    return str(response.json()["run_id"])


@requires_database
async def test_run_start_audits_the_dataset_and_stores_the_result(
    signed_in: AsyncClient, pool: asyncpg.Pool
) -> None:
    run_id = await _upload_seed(signed_in)
    early = await signed_in.get(f"/api/v1/runs/{run_id}/result")
    assert early.status_code == 409
    assert early.json()["error"]["code"] == "result_not_available"

    started = await signed_in.post(f"/api/v1/runs/{run_id}/start", json={"seed": 1301})
    assert started.status_code == 202, started.text

    state = (await signed_in.get(f"/api/v1/runs/{run_id}")).json()
    assert state["status"] == "completed", state
    assert state["started_at"] and state["finished_at"] and state["error"] is None

    result = (await signed_in.get(f"/api/v1/runs/{run_id}/result")).json()
    assert _without_clock(result["submission"]) == ESPERADO
    stored = await pool.fetchval("SELECT count(*) FROM fraud_signal WHERE run_id = $1", run_id)
    assert stored == len(result["signals"]) == sum(result["signals_per_rule"].values())

    again = await signed_in.post(f"/api/v1/runs/{run_id}/start")
    assert again.json()["error"]["code"] == "invalid_state"

    assert (await signed_in.delete(f"/api/v1/runs/{run_id}")).status_code == 204
    assert await pool.fetchval("SELECT count(*) FROM fraud_signal WHERE run_id = $1", run_id) == 0


@requires_database
async def test_run_with_only_required_tables_completes(signed_in: AsyncClient) -> None:
    run_id = await _upload_seed(signed_in, tables=("invoices", "bank_txns"))

    await signed_in.post(f"/api/v1/runs/{run_id}/start")

    assert (await signed_in.get(f"/api/v1/runs/{run_id}")).json()["status"] == "completed"
    result = (await signed_in.get(f"/api/v1/runs/{run_id}/result")).json()
    assert result["rows_per_table"]["vendors"] == 0
    assert result["rows_per_table"]["invoices"] > 0


@requires_database
async def test_failed_run_reports_the_error_and_can_be_retried(
    signed_in: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id = await _upload_seed(signed_in)

    def crash(directory: Path, *, seed: int) -> None:
        raise RuntimeError("disk gone")

    with monkeypatch.context() as patch:
        patch.setattr(service, "analyze_run_tables", crash)
        await signed_in.post(f"/api/v1/runs/{run_id}/start")

    state = (await signed_in.get(f"/api/v1/runs/{run_id}")).json()
    assert state["status"] == "failed"
    assert state["error"]["code"] == "investigation_failed"
    assert (await signed_in.get(f"/api/v1/runs/{run_id}/result")).status_code == 409

    retried = await signed_in.post(f"/api/v1/runs/{run_id}/start")
    assert retried.status_code == 202
    assert (await signed_in.get(f"/api/v1/runs/{run_id}")).json()["status"] == "completed"
