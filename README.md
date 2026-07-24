# cdisc-case-3 — USDM → traceable TFLs (full pipeline)

A Mediforce workflow for the CDISC AI Innovation Challenge, **Use Case 3:
AI-Driven Tables, Figures, and Listings (TFL) Generation** — now the **full
protocol-to-TFL pipeline**. Given a study's **USDM** metadata (and its **SDTM**
datasets) it plans the required TFLs, builds the analysis + ADaM specs, derives
ADaM, generates the **ARD** (numbers) and rendered **TFLs** (display), and
assembles an interactive **objective → endpoint → SDTM → ADaM → TFL**
traceability explorer.

**Thesis:** *plan from the objectives, generate from the spec, prove against the
standards.* Every TFL traces back through the ARD to the ADaM, SDTM, endpoint,
and objective that justify it. Validation is anchored to the **CDISC standards**,
not to a golden output — so it generalises to any study, whether or not a
known-good CSR exists: two deterministic conformance gates enforce that the
analysis metadata is a schema-valid **ARS** ReportingEvent and that the derived
**ADaM** passes **CDISC CORE** against a generated **Define-XML 2.1**. Three human
review gates (plan, specs, TFLs) each feed a **self-learning skill-refinement
loop**: reviewer feedback is distilled into durable, per-skill lessons and opened
as a PR, so the skills improve over time.

## Pipeline (16 steps)

| # | Step | Executor | Skill / script | Output |
|---|------|----------|----------------|--------|
| 1 | upload-inputs | human | — | upload the study's USDM JSON + SDTM datasets (→ `/data/` for plan-tlfs) |
| 2 | plan-tlfs | agent | `tlf-planner` | study-model.json, tlf-plan.json, tlf-index.md (+ persists SDTM → `/workspace/sdtm/`) |
| 3 | audit-plan | agent | `tlf-plan-critic` | coverage-report.md + verdict |
| 4 | **review-plan** | human review | — | approve → specs · revise → plan |
| 5 | build-specs | agent | `tlf-analysis-spec` | analysis-spec.json, adam-spec.json, **reporting-event.json (ARS)** |
| 6 | **validate-ars** | script (gate) | `validate_ars.py` | ars-validation.md · pass → specs review · fail → build-specs (≤3) |
| 7 | **review-specs** | human review | — | approve → ADaM · revise → specs |
| 8 | derive-adam | agent | `sdtm-to-adam` | `/workspace/adam/*` + conformance report |
| 9 | **generate-define** | script | `generate_define.py` | define.xml (Define-XML 2.1) |
| 10 | **validate-core** | script (gate) | `validate_core.py` | core-report.md · pass → generate · fail → derive-adam (≤2) |
| 11 | generate-tlfs | agent | `tlf-generator` | ARD + rendered TFLs |
| 12 | **review-tlfs** | human review | — | approve → trace · revise → generate |
| 13 | build-traceability | script | `build_traceability.py` | traceability.html, trace_graph.json, manifest.json |
| 14 | propose-skill-update | agent | `propose-skill-lesson` | per-skill lesson blocks |
| 15 | open-skill-pr | script | `open_skill_pr.py` | PR against main (or clean no-op) |
| 16 | done | human (terminal) | — | — |

### The two automated conformance gates

Both are deterministic `script` steps that **always exit 0** and encode the
outcome in `result.json`; the workflow transitions branch on `output.passed` and
a bounded `output.attempts` counter (persisted in `/workspace/.gate-attempts.json`).

- **`validate-ars`** validates `reporting-event.json` against the ARS LDM JSON
  Schema (baked into the image at `container/schemas/ars_ldm.schema.json`) plus
  reference-integrity checks. Pass → human spec review; fail → back to
  `build-specs` with the exact errors (`ars-validation.md`), capped at **3**
  attempts, after which it proceeds to human review with the errors surfaced.
- **`validate-core`** runs the CDISC Open Rules Engine (`cdisc-rules-engine`,
  CLI `core`) over the derived ADaM **against `define.xml`**. ERROR-severity
  findings gate: pass → `generate-tlfs`; fail → back to `derive-adam` (capped at
  **2**), then proceed forward with unresolved findings carried to `review-tlfs`
  for the reviewer to justify. WARNING/NOTICE findings are reported, not blocking.
  If the engine/rules-cache is unavailable it reports `status=core-unavailable`
  and proceeds unless `CORE_REQUIRED=true` — never a silent pass.

The loop caps (3, 2) live BOTH in the transition `when` expressions and as the
scripts' `ARS_MAX_ATTEMPTS` / `CORE_MAX_ATTEMPTS` defaults; keep them in sync if
you change either.

All inputs are uploaded up front at a single `file-upload` step (step 1): the
**USDM** JSON and the **SDTM** datasets together. They are made available read-only
under `/data/` to the next step (plan-tlfs), which persists the SDTM into
`/workspace/sdtm/` for the later ADaM step — so no separate staging step is needed.

Transitions include three revise loops (each review gate can send the run back
to its producing agent step).

### The self-learning skill-refinement loop (retained + generalized)

