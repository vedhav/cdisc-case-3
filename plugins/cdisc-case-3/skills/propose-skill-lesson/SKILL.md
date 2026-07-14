---
name: propose-skill-lesson
description: "Generalized self-learning loop for the CDISC Case 3 pipeline. Distil durable, per-skill lessons from the reviewer feedback captured during a run across ALL THREE review gates (plan / specs / TLFs). Reads /workspace/review_feedback.jsonl — one object per revise, each tagged with the skill it targets (tlf-planner, tlf-analysis-spec, tlf-generator) — plus the approved artifacts and each target skill's current references/lessons-learned.md; proposes an append-only markdown block per revised skill that would have produced an approvable result first pass. Writes { hasLessons, lessons: [ { skill, lessonAppendMarkdown } ], prTitle, prBody, summary } to /output/result.json. Append-only — never rewrites existing lessons. Triggers: 'learn from review feedback', 'propose skill lessons', 'codify reviewer comments into the skills', 'self-learning loop'. Used by the propose-skill-update agent step after the pipeline's reviews."
---

# propose-skill-lesson — turn this run's review feedback into durable skill guidance

## Purpose

The pipeline has three human review gates, each of which can send the run back
to the agent step that produced the artifact:

| Review gate | Sends back to | Skill that gets the lesson |
|---|---|---|
| **review-plan** | plan-tlfs | `tlf-planner` |
| **review-specs** | build-specs | `tlf-analysis-spec` |
| **review-tlfs** | generate-tlfs | `tlf-generator` |

Each time a reviewer clicks **Request Changes**, the target agent step captures
the comment into `/workspace/review_feedback.jsonl`, **tagged with its skill**.
Those comments are the exact places a skill fell short — the guidance that, had
it been in the skill, would have produced an approvable artifact on the first
pass.

This skill reads that feedback once, after the run's artifacts are approved, and
distils it into small, durable, **skill-general** lessons — grouped by skill. It
does **not** rewrite any skill. It emits *append-only* markdown blocks that the
next step (`open-skill-pr`) appends to each target skill's
`references/lessons-learned.md` and opens as one PR. A human reviews and merges;
the next run reads the merged lessons before working.

## Inputs

- **`/workspace/review_feedback.jsonl`** — one JSON object per line, appended by
  an agent step on each revise re-entry:
  `{ "skill": "<skill-id>", "iteration": N, "comment": "<reviewer comment>" }`.
  **This is the signal.** If the file is absent or empty, every gate approved
  first pass — nothing to learn. Emit `hasLessons: false` (see Empty case).
- **The approved artifacts** in `/workspace` and `/output` (e.g. `tlf-plan.json`,
  `analysis-spec.json`, `adam-spec.json`, `/workspace/code/*.R`, rendered TLFs) —
  ground each lesson in what the *accepted* artifact did differently from the
  first draft.
- **`/output/input.json`** — engine step input; carries `runId`.
- **Each target skill's current lessons file** —
  `plugins/cdisc-case-3/skills/<skill>/references/lessons-learned.md` from the
  checked-out skills repo — so you do **not** re-propose an existing lesson. If a
  file is missing, proceed (open-skill-pr creates it); the PR review is the
  backstop against duplicates.

## Output — `/output/result.json`

```json
{
  "hasLessons": true,
  "lessons": [
    {
      "skill": "tlf-generator",
      "lessonAppendMarkdown": "\n### 2026-07-14 — run <runId>\n\n**Context:** <output id / model shape>\n\n- **Lesson:** <imperative, skill-general guidance>. **Why:** <the review comment, one line>.\n"
    }
  ],
  "prTitle": "skill lessons from run <runId> review (<skill list>)",
  "prBody": "<markdown PR body — see below>",
  "summary": "One sentence: what the skills will now do better."
}
```

- Each `lessons[].lessonAppendMarkdown` is *only the new block* for that skill —
  never the whole file. Start it with a leading newline and a dated `###`
  heading so appended blocks stay separated. `open-skill-pr` appends it verbatim
  to that skill's lessons file; you own its exact bytes.
- One entry per revised skill (0–3 lessons per skill). Skip skills with no
  general lesson.
- Emit `hasLessons: false` and `lessons: []` when there is nothing worth
  codifying (see Empty case).

## Workflow

### Step 1 — Read & group the feedback
Read `/workspace/review_feedback.jsonl`. If missing/empty → Empty case. Group the
`(iteration, comment)` lines **by `skill`**. Read the relevant approved artifacts
so you understand what the accepted version did that the first draft did not.

### Step 2 — Decide what is a durable lesson (per skill)
A comment becomes a lesson only when it is **general** — it would help the agent
on a *future, different* study/output, not just this run. Good lessons: a
recurring planning/modelling/binding mistake (wrong population source, wrong
contrast, missing covariate, wrong PARAMCD/AVISIT filter, a missing scaffolding
table, a display convention), or a contract/scope violation. Skip run-specific
data corrections, one-off wording nits, and anything already in that skill's
lessons file. Aim for 0–3 lessons per skill; fewer, sharper lessons win.

### Step 3 — Write each lesson
One imperative bullet the future agent can act on, plus a one-line `Why` naming
the review comment. Phrase as a rule, not a narrative. Ground it in the accepted
artifact.

### Step 4 — Compose the PR body
```markdown
## Summary

<one paragraph: run <runId> took <N> revision(s) across <gates>; these lessons
codify the feedback so the next run gets it right the first time.>

## Proposed lessons

### tlf-generator
- <lesson> — from review comment: "<comment>"

### tlf-analysis-spec
- <lesson> — ...

## Source run
- Run: `<runId>`
- Revised skills / gates: `<...>`
- Revisions before approval: `<N>`

## Review checklist
- [ ] Each lesson is skill-general, not run-specific
- [ ] No duplicate of an existing lesson in that skill's lessons-learned.md
- [ ] Guidance is actionable at work time, not a post-hoc narrative
```

### Step 5 — Write `/output/result.json`
Write the object above. Set `hasLessons` to whether `lessons` has ≥1 entry.

## Empty case (valid, common)
No `review_feedback.jsonl`, empty file, or nothing survives Step 2:
```json
{ "hasLessons": false, "lessons": [], "prTitle": "", "prBody": "", "summary": "No revisions this run (or no general lesson) — nothing to codify." }
```
`open-skill-pr` sees `hasLessons: false` and opens no PR.

## Boundaries
- **Append-only.** Propose only new blocks; never edit/delete existing lessons.
- **General, not run-specific.** A lesson must help a future, different run.
- **Ground it in the accepted artifact.** Don't invent guidance the feedback
  didn't ask for.
- **No fabrication.** Every lesson traces to a real line in review_feedback.jsonl.
- **Empty is fine.** First-pass approvals produce no lessons and no PR.
