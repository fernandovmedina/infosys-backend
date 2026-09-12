"""Normalization shared by the importer and the search.

Both sides of a lookup must agree exactly. The importer writes
``rfc_normalized`` / ``name_normalized`` / ``name_core`` into the table using
these functions, and the API normalizes incoming queries with the very same
ones. Because normalization happens in Python rather than in SQL, the query is a
plain equality test against an indexed column -- no function call wraps the
column, so the B-tree and GIN indexes stay usable.

Changing any function here changes the meaning of the stored columns, so a
change must be followed by a re-import (``uv run sat-blacklist-import``).
"""

from __future__ import annotations

import re
import unicodedata

# Mexican RFC: 3 letters for a company (persona moral), 4 for an individual
# (persona física), then a 6-digit date (YYMMDD) and a 3-character homoclave.
RFC_PATTERN = re.compile(r"^[A-ZÑ&]{3,4}[0-9]{6}[A-Z0-9]{3}$")

RFC_LENGTH_MORAL = 12
RFC_LENGTH_FISICA = 13

# Placeholder SAT publishes when a taxpayer's identity is suppressed by court
# order. The accompanying name reads "Información suprimida en cumplimiento...".
REDACTED_RFC = "XXXXXXXXXXXX"

# Statuses meaning the taxpayer rebutted the presumption. Anything unrecognised
# is treated as *not* cleared, so a new SAT status fails safe.
CLEARED_SITUACIONES = frozenset({"DESVIRTUADO", "SENTENCIA FAVORABLE"})

_RFC_STRIP = re.compile(r"[^A-Z0-9Ñ&]")
_COMBINING_MARKS = re.compile(r"[\u0300-\u036f]")
# Deleted outright rather than replaced by a space, so "S.A." collapses to
# "SA" instead of splitting into "S A". \u2019 is the typographic apostrophe.
_NAME_DROP = re.compile(r"[.'\u2019]")
_NAME_TO_SPACE = re.compile(r"[^A-Z0-9&]+")
_WHITESPACE = re.compile(r"\s+")

# Trailing tokens that make up Mexican corporate suffixes. Stripped from the end
# of a name to build `name_core`, so that "GRUPO X, S.A. DE C.V." and "GRUPO X"
# compare equal. Only ever removed from the tail, never from the middle.
_SUFFIX_TOKENS = frozenset(
    {
        "SA",
        "SAS",
        "SAB",
        "SAPI",
        "SC",
        "AC",
        "SCL",
        "SCP",
        "SNC",
        "SPR",
        "SRL",
        "RL",
        "CV",
        "MI",
        "IAP",
        "ABP",
        "SOFOM",
        "SOFOL",
        "ENR",
        "ER",
        "SUCS",
        "SUC",
        "S",
        "C",
        "V",
        "R",
        "L",
        "DE",
        "EN",
        "NC",
        "Y",
    }
)


def normalize_rfc(value: str | None) -> str:
    """Uppercase an RFC and drop every separator.

    Handles the formatting inconsistencies seen in user input -- surrounding
    whitespace, lowercase, and the hyphens/spaces people type between the
    fiscal-name, date and homoclave blocks (``abc-123456-xyz``).
    """
    if not value:
        return ""
    return _RFC_STRIP.sub("", value.strip().upper())


def is_valid_rfc(normalized_rfc: str) -> bool:
    """Whether an already-normalized RFC is structurally valid."""
    if len(normalized_rfc) not in (RFC_LENGTH_MORAL, RFC_LENGTH_FISICA):
        return False
    return RFC_PATTERN.match(normalized_rfc) is not None


def _fold_accents(value: str) -> str:
    """Strip diacritics: ``Á``->``A``, ``Ñ``->``N``, ``Ü``->``U``."""
    decomposed = unicodedata.normalize("NFD", value)
    return _COMBINING_MARKS.sub("", decomposed)


def normalize_name(value: str | None) -> str:
    """Fold a company or person name into its comparable form.

    Removes the differences the task calls out: case, accents, punctuation and
    extra whitespace. ``"Asesores en Avalúos y Activos, S.A. de C.V."`` and
    ``"ASESORES EN AVALUOS Y ACTIVOS S.A. DE C.V."`` both become
    ``"ASESORES EN AVALUOS Y ACTIVOS SA DE CV"``.

    Periods are deleted rather than replaced with a space, so ``S.A.`` collapses
    to ``SA`` instead of splitting into ``S A``.
    """
    if not value:
        return ""
    folded = _fold_accents(value.upper())
    folded = _NAME_DROP.sub("", folded)
    folded = _NAME_TO_SPACE.sub(" ", folded)
    return _WHITESPACE.sub(" ", folded).strip()


def strip_corporate_suffix(normalized_name: str) -> str:
    """Remove trailing corporate-form tokens from an already-normalized name.

    ``"ABIRA & SAFFI CORPORATIVO S DE RL DE CV"`` -> ``"ABIRA & SAFFI CORPORATIVO"``.

    At least one token is always kept, so a name consisting only of suffix
    tokens is returned unchanged rather than emptied.
    """
    tokens = normalized_name.split()
    while len(tokens) > 1 and tokens[-1] in _SUFFIX_TOKENS:
        tokens.pop()
    return " ".join(tokens) if tokens else normalized_name


def name_core(value: str | None) -> str:
    """Convenience wrapper: normalize a name and strip its corporate suffix."""
    return strip_corporate_suffix(normalize_name(value))


def normalize_situacion(value: str | None) -> str:
    """Collapse whitespace in a status value.

    The source file pads some of them (``"Desvirtuado "``). Case is preserved so
    the stored value still reads the way SAT publishes it.
    """
    if not value:
        return ""
    return _WHITESPACE.sub(" ", value).strip()


def is_cleared(situacion: str) -> bool:
    """Whether a status means the taxpayer rebutted the presumption."""
    return situacion.upper() in CLEARED_SITUACIONES


def is_redacted(normalized_rfc: str) -> bool:
    """Whether a row is one of SAT's identity-suppressed placeholders."""
    return normalized_rfc.startswith(REDACTED_RFC)
