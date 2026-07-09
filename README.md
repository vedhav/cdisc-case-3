# cdisc-case-3 — ARS Reporting Event + ADaM → traceable TFLs

A Mediforce workflow for the CDISC AI Innovation Challenge, **Use Case 3:
AI-Driven Tables, Figures, and Listings (TFL) Generation**. It **executes** a
machine-readable CDISC **ARS v1.0 Reporting Event** (the SAP-as-data from Case 2)
against **ADaM** datasets to produce Tables, Figures, Listings and **Analysis
Results Datasets (ARD)** with end-to-end objective→result traceability.

**Thesis:** *execute the spec, don't reconstruct it.* Standard safety outputs run
through deterministic, validated **recipes**; the AI **drafts programs** only for
the custom efficacy outputs no validated code covers; a **human reviews** the
drafted programs before packaging. Traceability is exact **by construction** —
every result cell carries the ARS analysis/operation id that produced it.

See [`../mediforce/PLAN-3.md`](../mediforce/PLAN-3.md) for the full design.

## Steps

The former single "do everything" agent step is **decomposed into
single-responsibility steps**. Everything an LLM does *not* need to do — binding,
classification, running validated code — is deterministic; the AI is scoped to
the one thing no validated code covers (drafting the custom efficacy programs).

| # | Step | executor / plugin | What it does |
|---|------|-------------------|--------------|
| 1 | Provide inputs | `human` | Upload an ARS Reporting Event JSON + ADaM (or leave empty for the bundled CDISCPILOT01 reference) |
| 2 | Stage inputs | `script` | Resolve uploaded-or-bundled → `/workspace/reporting_event.json` + `/workspace/adam/` |
| 3 | Bind ARS to ADaM | `script` (py) | **Deterministic.** Resolve every `dataset.variable` (analysisSets, dataSubsets, groupings, analyses) against the real ADaM headers → `bindings.json` + `unbound.json` (gaps surfaced early, never dropped) |
| 4 | Classify outputs | `script` (py) | **Deterministic.** Rules table → standard vs custom per output; emit a fully-resolved recipe plan (recipe + args + real analysis/operation ids) → `coverage.json` + `standard_plan.json` |
| 5 | Run standard outputs | `script` (R) | **Deterministic, no LLM.** Execute the recipe plan over the validated recipe library → ARD + rendered table for every standard output |
| 6 | Draft custom programs | `agent` + `draft-custom-programs` skill | **AI, scoped to the custom outputs only.** Draft + run + repair standalone ANCOVA/KM programs → ARD + display + code; never touches the standard outputs |
| 7 | Review programs | `human` (`type: review`) | Review just the drafted custom programs. Approve → assemble; Request Changes → back to Draft custom with the comment |
| 8 | Assemble ARD + Traceability | `script` (R) | Coverage gate; consolidate `ard.csv`; write results back into the Reporting Event; build `traceability.html`; `manifest.json` |
| 9 | Propose skill lesson | `agent` + `propose-skill-lesson` skill | **Self-learning loop.** Distil this run's reviewer feedback (`review_feedback.jsonl`) into a durable, append-only lesson for the `draft-custom-programs` skill. First-pass approval (no revisions) ⇒ no lesson |
| 10 | Open skill-lesson PR | `script` (py) | `open_skill_pr.py`: append the lesson to `draft-custom-programs/references/lessons-learned.md` and open a PR against the skill repo. No lesson ⇒ no PR, clean exit |

## Self-learning loop (steps 9–10)

The drafted-programs review is not thrown away. Each time the reviewer clicks
**Request Changes** on step 7, step 6 (`draft-custom`) appends the comment to
`/workspace/review_feedback.jsonl`. After the run is approved and packaged, the
loop turns that feedback into durable skill guidance:

- **Propose skill lesson** (agent, `propose-skill-lesson` skill) reads
  `review_feedback.jsonl`, the approved programs, and the current
  `lessons-learned.md`, and distils **skill-general** lessons — the guidance that
  would have made the agent draft it right the first time. It emits *only a new
  append block* (never rewrites the file): `{ hasLessons, lessonAppendMarkdown,
  prTitle, prBody, summary }`.
