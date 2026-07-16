# Test summary — cdisc-case-3 container scripts

Run: `python tests/run_tests.py`

| Script | Status | Asserted shape |
|--------|--------|----------------|
| `container/build_trace_graph.py` (assemble-trace-graph) | **tested** | Deterministic join of study-model / tlf-plan / analysis-spec / adam-spec + staged SDTM + per-TLF artifacts ⇒ `trace_graph.json` per graph-data-schema: counts (2 obj / 2 end / 1 unresolved / 3 TLF / 2 ADaM / 1 absent SDTM), status tally `{generated:2, blocked:1}`, obj-end/end-tlf/tlf-adam/adam-sdtm/reg-tlf edges, dashed `tlf-sdtm` to the absent `DV`, issues feed (blocked+clarification+gap), embedded `generatedMd`/`ardJson`; written to `/workspace` **and** `/output`. |
| `container/stage_inputs.py` (plan-tlfs STEP 0) | **tested** | Content-detects the USDM (by `usdmVersion`/`study.versions`) even when SDTM arrives as Dataset-JSON ⇒ `/workspace/usdm.json` + every other upload → `/workspace/sdtm/` + `stage_manifest.json`; fail-fast (non-zero) when no USDM or no SDTM. |
| `container/check_feedback.py` (check-feedback) | **tested** | `/workspace/review_feedback.jsonl` ⇒ `{hadRevisions, revisionCount, skills[]}` (distinct, first-seen order; blank lines ignored); absent file ⇒ `hadRevisions:false`. Drives the `output.hadRevisions` transition branch. |
| `container/open_skill_pr.py` — `append_lesson` | **tested** | Appends the lesson block to a skill's `lessons-learned.md`; idempotent on retry (same block at the tail ⇒ no change); **creates** the file when a newly-ported skill has none. |
| `container/open_skill_pr.py` — no-lessons path | **tested** | `hasLessons:false` input ⇒ `/output/result.json` = `{prCreated:false, reason:"no-lessons"}`, exit 0, and **no clone** (network never touched). |
| `container/open_skill_pr.py` — fail-soft (F3) | **tested** | A config error (missing `GITHUB_TOKEN`) records `{prCreated:false, reason:"error:…"}` and **exits 0**, so the PR side effect never fails an already-approved run. |
| `container/open_skill_pr.py` — clone → append → push → open PR | **skipped — needs `GITHUB_TOKEN` + write access to the skill repo** | On `hasLessons:true`, clones `SKILL_REPO`, appends, branches `skill-lesson/<runId>`, commits as `Mediforce Bot`, pushes, opens a PR against `main`; result `{prCreated:true, prUrl, branch}`. |
| `plugins/.../propose-skill-lesson/SKILL.md` | not a script (agent skill) | Exercised by a real run; output contract `{hasLessons, lessons[], prTitle, prBody, summary}`. |

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
