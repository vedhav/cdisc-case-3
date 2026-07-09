"""Behavior test for container/open_skill_pr.py.

Covers the network-free logic:
  - append_lesson: appends the block and is idempotent under retry
  - no-lessons path: main() writes prCreated=false and exits 0 before any clone

The clone -> push -> open-PR path needs a live GITHUB_TOKEN + write access to the
skill repo, so it is exercised only by a real run (see tests/TEST_SUMMARY.md).
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "container" / "open_skill_pr.py"
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load_module():
    spec = importlib.util.spec_from_file_location("open_skill_pr", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_append_lesson_appends_and_is_idempotent() -> None:
    mod = _load_module()
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        lessons = repo / mod.LESSONS_FILE
        lessons.parent.mkdir(parents=True)
        lessons.write_text("# lessons\n\n<!-- lessons appended below -->\n", encoding="utf-8")

        block = "\n### 2026-07-09 — run r1\n- **Lesson:** do X.\n"
        assert mod.append_lesson(repo, block) is True
        content = lessons.read_text(encoding="utf-8")
        assert "do X." in content
        assert content.endswith(block)

        # Same block again — already at the tail, no change (retry-safe).
        assert mod.append_lesson(repo, block) is False
        assert lessons.read_text(encoding="utf-8") == content


def test_append_lesson_missing_file_raises() -> None:
    mod = _load_module()
    with tempfile.TemporaryDirectory() as tmp:
        try:
            mod.append_lesson(Path(tmp), "\n### x\n")
        except FileNotFoundError:
            return
        raise AssertionError("expected FileNotFoundError when lessons file absent")


def test_no_lessons_path_writes_no_pr_and_exits_zero() -> None:
    """hasLessons=false -> prCreated=false, exit 0, no network touched."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "output"
        out.mkdir()
        (out / "input.json").write_text(
            (FIXTURES / "no_lessons.input.json").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        env = os.environ.copy()
        env.update(
            {
                "OUTPUT_DIR": str(out),
                "GITHUB_TOKEN": "dummy-token-not-used",
                "SKILL_REPO": "owner/repo",
                "CLONE_DIR": str(Path(tmp) / "clone"),
            }
        )
        result = subprocess.run(
            [sys.executable, str(SCRIPT)], env=env, capture_output=True, text=True
        )
        assert result.returncode == 0, f"expected exit 0, got {result.returncode}: {result.stderr}"
        payload = json.loads((out / "result.json").read_text(encoding="utf-8"))
        assert payload["prCreated"] is False
        assert payload["reason"] == "no-lessons"
        assert not (Path(tmp) / "clone").exists(), "must not clone on the no-lessons path"


if __name__ == "__main__":
    test_append_lesson_appends_and_is_idempotent()
    test_append_lesson_missing_file_raises()
    test_no_lessons_path_writes_no_pr_and_exits_zero()
    print("test_open_skill_pr: all passed")
