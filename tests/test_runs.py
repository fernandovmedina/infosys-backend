"""Dataset upload: zip / CSV ingestion, diagnostics and the /runs endpoints."""

from __future__ import annotations

import io
import uuid
import zipfile
from collections.abc import AsyncIterator
from pathlib import Path

import asyncpg
import pytest
from httpx import AsyncClient

from app.core.config import get_settings
from app.core.errors import UploadRejectedError
from app.runs.ingest import UploadedFile, ingest
from tests.conftest import requires_database

# Real seed produced by estate-generate, kept in the frontend repo next to this one.
SEED_ZIP = Path(__file__).resolve().parents[2] / "infosys" / "public" / "seed.zip"

TABLE_CSVS: dict[str, str] = {
    "vendors": (
        "rfc,legal_name,registered_date,address,bank_clabe,category,contact_email\n"
        "AAAA010101AA1,Uno SA,2025-01-15,Calle 1,000000000000000001,Consultoria,a@x.mx\n"
    ),
    "invoices": (
        "uuid,issuer_rfc,receiver_rfc,issue_date,subtotal,iva,total,concepto_text,"
        "uso_cfdi,forma_pago,metodo_pago,status\n"
        "INV-1,AAAA010101AA1,EMP920101AB1,2026-02-15,80000,12800,92800,Servicio,G03,03,PUE,vigente\n"
    ),
    "ledger": (
        "entry_id,date,account_code,account_name,debit,credit,description,invoice_uuid,"
        "cost_center,approver\n"
        "1,2026-02-15,5000,Gastos,92800,0,Registro,INV-1,CC-100,A. Ejemplo\n"
    ),
    "bank_txns": (
        "txn_id,date,from_clabe,to_clabe,amount,reference,channel\n"
        "BNK-1,2026-03-29,000000000000000099,000000000000000001,92800,Pago INV-1,SPEI\n"
    ),
    "purchase_orders": (
        "po_id,vendor_rfc,date,amount,requester,approver,description\n"
        "PO-1,AAAA010101AA1,2026-02-20,92800,C. Ejemplo,D. Ejemplo,Servicio\n"
    ),
    "contracts": (
        "contract_id,vendor_rfc,start_date,value,scope_text\n"
        "CTR-1,AAAA010101AA1,2024-07-01,556800,Contrato marco\n"
    ),
    "employees": (
        "emp_id,name,role,bank_clabe,hire_date\n"
        "EMP:0001,Persona Uno,Compras,000000000000000501,2021-03-01\n"
    ),
    "efos_list": (
        "rfc,legal_name,status,publication_date\nAAAA010101AA1,Uno SA,definitivo,2025-12-11\n"
    ),
}


def _csv(name: str, content: str | None = None) -> UploadedFile:
    return UploadedFile(f"{name}.csv", (content or TABLE_CSVS[name]).encode())


def _zip(entries: dict[str, str | bytes], filename: str = "estate.zip") -> UploadedFile:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as bundle:
        for path, content in entries.items():
            bundle.writestr(path, content)
    return UploadedFile(filename, buffer.getvalue())


def _statuses(files: list[UploadedFile]) -> dict[str, str]:
    return {d.name: d.status for d in ingest(files).diagnostics}


def _rejection(files: list[UploadedFile]) -> UploadRejectedError:
    with pytest.raises(UploadRejectedError) as info:
        ingest(files)
    return info.value


# ---------------------------------------------------------------------------
# Ingestion
# ---------------------------------------------------------------------------


def test_zip_with_folder_maps_every_table_and_skips_private() -> None:
    entries: dict[str, str | bytes] = {f"seed/{n}.csv": c for n, c in TABLE_CSVS.items()}
    entries["seed/private/seed.ground_truth.json"] = "{}"
    entries["__MACOSX/seed/._vendors.csv"] = b"\x00\x05"
    entries["seed/README.txt"] = "hola"

    dataset = ingest([_zip(entries)])

    assert dataset.format == "zip"
    assert not dataset.blocked
    assert [d.status for d in dataset.diagnostics] == ["ok"] * 8
    assert dataset.diagnostics[0].source_file == "seed/vendors.csv"
    assert {i.filename for i in dataset.ignored_files} == {
        "seed/private/seed.ground_truth.json",
        "seed/README.txt",
    }