- **Open skill-lesson PR** (script, `open_skill_pr.py`) fresh-clones `SKILL_REPO`,
  **deterministically appends** the block to
  `plugins/cdisc-case-3/skills/draft-custom-programs/references/lessons-learned.md`,
  branches `skill-lesson/<runId>`, commits as `Mediforce Bot`, pushes, and opens a
  PR against `main`. A maintainer reviews and merges; the next run reads the
  merged lesson before drafting.

The loop is **append-only** (mirrors the landing-zone `propose-rules` pattern):
the agent proposes only a new block, the script only appends, and existing lessons
are never edited by the workflow — the PR review is the human gate. A first-pass
approval with no revisions produces `hasLessons: false` and opens no PR. No
`workspace.remote` is used; the PR step self-clones, so the deterministic pipeline
(steps 1–8) is untouched.

Output contracts:

| Step | `/output/result.json` shape |
|------|------------------------------|
| `propose-skill-update` | `{ hasLessons: bool, lessonAppendMarkdown: string, prTitle: string, prBody: string, summary: string }` |
| `open-skill-pr` | `{ prCreated: bool, prUrl: string\|null, branch: string\|null, reason: string\|null }` |

## Two-mode execution (the design fact)

- **Standard safety outputs** (demographics, overall AE, AE by SOC/PT, vitals) →
  the deterministic **recipe library** (`container/recipes/recipes.R`), built on
  `cards`/`cardx`/`gtsummary`. The agent only supplies bindings; the executing
  code is fixed and validated. "Almost all safety outputs for free."
- **Custom efficacy outputs** (ADAS-Cog ANCOVA, time-to-event Kaplan-Meier) →
  the agent **drafts a standalone program**, runs it, repairs until it renders,
  and a human reviews it. Even here it emits the same long-skinny ARD contract.

Because binding, classification, and the standard run are deterministic scripts,
the standard safety outputs are **reproducible by construction** — the LLM cannot
mis-bind or silently drop them, and every ARD row carries the real ARS analysis
and operation id so results write straight back into the spec. Inferential
comparison analyses (chi-square/ANOVA/Fisher) are outside the descriptive recipe
library; they are recorded as `not_computed` in `coverage.json` and shown as gaps
in the traceability graph rather than faked.

`siera` (the ARS-native CRAN package) is deliberately **not** used — it is
pre-1.0 and its back end is not production-grade (per practitioner review). The
agent drafts analysis R directly on `cards`/`cardx` instead. See PLAN-3 §3.

## The long-skinny ARD contract

Every output — recipe-driven or agent-drafted — writes
`/workspace/ard/<outputId>.csv` with:

```
output_id, analysis_id, operation_id, group_var, group_level,
variable, variable_level, stat_name, stat_label, stat_raw, stat_fmt
```

`package.R` consolidates all of these into one `/output/ard.csv` (the reusable,
loadable results-by-row frame) and writes each value back into the matching
`Analysis.results[]` of `reporting_event_with_results.json` — spec in, completed
spec out, one CDISC artifact.

## Run outputs (`/output`)

| File | What it is |
|------|-----------|
| `traceability.html` | **interactive** Objective → Endpoint → Output → Analysis → Method → ADaM graph, built by `build_trace.py` from this run's artifacts (click-to-trace lineage, standard/custom modes, gap detection). Open standalone at `viz/traceability.html`. |
| `traceability_table.html` | the detailed row view: every output cell → analysis → ADaM variable → population → SAP reference, stamped with ARS ids |
| `ard.csv` | all per-output ARDs consolidated into one long-skinny results-by-row frame |
| `reporting_event_with_results.json` | the ARS spec with results written back into `Analysis.results[]` |
| `manifest.json` | study id, counts, standard/custom split, repairs, coverage pass/fail, per-output lineage |
| `tfl/`, `ard/` | the rendered displays and per-output ARDs |

## Layout

