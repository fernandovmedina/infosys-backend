"""Unit tests for the normalization shared by the importer and the search."""

from __future__ import annotations

import pytest

from app.sat.normalization import (
    is_cleared,
    is_redacted,
    is_valid_rfc,
    name_core,
    normalize_name,
    normalize_rfc,
    normalize_situacion,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("aaa080808hl8", "AAA080808HL8"),
        ("  AAA080808HL8  ", "AAA080808HL8"),
        ("aaa-080808-hl8", "AAA080808HL8"),
        ("AAA 080808 HL8", "AAA080808HL8"),
        ("CACL7806172Y1", "CACL7806172Y1"),
        (None, ""),
        ("", ""),
    ],
)
def test_normalize_rfc(raw: str | None, expected: str) -> None:
    assert normalize_rfc(raw) == expected


@pytest.mark.parametrize(
    ("rfc", "valid"),
    [
        ("AAA080808HL8", True),  # persona moral, 12 chars
        ("CACL7806172Y1", True),  # persona fisica, 13 chars
        ("XXXXXXXXXXXX", False),  # SAT redaction placeholder
        ("AAA080808", False),  # too short
        ("AAA080808HL88888", False),  # too long
        ("1AA080808HL8", False),  # must start with letters
        ("AAAAAAAAAHL8", False),  # missing the date block
        ("", False),
    ],
)
def test_is_valid_rfc(rfc: str, valid: bool) -> None:
    assert is_valid_rfc(rfc) is valid


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Asesores en Avalúos y Activos, S.A. de C.V.", "ASESORES EN AVALUOS Y ACTIVOS SA DE CV"),
        ("ASESORES  EN   AVALUOS", "ASESORES EN AVALUOS"),
        ("ZUÑIGA RAMIREZ CAROLINA", "ZUNIGA RAMIREZ CAROLINA"),
        ("  espacios  alrededor  ", "ESPACIOS ALREDEDOR"),
        ("ABIRA & SAFFI CORPORATIVO", "ABIRA & SAFFI CORPORATIVO"),
        (None, ""),
    ],
)
def test_normalize_name(raw: str | None, expected: str) -> None:
    assert normalize_name(raw) == expected


def test_normalize_name_is_accent_and_case_insensitive() -> None:
    assert normalize_name("Ingenios Santos, S.A. de C.V.") == normalize_name(
        "INGENIOS SANTOS S.A. DE C.V."
    )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("INGENIOS SANTOS, S.A. DE C.V.", "INGENIOS SANTOS"),
        ("ABIRA & SAFFI CORPORATIVO, S. DE R.L. DE C.V.", "ABIRA & SAFFI CORPORATIVO"),
        ("ZUÑIGA RAMIREZ CAROLINA", "ZUNIGA RAMIREZ CAROLINA"),
        (
            "AQUAERIS ACUACULTURA Y ARQUITECTURA SUSTENTABLE, S.C.",
            "AQUAERIS ACUACULTURA Y ARQUITECTURA SUSTENTABLE",
        ),
    ],
)
def test_name_core_strips_corporate_suffix(raw: str, expected: str) -> None:
    assert name_core(raw) == expected


def test_name_core_keeps_at_least_one_token() -> None:
    """A name made only of suffix tokens must not be emptied."""
    assert name_core("S.A. DE C.V.") != ""


def test_normalize_situacion_collapses_padding() -> None:
    assert normalize_situacion("Desvirtuado ") == "Desvirtuado"
    assert normalize_situacion("  Sentencia   Favorable ") == "Sentencia Favorable"


@pytest.mark.parametrize(
    ("situacion", "cleared"),
    [
        ("Desvirtuado", True),
        ("Sentencia Favorable", True),
        ("Definitivo", False),
        ("Presunto", False),
        ("Un Estado Nuevo De SAT", False),  # unknown status fails safe
    ],
)
def test_is_cleared(situacion: str, cleared: bool) -> None:
    assert is_cleared(situacion) is cleared


def test_is_redacted() -> None:
    assert is_redacted("XXXXXXXXXXXX") is True
    assert is_redacted("AAA080808HL8") is False