def test_loose_csvs_map_by_name_and_hash_is_order_independent() -> None:
    files = [_csv(name) for name in TABLE_CSVS]

    dataset = ingest(files)

    assert dataset.format == "csv"
    assert dataset.filename == "8 archivos CSV"
    assert all(d.status == "ok" for d in dataset.diagnostics)
    assert ingest(list(reversed(files))).sha256 == dataset.sha256


def test_unknown_file_name_falls_back_to_header_columns() -> None:
    dataset = ingest([UploadedFile("export_2026.csv", TABLE_CSVS["invoices"].encode())])

    assert dataset.tables["invoices"].source_file == "export_2026.csv"


def test_aliases_semicolons_and_bom_are_understood() -> None:
    content = "\ufeff" + TABLE_CSVS["bank_txns"].replace(",", ";")
    dataset = ingest([UploadedFile("Bank-Transactions.csv", content.encode())])

    assert dataset.tables["bank_txns"].header[0] == "txn_id"
    assert len(dataset.tables["bank_txns"].rows) == 1


def test_missing_required_table_blocks_and_optional_warns() -> None:
    statuses = _statuses([_csv("invoices"), _csv("vendors")])

    assert statuses["invoices"] == "ok"
    assert statuses["bank_txns"] == "error"
    assert statuses["efos_list"] == "warning"


def test_missing_key_column_on_required_table_is_an_error() -> None:
    no_amount = "txn_id,date,from_clabe,to_clabe\nBNK-1,2026-03-29,1,2\n"

    assert _statuses([_csv("invoices"), _csv("bank_txns", no_amount)])["bank_txns"] == "error"


def test_bad_values_become_column_warnings() -> None:
    bad = TABLE_CSVS["invoices"] + (
        "INV-2,A,B,15/02/2026,x,0,mil,Servicio,G03,03,CONTADO,vigente\n"
    )
    dataset = ingest([_csv("invoices", bad), _csv("bank_txns")])

    columns = {w.column for w in dataset.column_warnings if w.table == "invoices"}
    assert columns == {"issue_date", "subtotal", "total", "metodo_pago"}
    assert dataset.diagnostics[1].status == "warning"


@pytest.mark.parametrize(
    ("files", "code"),
    [
        ([], "no_files"),
        ([UploadedFile("estate.xlsx", b"x")], "unsupported_format"),
        ([_zip({"a.csv": "x"}), _csv("invoices")], "mixed_formats"),
        ([_zip({"a.csv": "x"}), _zip({"b.csv": "x"}, "b.zip")], "multiple_archives"),
        ([UploadedFile("estate.zip", b"not a zip")], "invalid_archive"),
        ([UploadedFile("notes.csv", b"foo,bar\n1,2\n")], "no_tables_found"),
        ([_csv("invoices"), UploadedFile("facturas.csv", b"uuid\n")], "duplicate_table"),
        ([UploadedFile("invoices.csv", b"\x00\x01binary")], "invalid_csv"),
    ],
)
def test_unusable_uploads_are_rejected(files: list[UploadedFile], code: str) -> None:
    assert _rejection(files).code == code


@pytest.mark.skipif(not SEED_ZIP.exists(), reason="seed.zip not found next to the backend")
def test_real_seed_zip_is_clean() -> None:
    dataset = ingest([UploadedFile(SEED_ZIP.name, SEED_ZIP.read_bytes())])

    assert not dataset.blocked
    assert all(d.status == "ok" for d in dataset.diagnostics), dataset.diagnostics
    assert all("private/" in i.filename for i in dataset.ignored_files)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@pytest.fixture
