"""Gate the self-learning tail on whether any review actually sent feedback back.

Runs as the `check-feedback` script step, after the traceability HTML is built.
On each Request-Changes, the producing agent step appends the reviewer comment to
/workspace/review_feedback.jsonl. This step reads that file and emits `hadRevisions`
so the workflow only spends the ~15-min `propose-skill-update` agent + the
`open-skill-pr` step when there is feedback to learn from — a clean first-pass run
(no revisions) routes straight to done.

Reads:  /workspace/review_feedback.jsonl   one JSON object per revise
Writes: /output/result.json  { hadRevisions: bool, revisionCount: int, skills: [str] }

The `hadRevisions` field drives the transition `when` out of this step. Paths are
overridable via WORKSPACE_DIR / OUTPUT_DIR for local testing; always exits 0.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

WORKSPACE = Path(os.environ.get("WORKSPACE_DIR", "/workspace"))
OUTPUT = Path(os.environ.get("OUTPUT_DIR", "/output"))


def main() -> None:
    feedback = WORKSPACE / "review_feedback.jsonl"
    revision_count = 0
    skills: list[str] = []

    if feedback.is_file():
        for line in feedback.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            revision_count += 1
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            skill = entry.get("skill") if isinstance(entry, dict) else None
            if skill and skill not in skills:
                skills.append(skill)

    result = {"hadRevisions": revision_count > 0, "revisionCount": revision_count, "skills": skills}
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"check_feedback: hadRevisions={result['hadRevisions']} "
          f"({revision_count} revision(s), skills={skills or 'none'})")


if __name__ == "__main__":
    main()
