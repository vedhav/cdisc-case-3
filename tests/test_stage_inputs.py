"""Behavior test for container/stage_inputs.py.

Builds a /data dir mixing the USDM with SDTM (including a Dataset-JSON SDTM file
that must NOT be mistaken for the USDM), and asserts the content-detection split:
USDM -> /workspace/usdm.json, everything else -> /workspace/sdtm/. Also asserts the
fail-fast paths (no USDM, no SDTM). Pure filesystem logic — MUST run green.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "container" / "stage_inputs.py"
USDM_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "stage" / "usdm_min.json"


def _run(data: Path, workspace: Path) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env.update({"DATA_DIR": str(data), "WORKSPACE_DIR": str(workspace)})
    return subprocess.run([sys.executable, str(SCRIPT)], env=env, capture_output=True, text=True)


def test_detects_usdm_and_stages_sdtm() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        data = Path(tmp) / "data"
        ws = Path(tmp) / "workspace"
        data.mkdir()
        # USDM + two SDTM csvs + one Dataset-JSON SDTM (a .json that is NOT the USDM).
        (data / "study_def.json").write_text(USDM_FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
        (data / "dm.csv").write_text("USUBJID\n001\n", encoding="utf-8")
        (data / "qs.xpt").write_text("binary-ish", encoding="utf-8")
        (data / "vs.json").write_text(json.dumps({"datasetJSONVersion": "1.1", "records": []}), encoding="utf-8")

        proc = _run(data, ws)
        assert proc.returncode == 0, f"exit {proc.returncode}: {proc.stderr}"

        assert (ws / "usdm.json").exists()
        assert json.loads((ws / "usdm.json").read_text(encoding="utf-8"))["usdmVersion"] == "3.0.0"

        staged = sorted(p.name for p in (ws / "sdtm").iterdir())
        assert staged == ["dm.csv", "qs.xpt", "vs.json"], staged  # Dataset-JSON stays SDTM
        manifest = json.loads((ws / "stage_manifest.json").read_text(encoding="utf-8"))
        assert manifest["usdm"] == "study_def.json"
        assert manifest["sdtmCount"] == 3


def test_no_usdm_fails() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        data = Path(tmp) / "data"
        ws = Path(tmp) / "workspace"
        data.mkdir()
        (data / "dm.csv").write_text("USUBJID\n", encoding="utf-8")
        (data / "notusdm.json").write_text(json.dumps({"records": []}), encoding="utf-8")
        proc = _run(data, ws)
        assert proc.returncode != 0, "expected non-zero when no USDM present"
        assert not (ws / "usdm.json").exists()


def test_no_sdtm_fails() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        data = Path(tmp) / "data"
        ws = Path(tmp) / "workspace"
        data.mkdir()
        (data / "study_def.json").write_text(USDM_FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
        proc = _run(data, ws)
        assert proc.returncode != 0, "expected non-zero when only the USDM is uploaded"


if __name__ == "__main__":
    test_detects_usdm_and_stages_sdtm()
    test_no_usdm_fails()
    test_no_sdtm_fails()
    print("test_stage_inputs: all passed")