async def signed_in(
    client: AsyncClient, pool: asyncpg.Pool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[AsyncClient]:
    monkeypatch.setattr(get_settings(), "runs_storage_dir", str(tmp_path))
    email = f"runs-{uuid.uuid4().hex[:10]}@example.com"
    response = await client.post(
        "/api/v1/auth/register",
        json={"name": "Runs Test", "email": email, "password": "password123"},
    )
    assert response.status_code == 201
    try:
        yield client
    finally:
        await pool.execute("DELETE FROM app_user WHERE email_normalized = $1", email)


@requires_database
async def test_upload_zip_then_read_validation_and_history(
    signed_in: AsyncClient, tmp_path: Path
) -> None:
    archive = _zip({f"seed/{n}.csv": c for n, c in TABLE_CSVS.items()})

    created = await signed_in.post(
        "/api/v1/runs", files=[("files", (archive.filename, archive.data, "application/zip"))]
    )
    assert created.status_code == 201, created.text
    run_id = created.json()["run_id"]
    assert created.json()["status"] == "ready"
    assert (tmp_path / run_id / "tables" / "invoices.csv").exists()

    validation = (await signed_in.get(f"/api/v1/runs/{run_id}/validation")).json()
    assert validation["format"] == "zip"
    assert [t["name"] for t in validation["tables"]][:2] == ["vendors", "invoices"]
    assert all(t["status"] == "ok" for t in validation["tables"])

    state = (await signed_in.get(f"/api/v1/runs/{run_id}")).json()
    assert state["status"] == "ready"
    history = (await signed_in.get("/api/v1/runs")).json()
    assert history[0]["run_id"] == run_id

    started = await signed_in.post(f"/api/v1/runs/{run_id}/start")
    assert started.status_code == 501
    assert started.json()["error"]["code"] == "investigation_unavailable"


@requires_database
async def test_upload_multiple_csvs_with_blocking_diagnostics(signed_in: AsyncClient) -> None:
    files = [
        ("files", (f.filename, f.data, "text/csv")) for f in (_csv("invoices"), _csv("vendors"))
    ]

    created = await signed_in.post("/api/v1/runs", files=files)
    assert created.status_code == 201, created.text
    run_id = created.json()["run_id"]

    validation = (await signed_in.get(f"/api/v1/runs/{run_id}/validation")).json()
    bank = next(t for t in validation["tables"] if t["name"] == "bank_txns")
    assert bank["missing"] is True
    assert bank["status"] == "error"

    started = await signed_in.post(f"/api/v1/runs/{run_id}/start")
    assert started.status_code == 409
    assert started.json()["error"]["code"] == "validation_blocked"


@requires_database
async def test_rejected_upload_uses_error_envelope(signed_in: AsyncClient) -> None:
    response = await signed_in.post(
        "/api/v1/runs", files=[("files", ("estate.xlsx", b"x", "application/octet-stream"))]
    )

    assert response.status_code == 415
    assert response.json()["error"]["code"] == "unsupported_format"
    assert (await signed_in.post("/api/v1/runs")).json()["error"]["code"] == "no_files"


@requires_database
async def test_runs_require_auth_and_are_private(client: AsyncClient) -> None:
    response = await client.get("/api/v1/runs")
    assert response.status_code == 401

    assert (await client.get("/api/v1/runs/run_missing")).status_code == 401


async def _upload_zip(client: AsyncClient) -> str:
    archive = _zip({f"seed/{n}.csv": c for n, c in TABLE_CSVS.items()})
    response = await client.post(
        "/api/v1/runs", files=[("files", (archive.filename, archive.data, "application/zip"))]
    )
    assert response.status_code == 201, response.text
    return str(response.json()["run_id"])


@requires_database
async def test_delete_run_removes_row_and_dataset(signed_in: AsyncClient, tmp_path: Path) -> None:
    run_id = await _upload_zip(signed_in)

    response = await signed_in.delete(f"/api/v1/runs/{run_id}")

    assert response.status_code == 204
    assert not (tmp_path / run_id).exists()
    assert (await signed_in.get(f"/api/v1/runs/{run_id}")).status_code == 404
    missing = await signed_in.delete(f"/api/v1/runs/{run_id}")
    assert missing.json()["error"]["code"] == "run_not_found"


@requires_database
async def test_running_run_cannot_be_deleted_and_survives_clear(
    signed_in: AsyncClient, pool: asyncpg.Pool
) -> None:
    running = await _upload_zip(signed_in)
    await _upload_zip(signed_in)
    await _upload_zip(signed_in)
    await pool.execute("UPDATE investigation_run SET status = 'running' WHERE id = $1", running)

    blocked = await signed_in.delete(f"/api/v1/runs/{running}")
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "invalid_state"

    cleared = await signed_in.delete("/api/v1/runs")
    assert cleared.json() == {"deleted": 2}
    assert [r["run_id"] for r in (await signed_in.get("/api/v1/runs")).json()] == [running]
