import json
from pathlib import Path

import pytest

from app.fraud.engine.cli import ReplayError, replay
from tests.test_fraud.conftest import ESCENARIO_1301


def test_offline_replay_writes_a_verified_artifact_bundle(tmp_path: Path) -> None:
    output_dir = tmp_path / "replay"

    manifest = replay(
        input_dir=ESCENARIO_1301, output_dir=output_dir, seed=1301, max_rows=1_000_000
    )

    submission = json.loads((output_dir / "submission.json").read_text(encoding="utf-8"))
    saved_manifest = json.loads((output_dir / "audit-log.json").read_text(encoding="utf-8"))
    html = (output_dir / "case-file.html").read_text(encoding="utf-8")
    assert submission["seed"] == 1301
    assert "Static forensic case file" in html
    assert manifest == saved_manifest
    assert saved_manifest["validation"]["official_validator_passed"] is True
    assert saved_manifest["input"]["bundle_sha256"]
    assert saved_manifest["deterministic_result"]["sha256"]
    assert saved_manifest["operational_metadata"]["wall_clock_seconds"] >= 0


def test_offline_replay_refuses_to_overwrite_an_artifact_directory(tmp_path: Path) -> None:
    output_dir = tmp_path / "replay"
    replay(input_dir=ESCENARIO_1301, output_dir=output_dir, seed=1301, max_rows=1_000_000)

    with pytest.raises(ReplayError, match="will not be overwritten"):
        replay(input_dir=ESCENARIO_1301, output_dir=output_dir, seed=1301, max_rows=1_000_000)
