"""Offline, local replay for a directory containing the eight estate CSV files.

The command deliberately has no API, database, authentication, or network
dependency. It writes a new artifact bundle and refuses to overwrite an
existing one, so a completed bundle remains an auditable snapshot.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

import duckdb

from app.fraud.engine.esquema import TABLES
from app.fraud.engine.ingesta import IngestaInvalida, archivos_en_carpeta, cargar_csvs
from app.fraud.engine.pipeline import auditar_conexion
from app.fraud.service import ENGINE_VERSION


class ReplayError(ValueError):
    """A local replay could not produce a validated artifact bundle."""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _input_manifest(files: dict[str, Path]) -> tuple[str, list[dict[str, str]]]:
    digest = hashlib.sha256()
    entries = []
    for table in TABLES:
        path = files[table]
        content_hash = _sha256_file(path)
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(bytes.fromhex(content_hash))
        entries.append({"table": table, "filename": path.name, "sha256": content_hash})
    return digest.hexdigest(), entries


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def replay(*, input_dir: Path, output_dir: Path, seed: int, max_rows: int) -> dict[str, Any]:
    """Run one offline replay and atomically publish its immutable output bundle."""
    if not input_dir.is_dir():
        raise ReplayError(f"Input directory does not exist: {input_dir}")
    if output_dir.exists():
        raise ReplayError(f"Output directory already exists and will not be overwritten: {output_dir}")

    files = archivos_en_carpeta(input_dir)
    input_sha256, input_files = _input_manifest(files) if len(files) == len(TABLES) else ("", [])
    try:
        with duckdb.connect() as con:
            rows = cargar_csvs(con, files, max_filas=max_rows)
            result = auditar_conexion(con, seed=seed, estate_nombre=input_dir.name)
    except IngestaInvalida as exc:
        details = "; ".join(f"{item.archivo}: {item.mensaje}" for item in exc.errores)
        raise ReplayError(f"Input CSV validation failed: {details}") from exc

    if not result.validacion_ok or result.case_file_html is None:
        raise ReplayError(
            "Engine output did not pass the official validator: "
            + "; ".join(result.errores_validacion)
        )

    submission = result.submission
    deterministic_submission = json.loads(json.dumps(submission))
    deterministic_submission["run_metadata"].pop("wall_clock_seconds", None)
    manifest: dict[str, Any] = {
        "artifact_format": "fraud-replay/v1",
        "engine_version": ENGINE_VERSION,
        "seed": seed,
        "input": {"bundle_sha256": input_sha256, "files": input_files, "rows_per_table": rows},
        "validation": {"official_validator_passed": True, "errors": []},
        "analysis": {
            "rules_evaluated": len(result.senales_por_regla),
            "signals_per_rule": result.senales_por_regla,
            "data_quality": result.calidad,
            "rule_failures": [
                {"rule": rule, "error": error} for rule, error in result.fallos
            ],
            "warnings": result.avisos,
            "findings_count": len(submission["findings"]),
            "leads_closed_count": len(submission["leads_not_pursued"]),
        },
        "deterministic_result": {
            "definition": "submission.json excluding run_metadata.wall_clock_seconds",
            "sha256": hashlib.sha256(
                json.dumps(
                    deterministic_submission, ensure_ascii=False, separators=(",", ":"), sort_keys=True
                ).encode("utf-8")
            ).hexdigest(),
        },
        "operational_metadata": {
            "wall_clock_seconds": submission["run_metadata"]["wall_clock_seconds"],
            "note": "Execution time is observed operational metadata and is not deterministic.",
        },
    }

    output_dir.parent.mkdir(parents=True, exist_ok=True)
    temp_dir = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.tmp-", dir=output_dir.parent))
    try:
        _write_json(temp_dir / "submission.json", submission)
        (temp_dir / "case-file.html").write_text(result.case_file_html, encoding="utf-8")
        _write_json(temp_dir / "audit-log.json", manifest)
        temp_dir.replace(output_dir)
    except BaseException:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, required=True, help="Directory containing estate CSV files.")
    parser.add_argument("--output-dir", type=Path, required=True, help="New directory for the artifact bundle.")
    parser.add_argument("--seed", type=int, default=0, help="Deterministic audit seed (default: 0).")
    parser.add_argument("--max-rows", type=int, default=1_000_000, help="Maximum rows per CSV table.")
    args = parser.parse_args()
    if args.max_rows < 1:
        parser.error("--max-rows must be positive")
    try:
        manifest = replay(
            input_dir=args.input_dir,
            output_dir=args.output_dir,
            seed=args.seed,
            max_rows=args.max_rows,
        )
    except ReplayError as exc:
        parser.error(str(exc))
    print(
        f"Wrote {args.output_dir} "
        f"({manifest['analysis']['findings_count']} findings, "
        f"input sha256 {manifest['input']['bundle_sha256']})"
    )


if __name__ == "__main__":
    main()