On each **Request Changes**, the producing agent step (`plan-tlfs`,
`build-specs`, `generate-tlfs`) appends the reviewer comment to
`/workspace/review_feedback.jsonl`, **tagged with its skill**. After approval,
`propose-skill-update` groups that feedback by skill and distils durable,
skill-general lessons; `open-skill-pr` appends each to the target skill's
`references/lessons-learned.md` and opens one PR against `main`. A human merges;
the next run reads the improved skills. First-pass approvals (no revisions)
produce no PR.

## Skills (in `plugins/cdisc-case-3/skills`, read at run time via `externalSkillsRepo` + `skillsDir`)

Six skills run as agents: `tlf-planner`, `tlf-plan-critic`, `tlf-analysis-spec`,
`sdtm-to-adam`, `tlf-generator`, `propose-skill-lesson`. The revisable ones
(`tlf-planner`, `tlf-analysis-spec`, `tlf-generator`) each carry a
`references/lessons-learned.md` that the loop appends to.

`traceability-builder` is **no longer invoked as an agent** — the traceability
step is now the deterministic `container/build_traceability.py` script (it never
recomputes a statistic, so it needs no LLM; this removes its per-run cost and
nondeterminism). The skill directory is retained as the shared design/mirror and
as the human-readable contract the script implements
(`references/graph-data-schema.md`).

## Environment variables & secrets

| Name | Secret | Scope | Used by | Meaning | How to set | Example |
|------|--------|-------|---------|---------|------------|---------|
| `GITHUB_TOKEN` | ✅ | workflow | all script/agent steps (Docker build context + skills fetch) and `open-skill-pr` | Token with repo read for the pinned build/skills context, plus `contents:write` + `pull-requests:write` for the skill-lesson PR | namespace/workflow secret | `ghp_…` |
| `OPENROUTER_API_KEY` | ✅ | workflow | every agent step (mapped to `ANTHROPIC_AUTH_TOKEN`, base URL `https://openrouter.ai/api`) | LLM credential for the Claude-Code agents | namespace/workflow secret | `sk-or-…` |
| `SKILL_REPO` | — | `open-skill-pr` step env | `open_skill_pr.py` | `<owner>/<repo>` the skills live in | step `env` | `vedhav/cdisc-case-3` |

Secrets are referenced via `{{SECRET_NAME}}` templates and are never committed or
baked into the image.

## Docker image

`mediforce-agent:cdisc-case-3`, built from `Dockerfile` (`FROM
mediforce-golden-image`). Adds the pinned R stack — admiral/admiraldev/metacore/
metatools (ADaM); cards/cardx/emmeans/mmrm/survival/broom.helpers (ARD + models);
gtsummary/gt/tfrmt/rtables/rlistings/ggsurvfit/ggplot2 (display); dplyr/tidyr/
haven/jsonlite — plus Python `pyyaml` and the step scripts (`container/`). Skills
and the local-test `fixtures/` are **not** baked in (inputs are uploaded per run;
fixtures are for local testing only).

Every step references this image **by tag only** (`image: mediforce-agent:cdisc-case-3`,
no `repo`/`commit`/`dockerfile`) — same as `apps/protocol-to-tfl`. The image must
already exist on the host that runs the containers; the platform does **not**
auto-build it. Build it once on that host:
`docker build -t mediforce-agent:cdisc-case-3 .`. Rebuild + re-tag whenever the
`Dockerfile` or `container/` scripts change. (The prior per-step auto-build shape
— `repo`+`commit`+`dockerfile` — was removed: a hand-built image carries no
`mediforce.build.commit` label, so the runtime saw it as "stale" and tried to
rebuild the R stack through `execSync(stdio:'pipe')`, whose 1 MB `maxBuffer`
overflows on the chatty source compile and hangs the step outside its timeout.)

## Output contract (`/output`)

`study-model.json`, `tlf-plan.json`, `tlf-index.md`, `coverage-report.md`,
`analysis-spec.json`, `adam-spec.json`, the ARD + rendered TFLs,
`traceability.html`, `trace_graph.json`, `manifest.json`, and each
step's `result.json`.

## Inputs (uploaded per run — nothing bundled)

A single `upload-inputs` step (step 1) collects everything up front; the files land
read-only under `/data/` for plan-tlfs (which persists the SDTM into `/workspace/sdtm/`):
- the study's **USDM** study-definition JSON (required).
- the study's **SDTM** datasets (required; `.xpt` / Dataset-JSON / `.csv` / `.sas7bdat`).

The pipeline runs against any new study's USDM + SDTM. A known-good reference for
smoke-testing is the **CDISCPILOT01** (H2Q-MC-LZZT Alzheimer's) USDM + SDTM,
produced/held upstream (Case 1/Case 2 and the `protocol-to-tfl` source).

## Runtime source pinning

Only `externalSkillsRepo.commit` is pinned — it is the sole runtime source the
platform fetches at run time (the pipeline skills, cloned from this repo at that
commit). Update it on each skill release via the two-step pin dance: push, read
HEAD, rewrite the pin to that SHA, push again. The Docker image is **not** pinned
by commit here — it is referenced by tag and built out-of-band on the host (see
Docker image above), so keep the image in sync with `Dockerfile`/`container/` by
rebuilding when they change. `workspace.remote` is unused; `source` (git-import
provenance) is n/a.

## Registration

Import/register a new workflow version for every released change
(`mediforce workflow validate` then register). See `src/cdisc-case-3.wd.json`.
