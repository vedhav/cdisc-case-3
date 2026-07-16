"""Behavior test for container/check_feedback.py.

Asserts the hadRevisions gate: a populated review_feedback.jsonl yields
hadRevisions=true with the distinct skills, and an absent/empty file yields
hadRevisions=false (a clean first-pass run skips the skill-refinement tail).
Pure logic — MUST run green.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "container" / "check_feedback.py"


def _run(workspace: Path) -> dict:
    out = workspace.parent / "output"
    out.mkdir(exist_ok=True)
    env = os.environ.copy()
    env.update({"WORKSPACE_DIR": str(workspace), "OUTPUT_DIR": str(out)})
    proc = subprocess.run([sys.executable, str(SCRIPT)], env=env, capture_output=True, text=True)
    assert proc.returncode == 0, f"exit {proc.returncode}: {proc.stderr}"
    return json.loads((out / "result.json").read_text(encoding="utf-8"))


def test_had_revisions_true_with_distinct_skills() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp) / "workspace"
        ws.mkdir()
        (ws / "review_feedback.jsonl").write_text(
            json.dumps({"skill": "tlf-planner", "iteration": 1, "comment": "fix numbering"}) + "\n"
            + "\n"  # blank line ignored
            + json.dumps({"skill": "tlf-generator", "iteration": 1, "comment": "wrong rounding"}) + "\n"
            + json.dumps({"skill": "tlf-planner", "iteration": 2, "comment": "again"}) + "\n",
            encoding="utf-8",
        )
        result = _run(ws)
        assert result["hadRevisions"] is True
        assert result["revisionCount"] == 3
        assert result["skills"] == ["tlf-planner", "tlf-generator"]  # distinct, first-seen order


def test_had_revisions_false_when_absent() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp) / "workspace"
        ws.mkdir()
        result = _run(ws)
        assert result["hadRevisions"] is False
        assert result["revisionCount"] == 0
        assert result["skills"] == []


if __name__ == "__main__":
    test_had_revisions_true_with_distinct_skills()
    test_had_revisions_false_when_absent()
    print("test_check_feedback: all passed")
