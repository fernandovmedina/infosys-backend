"""Fraud-detection API routes: analyze an estate, rule catalog and engine health.

Adapted from motor-agente-forense `src/api/app.py` (`POST /v1/auditorias`,
`GET /v1/reglas`, `GET /v1/salud`). Authentication is this API's session cookie
instead of the reference's `X-API-Key`, and errors use the project envelope.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, File, Form, UploadFile, status
from starlette.concurrency import run_in_threadpool

from app.api.dependencies import CurrentUserDependency, SettingsDependency
from app.core.errors import FraudDatasetInvalidError, UploadRejectedError
from app.fraud import service
from app.fraud.engine.esquema import TABLES
from app.fraud.schemas import FraudAnalysis, FraudEngineHealth, RuleInfo

router = APIRouter(prefix="/fraud", tags=["fraud"])

_READ_CHUNK_BYTES = 1024 * 1024

type OptionalCsv = Annotated[UploadFile | None, File()]


async def _save_upload(upload: UploadFile, destination: Path, max_bytes: int, table: str) -> None:
    """Stream one part to disk, refusing it as soon as it passes `max_bytes`."""
    written = 0
    with destination.open("wb") as handle:
        while chunk := await upload.read(_READ_CHUNK_BYTES):
            written += len(chunk)
            if written > max_bytes:
                raise UploadRejectedError(
                    "file_too_large",
                    f"{table}.csv supera el máximo de {max_bytes // (1024 * 1024)} MB.",
                    details={"file": f"{table}.csv", "max_bytes": max_bytes},
                    status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                )
            handle.write(chunk)


@router.post(
    "/analyze",
    response_model=FraudAnalysis,
    summary="Run the fraud engine over the eight estate CSVs",
    responses={
        413: {"description": "A CSV exceeds FRAUD_MAX_BYTES_PER_FILE (`file_too_large`)."},
        422: {"description": "A CSV is missing or does not match the schema (`invalid_dataset`)."},
        500: {"description": "The result failed the official validator (`engine_output_invalid`)."},
    },
)
async def analyze(
    _user: CurrentUserDependency,
    settings: SettingsDependency,
    vendors: OptionalCsv = None,
    invoices: OptionalCsv = None,
    ledger: OptionalCsv = None,
    bank_txns: OptionalCsv = None,
    purchase_orders: OptionalCsv = None,
    contracts: OptionalCsv = None,
    employees: OptionalCsv = None,
    efos_list: OptionalCsv = None,
    seed: Annotated[int, Form(description="Run identifier copied to submission.seed.")] = 0,
) -> FraudAnalysis:
    """Audit one company's estate synchronously and return findings with their evidence.

    Send one multipart file field per table (`vendors`, `invoices`, `ledger`,
    `bank_txns`, `purchase_orders`, `contracts`, `employees`, `efos_list`), each a
    UTF-8 CSV whose header has exactly the columns of `estate_schema.sql`. Every
    problem found is reported at once in `error.details` as `{file, column, message}`.
    Nothing is persisted: the CSVs live in a temporary directory and the estate in
    an in-memory DuckDB, both discarded when the request ends.
    """
    uploads = {
        "vendors": vendors,
        "invoices": invoices,
        "ledger": ledger,
        "bank_txns": bank_txns,
        "purchase_orders": purchase_orders,
        "contracts": contracts,
        "employees": employees,
        "efos_list": efos_list,
    }
    with tempfile.TemporaryDirectory(prefix="fraud_") as tmp:
        files: dict[str, Path] = {}
        for table in TABLES:
            upload = uploads[table]
            if upload is None:
                continue
            destination = Path(tmp) / f"{table}.csv"
            await _save_upload(upload, destination, settings.fraud_max_bytes_per_file, table)
            files[table] = destination
        if not files:
            raise FraudDatasetInvalidError(
                "No se recibió ningún CSV del estate.",
                details=[
                    {"file": f"{table}.csv", "column": None, "message": "falta el archivo"}
                    for table in TABLES
                ],
            )
        return await run_in_threadpool(
            service.analyze_files, files, seed=seed, max_rows=settings.fraud_max_rows_per_table
        )


@router.get("/rules", response_model=list[RuleInfo], summary="The fraud-rule catalog")
async def rules() -> list[RuleInfo]:
    return service.rule_catalog()


@router.get("/health", response_model=FraudEngineHealth, summary="Fraud engine status")
async def health() -> FraudEngineHealth:
    return service.engine_health()
