"""
Pipeline completo sobre el escenario seed 1301 (los 5 esquemas con decoys):
resultado idéntico al de referencia, determinista y aprobado por el validador.

Si un cambio intencional altera la salida, regenerar la referencia con el motor
de origen y copiar su submission.json sin run_metadata.wall_clock_seconds.
"""

import json
from typing import Any

import duckdb
import pytest

from app.fraud.engine.esquema import TABLES
from app.fraud.engine.ingesta import IngestaInvalida, archivos_en_carpeta, cargar_csvs
from app.fraud.engine.pipeline import auditar_conexion
from tests.test_fraud.conftest import ESCENARIO_1301, RAIZ

ESPERADO = RAIZ / "tests" / "fixtures" / "fraud" / "seed_1301.json"


def _sin_reloj(submission: dict[str, Any]) -> dict[str, Any]:
    copia: dict[str, Any] = json.loads(json.dumps(submission))
    copia["run_metadata"].pop("wall_clock_seconds")
    return copia


def test_resultado_igual_a_referencia(con_1301):
    resultado = auditar_conexion(con_1301, seed=1301)
    assert resultado.validacion_ok, resultado.errores_validacion
    assert resultado.avisos == []
    assert _sin_reloj(resultado.submission) == json.loads(ESPERADO.read_text(encoding="utf-8"))
    assert resultado.case_file_html is not None
    assert resultado.case_file_html.startswith("<!doctype html>") or (
        "<html" in resultado.case_file_html
    )
    assert "Static forensic case file" in resultado.case_file_html
    assert "app.fraud.engine.cli" not in resultado.case_file_html


def test_determinista(con_1301):
    a = auditar_conexion(con_1301, seed=1301)
    b = auditar_conexion(con_1301, seed=1301)
    assert _sin_reloj(a.submission) == _sin_reloj(b.submission)


def test_estate_vacio_no_acusa():
    with duckdb.connect() as con:
        for ddl in TABLES.values():
            con.execute(ddl)
        resultado = auditar_conexion(con)
    assert resultado.validacion_ok, resultado.errores_validacion
    assert resultado.submission["findings"] == []


def test_ingesta_reporta_columna_y_valor_invalidos(tmp_path):
    archivos = archivos_en_carpeta(ESCENARIO_1301)
    malo = tmp_path / "bank_txns.csv"
    lineas = archivos["bank_txns"].read_text(encoding="utf-8").splitlines()
    lineas[1] = lineas[1].replace(lineas[1].split(",")[4], "abc", 1)
    malo.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    renombrado = tmp_path / "vendors.csv"
    renombrado.write_text(
        archivos["vendors"].read_text(encoding="utf-8").replace("bank_clabe", "clabe", 1),
        encoding="utf-8",
    )

    with duckdb.connect() as con:
        with pytest.raises(IngestaInvalida) as exc:
            cargar_csvs(con, {**archivos, "vendors": renombrado})
        assert {(e.archivo, e.columna) for e in exc.value.errores} == {
            ("vendors.csv", "bank_clabe"),
            ("vendors.csv", "clabe"),
        }

        with pytest.raises(IngestaInvalida) as exc:
            cargar_csvs(con, {**archivos, "bank_txns": malo})
        assert [(e.archivo, e.columna) for e in exc.value.errores] == [("bank_txns.csv", "amount")]


def test_fraud_no_menciona_referencia_privada():
    needle = "ground" + "_truth"
    fugas = [
        str(p.relative_to(RAIZ))
        for p in (RAIZ / "app" / "fraud").rglob("*.py")
        if needle in p.read_text(encoding="utf-8")
    ]
    assert fugas == []


def test_validate_format_es_identico_a_material_publico():
    oficial = RAIZ / "app" / "fraud" / "engine" / "validate_format.py"
    publico = RAIZ / "public" / "material" / "validate_format.py"
    assert oficial.read_bytes() == publico.read_bytes()