```
container/stage_inputs.py          step 2 (resolve uploaded-or-bundled inputs)
container/bind_validate.py         step 3 (deterministic ARS->ADaM binding; gaps -> unbound.json)
container/classify_outputs.py      step 4 (deterministic classify + resolved recipe plan)
container/run_standard.R           step 5 (dumb executor of the recipe plan; no LLM)
container/recipes/recipes.R        the validated standard-output recipe library
container/draft_custom.R           the WORKING reference the draft-custom AI step adapts (ANCOVA + KM)
container/package.R                step 8 (coverage gate + ard.csv + write-back + traceability)
container/build_trace.py           builds the interactive /output/traceability.html from run artifacts
container/open_skill_pr.py         step 10 (append the distilled lesson to lessons-learned.md; open the skill PR)
plugins/cdisc-case-3/skills/draft-custom-programs/SKILL.md   step 6 skill (the AI value-add, custom only)
plugins/cdisc-case-3/skills/draft-custom-programs/references/lessons-learned.md   append-only feedback the skill reads before drafting
plugins/cdisc-case-3/skills/propose-skill-lesson/SKILL.md    step 9 skill (distil review feedback into a durable lesson)
tests/                             behavior test for open_skill_pr.py (+ TEST_SUMMARY.md)
viz/                               interactive traceability graph (template + shared graph builder); see viz/README.md
fixtures/reporting_event.json      bundled CDISCPILOT01 ARS (5 safety + 2 efficacy outputs; all in the LOPA)
fixtures/adam/*.csv                bundled CDISCPILOT01 ADaM
fixtures/usdm_trace.json           bundled USDM objectives/endpoints + endpoint->output map (the traceability graph's USDM half)
fixtures/ars/ars_ldm.schema.json   pinned ARS v1.0 JSON schema
fixtures/curate_fixture.py         how the bundled Reporting Event was curated (provenance)
Dockerfile                         golden image + cards/cardx/gtsummary/survival/emmeans (+ COPY viz/)
src/cdisc-case-3.wd.json           the workflow definition (decomposed, single-responsibility steps)
```

The bundled Reporting Event is the official CDISC ARS v1 **Common Safety
Displays** example (CDISCPILOT01), results stripped, plus two authored efficacy
outputs for the custom path — see `fixtures/curate_fixture.py`.

## Key wiring (mirrors cdisc-case-1)

- **Image** built lazily from each step's `repo`+`commit`+`dockerfile`+`repoAuth`
  (HTTPS-token clone). Skills read at run time from `externalSkillsRepo` +
  `skillsDir` — not baked into the image.
- **Downloadable artifacts** go to `/output`; `/workspace` passes data between
  steps.
- **Review step** routes `approve → assemble-trace`, `revise → draft-custom` (with
  the reviewer comment), mirroring the golden-standard-workflow review shape.

## Secrets (on the target instance)

| Secret | Used by |
| ------ | ------- |
| `GITHUB_TOKEN` | image build + skill clone (all container/agent steps); **also** the `open-skill-pr` step to clone `SKILL_REPO` and open the lesson PR — needs `contents:write` + `pull-requests:write` |
| `OPENROUTER_API_KEY` | the `draft-custom` and `propose-skill-update` agent steps |

Non-secret step env: `open-skill-pr` sets `SKILL_REPO=vedhav/cdisc-case-3` (the
repo the `draft-custom-programs` skill lives in, where the lesson PR is opened).

## Runbook

```bash
cd /Users/vedha/Repo/cdisc-case-3
git init && git add -A && git commit -m "cdisc-case-3: ARS Reporting Event -> traceable TFLs"
gh repo create cdisc-case-3 --public --source=. --push
git rev-parse HEAD    # set this SHA into every commit field + externalSkillsRepo in src/cdisc-case-3.wd.json

docker build -t mediforce-agent:cdisc-case-3 .   # needs mediforce-golden-image

BASE=https://cdisc.mediforce.ai/
MEDIFORCE_API_KEY=$(cat ~/.config/mediforce/cdisc-key) \
pnpm exec mediforce workflow register --file=src/cdisc-case-3.wd.json --namespace=cdisc --base-url=$BASE

MEDIFORCE_API_KEY=$(cat ~/.config/mediforce/cdisc-key) \
pnpm exec mediforce run start --workflow="Use Case 3: AI-Driven Tables, Figures, and Listings (TFL) Generation" --namespace=cdisc --base-url=$BASE
```

Complete **Provide inputs** in the UI (leave empty for the bundled CDISCPILOT01).
Steps 2–8 run automatically (pausing only at **Review programs** for the human
verdict); the TFLs, `ard.csv`, `traceability.html`, and
`reporting_event_with_results.json` appear as downloads on **Assemble ARD +
Traceability**.

> After changing any script/skill/fixture, re-pin: `git rev-parse HEAD` and set
> that SHA into `externalSkillsRepo.commit` and every step's `commit` in
> `src/cdisc-case-3.wd.json` (the image + skills are cloned at that commit).
