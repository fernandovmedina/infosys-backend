"""Read-only access to the supplied public estate contract.

The SQL schema remains the authoritative format specification in
``public/material``. Keeping its location in one module prevents generator
code from scattering hard-coded relative paths or silently copying the schema.
"""

from __future__ import annotations

from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[2]
CHALLENGE_MATERIAL_DIR = BACKEND_ROOT / "public" / "material"
ESTATE_SCHEMA_PATH = CHALLENGE_MATERIAL_DIR / "estate_schema.sql"


def load_estate_schema() -> str:
    """Return the supplied SQLite estate schema without modifying it."""
    return ESTATE_SCHEMA_PATH.read_text(encoding="utf-8")
