# Test summary — cdisc-case-3 self-learning loop

Run: `python tests/run_tests.py`

| Script | Status | Asserted shape |
|--------|--------|----------------|
| `container/open_skill_pr.py` — `append_lesson` | **tested** | Appends the lesson block to `lessons-learned.md`; idempotent on retry (same block at the tail ⇒ no change); raises `FileNotFoundError` when the lessons file is absent. |
| `container/open_skill_pr.py` — no-lessons path | **tested** | `hasLessons:false` input ⇒ `/output/result.json` = `{prCreated:false, reason:"no-lessons"}`, exit 0, and **no clone** (network never touched). |
| `container/open_skill_pr.py` — clone → append → push → open PR | **skipped — needs `GITHUB_TOKEN` + write access to the skill repo** | On `hasLessons:true`, clones `SKILL_REPO`, appends, branches `skill-lesson/<runId>`, commits as `Mediforce Bot`, pushes, opens a PR against `main`; result `{prCreated:true, prUrl, branch}`. |
| `plugins/.../propose-skill-lesson/SKILL.md` | not a script (agent skill) | Exercised by a real run; output contract `{hasLessons, lessonAppendMarkdown, prTitle, prBody, summary}`. |

The clone/push/PR path is not runnable offline (it writes to a live GitHub repo).
To exercise it end to end after providing credentials, run against a throwaway
fork you can write to:

```bash
GITHUB_TOKEN=<token with contents:write + pull-requests:write> \
SKILL_REPO=<your-fork>/cdisc-case-3 \
OUTPUT_DIR=/tmp/osp-out \
python container/open_skill_pr.py
# with /tmp/osp-out/input.json = tests/fixtures/lessons.input.json
```

Expect a `skill-lesson/test-run-0002` branch and an open PR appending one lesson
to `plugins/cdisc-case-3/skills/draft-custom-programs/references/lessons-learned.md`.
