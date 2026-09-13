"""Fraud-analysis business logic: load an estate, run the engine, shape the result.

Everything here is synchronous (DuckDB and pandas block); the API calls it from a
worker thread. The engine itself (`app.fraud.engine`) is used as-is: this module
only chooses how the estate is loaded and translates `ResultadoAuditoria` into
the API's `FraudAnalysis`.

Logs carry sizes, counts and durations only -- never CSV content, RFCs or amounts.
"""

from __future__ import annotations

import json
import logging
import math
import time
from pathlib import Path
from typing import Any

import duckdb

from app.core.errors import FraudDatasetInvalidError, FraudEngineOutputInvalidError
from app.fraud.engine.catalogo import FAMILIA, FRASE_FAMILIA, REGLAS_INTEGRIDAD, RULE_TO_SCHEME
from app.fraud.engine.ingesta import IngestaInvalida, cargar_csvs
from app.fraud.engine.pipeline import ResultadoAuditoria, auditar_conexion
from app.fraud.engine.runner import cargar_reglas, nombre_regla
from app.fraud.loader import load_run_tables
from app.fraud.schemas import (
    FraudAnalysis,
    FraudEngineHealth,
    RuleFailure,
    RuleInfo,
    Signal,
    Submission,
)

logger = logging.getLogger(__name__)

# Version of the motor-agente-forense engine this port matches (src/api/app.py VERSION).
ENGINE_VERSION = "0.1.0"
# Estate name the case file prints; the reference API uses this same value.
_ESTATE_NAME = "carga_api"


def rule_id(rule: Any) -> str:
    """`rule_efos_direct_match` -> `EFOS_DIRECT_MATCH`, as the reference API reports it."""
    name = nombre_regla(rule)
    return name.removeprefix("rule_").upper() if name.startswith("rule_") else name


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------


def analyze_files(files: dict[str, Path], *, seed: int, max_rows: int) -> FraudAnalysis:
    """Strict path: validate the CSVs exactly like the reference engine, then audit them."""
    started = time.monotonic()
    with duckdb.connect() as con:
        try:
            rows = cargar_csvs(con, files, max_filas=max_rows)
        except IngestaInvalida as exc:
            logger.info("Fraud analysis rejected: %d ingestion errors", len(exc.errores))
            raise FraudDatasetInvalidError(
                details=[
                    {"file": e.archivo, "column": e.columna, "message": e.mensaje}
                    for e in exc.errores
                ]
            ) from exc
        return _audit(con, rows=rows, seed=seed, started=started, source="upload")


def analyze_run_tables(directory: Path, *, seed: int) -> FraudAnalysis:
    """Run path: load a diagnosed run's stored tables (see `loader`) and audit them."""
    started = time.monotonic()
    with duckdb.connect() as con:
        rows = load_run_tables(con, directory)
        return _audit(con, rows=rows, seed=seed, started=started, source="run")


def _audit(
    con: duckdb.DuckDBPyConnection,
    *,
    rows: dict[str, int],
    seed: int,
    started: float,
    source: str,
) -> FraudAnalysis:
    logger.info(
        "Fraud analysis started (%s): %d tables, %d rows", source, len(rows), sum(rows.values())
    )
    result = auditar_conexion(con, seed=seed, estate_nombre=_ESTATE_NAME)

    for name, error in result.fallos:
        logger.warning("Fraud rule %s failed and was skipped: %s", name, error)
    if not result.validacion_ok:
        logger.error(
            "Fraud analysis withheld: %d official validator errors",
            len(result.errores_validacion),
        )
        raise FraudEngineOutputInvalidError(details=result.errores_validacion)

    analysis = to_analysis(result, rows=rows, seed=seed)
    logger.info(
        "Fraud analysis completed (%s): %d rules run, %d triggered, %d failed, "
        "%d signals, %d findings, %d leads, %.2f s",
        source,
        analysis.rules_evaluated,
        analysis.rules_triggered,
        len(analysis.rule_failures),
        len(analysis.signals),
        analysis.findings_count,
        len(analysis.submission.leads_not_pursued),
        time.monotonic() - started,
    )
    return analysis


