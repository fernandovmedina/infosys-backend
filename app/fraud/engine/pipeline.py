"""
Pipeline del agente forense: estate DuckDB -> Signals -> Findings / pistas ->
submission validado -> case file HTML.

`auditar_conexion` es la entrada como librería: recibe una conexión con las 8
tablas cargadas y devuelve el resultado en memoria, sin escribir a disco ni
imprimir.

Portado de motor-agente-forense `src/agente/pipeline.py`. Cambios: se quitó la
CLI (`auditar`/`main`, que leía un archivo DuckDB y escribía a disco; aquí la
entrada es la API) y `ResultadoAuditoria` expone además los Signals crudos
(`signals`) y las reglas fallidas (`fallos`) para guardarlos en PostgreSQL. La
lógica de auditoría no cambió.
"""

from dataclasses import dataclass, field

import duckdb
import pandas as pd

from .case_file import render_case_file
from .ensamblador import Ensamblador, ensamblar
from .entidades import Entidad
from .estate import Estate
from .metricas import RunMetrics
from .runner import cargar_reglas, ejecutar_reglas, nombre_regla
from .submission import build_submission, traducir_finding
from .validacion import validar


@dataclass
class ResultadoAuditoria:
    submission: dict
    case_file_html: str | None  # None si el submission no pasó el validador
    validacion_ok: bool
    errores_validacion: list[str]
    avisos: list[str] = field(default_factory=list)
    calidad: dict[str, int] = field(default_factory=dict)
    senales_por_regla: dict[str, int] = field(default_factory=dict)
    signals: pd.DataFrame | None = None  # contrato del runner + `contexto` (JSON)
    fallos: list[tuple[str, str]] = field(default_factory=list)
    reglas_ejecutadas: list[str] = field(default_factory=list)


def auditar_conexion(
    con: duckdb.DuckDBPyConnection, seed: int = 0, estate_nombre: str = "estate"
) -> ResultadoAuditoria:
    """Audita el estate de `con` (solo lectura) y devuelve submission, case file y validación."""
    metrics = RunMetrics()
    metrics.start()

    reglas = cargar_reglas()
    signals, fallos, resumen = ejecutar_reglas(con, reglas)
    avisos = [f"Detector {nombre} failed and was omitted: {error}" for nombre, error in fallos]

    estate = Estate(con)
    findings_internos, leads, calidad = ensamblar(estate, signals)

    ensamblador = Ensamblador(estate)
    findings, anexos = [], []
    for fi in findings_internos:
        finding, anexo = traducir_finding(ensamblador, fi)
        findings.append(finding)
        anexos.append(anexo)

    submission = build_submission(seed, findings, leads, metrics)
    ok, errores = validar(con, submission)
    resultado = ResultadoAuditoria(
        submission=submission,
        case_file_html=None,
        validacion_ok=ok,
        errores_validacion=errores,
        avisos=avisos,
        calidad=calidad,
        senales_por_regla={nombre: n for nombre, n in resumen},
        signals=signals,
        fallos=fallos,
        reglas_ejecutadas=[nombre_regla(r) for r in reglas],
    )
    if not ok:
        return resultado

    empresa_nombre = None
    if estate.empresa_rfc:
        filas = estate.vendors_por_rfc(estate.empresa_rfc)
        empresa_nombre = filas[0]["legal_name"] if filas else None
    nombres_pistas = {}
    for lead in leads:
        prefijo, _, ident = lead["entity"].partition(":")
        tipo = {"RFC": "rfc", "EMP": "employee"}.get(prefijo)
        if tipo:
            nombres_pistas[lead["entity"]] = ensamblador.nombre(Entidad(tipo, ident))
    contexto = {
        "nombres_pistas": nombres_pistas,
        "empresa_rfc": estate.empresa_rfc,
        "empresa_nombre": empresa_nombre,
        "periodo": estate.periodo(),
        "calidad": calidad,
        "reglas_ejecutadas": [nombre_regla(r) for r in reglas],
        "reglas_fallidas": fallos,
        "estate_nombre": estate_nombre,
    }
    resultado.case_file_html = render_case_file(submission, anexos, contexto)
    return resultado