def to_analysis(result: ResultadoAuditoria, *, rows: dict[str, int], seed: int) -> FraudAnalysis:
    """Translate the engine's in-memory result into the API model."""
    assert result.case_file_html is not None  # set whenever validacion_ok
    submission = Submission.model_validate(result.submission)
    return FraudAnalysis(
        engine_version=ENGINE_VERSION,
        seed=seed,
        rules_evaluated=len(result.senales_por_regla),
        rules_triggered=sum(1 for n in result.senales_por_regla.values() if n > 0),
        findings_count=len(submission.findings),
        total_exposure=round(sum(f.peso_amount for f in submission.findings), 2),
        submission=submission,
        signals=signals_from_frame(result),
        signals_per_rule=result.senales_por_regla,
        data_quality=result.calidad,
        rule_failures=[RuleFailure(rule=name, error=error) for name, error in result.fallos],
        warnings=result.avisos,
        rows_per_table=rows,
        case_file_html=result.case_file_html,
    )


def _clean(value: Any) -> Any:
    return None if isinstance(value, float) and math.isnan(value) else value


def signals_from_frame(result: ResultadoAuditoria) -> list[Signal]:
    """The runner's signal frame as API models, in the order the rules produced them."""
    if result.signals is None or result.signals.empty:
        return []
    # to_json turns numpy scalars, NaN and timestamps into plain JSON values.
    records: list[dict[str, Any]] = json.loads(
        result.signals.to_json(orient="records", date_format="iso")
    )
    signals = []
    for record in records:
        rid = str(record["rule_id"])
        evidence = _clean(record["evidence_id"])
        amount = _clean(record["monto"])
        context = record["contexto"]
        signals.append(
            Signal(
                rule_id=rid,
                scheme_type=RULE_TO_SCHEME.get(rid),  # type: ignore[arg-type]
                evidence_family=FAMILIA.get(rid),
                source_table=record["source_table"],
                entity_id=None if record["entity_id"] is None else str(record["entity_id"]),
                evidence_id=None if evidence is None else str(evidence),
                detected_on=None
                if record["fecha_deteccion"] is None
                else str(record["fecha_deteccion"]),
                severity=record["severidad"],
                self_sufficiency=record["autosuficiencia"],
                amount=None if amount is None else float(amount),
                context=json.loads(context) if isinstance(context, str) else context,
            )
        )
    return signals


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------


def _loaded_rules() -> tuple[dict[str, Any], list[str]]:
    """({rule_id: rule function}, import errors)."""
    try:
        rules = cargar_reglas()
    except Exception as exc:  # a broken registry must not take the health check down
        return {}, [f"{type(exc).__name__}: {exc}"]
    return {rule_id(rule): rule for rule in rules}, []


def _description(rule: Any) -> str | None:
    doc = getattr(rule, "__doc__", None)
    if not doc:
        return None
    return " ".join(doc.strip().split("\n\n", 1)[0].split())


def rule_catalog() -> list[RuleInfo]:
    """Every rule the engine knows: the implemented detectors and the catalog's planned ones."""
    loaded, _ = _loaded_rules()
    ids = sorted(set(RULE_TO_SCHEME) | REGLAS_INTEGRIDAD | set(loaded))
    catalog = []
    for rid in ids:
        family = FAMILIA.get(rid)
        catalog.append(
            RuleInfo(
                rule_id=rid,
                scheme_type=RULE_TO_SCHEME.get(rid),  # type: ignore[arg-type]
                evidence_family=family,
                family_description=FRASE_FAMILIA.get(family) if family else None,
                data_quality=rid in REGLAS_INTEGRIDAD,
                implemented=rid in loaded,
                description=_description(loaded[rid]) if rid in loaded else None,
            )
        )
    return catalog


def engine_health() -> FraudEngineHealth:
    loaded, errors = _loaded_rules()
    return FraudEngineHealth(
        status="ok" if loaded and not errors else "degraded",
        engine_version=ENGINE_VERSION,
        rules_loaded=len(loaded),
        rule_load_errors=errors,
    )
