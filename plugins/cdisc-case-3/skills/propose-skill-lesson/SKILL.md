---
name: propose-skill-lesson
description: "Distil durable lessons for the draft-custom-programs skill from the reviewer feedback captured during a run of the CDISC Case 3 workflow. Reads /workspace/review_feedback.jsonl (the reviewer comments from each revise of Review programs), the approved custom R programs, coverage.json, and the current draft-custom-programs lessons-learned.md; proposes a new append-only markdown block that would have made the agent draft it right the first time. Writes { hasLessons, lessonAppendMarkdown, prTitle, prBody, summary } to /output/result.json. Append-only — never rewrites existing lessons. Triggers: 'learn from review feedback', 'propose skill lesson', 'codify reviewer comments into the skill', 'self-learning loop for draft-custom'. Used by the propose-skill-update agent step after the human approves the drafted programs."
---

# propose-skill-lesson — turn this run's review feedback into durable skill guidance

## Purpose

The `draft-custom-programs` skill drafts the custom efficacy programs; a human
then reviews them in the **Review programs** step. Every time the reviewer clicks
**Request Changes**, `draft-custom` captures the comment into
`/workspace/review_feedback.jsonl`. Those comments are the exact places the skill
fell short — the guidance that, had it been in the skill, would have produced an
approvable program on the first pass.

This skill reads that feedback once, after the run is approved, and distils it
into a small, durable, **skill-general** lesson block. It does **not** rewrite the
skill. It emits an *append-only* markdown block that the next step
(`open-skill-pr`) appends to
`plugins/cdisc-case-3/skills/draft-custom-programs/references/lessons-learned.md`
and opens as a PR. A human reviews and merges the PR; the next run of the
workflow reads the merged lesson before drafting.

## Inputs

- **`/workspace/review_feedback.jsonl`** — one JSON object per line, appended by
  `draft-custom` on each revise re-entry:
  `{ "timestamp": "...", "iteration": N, "comment": "<reviewer comment>" }`.
  **This is the signal.** If the file is absent or empty, the run was approved
  first pass with no revisions — there is nothing to learn. Emit
  `hasLessons: false` and stop (see Empty case).
- **`/workspace/code/*.R`** — the approved custom programs. Use them to ground a
  lesson in what the final, accepted program actually did differently from the
  first draft (the concrete fix the feedback was asking for).
- **`/workspace/coverage.json`** — per-output classification and `repairs` notes.
  Tells you which outputs were `custom` and what the agent had to repair.
- **`/output/input.json`** — engine step input. Carries `runId` (also in
  `variables` / env) and the flattened output of the immediately-preceding step.
  Read `steps['review-programs']` for the final verdict/comment if present.
- **The current lessons file** — read
  `plugins/cdisc-case-3/skills/draft-custom-programs/references/lessons-learned.md`
  from the checked-out skills repo so you do **not** re-propose a lesson that is
  already recorded. If you cannot locate it, proceed — the PR review is the
  backstop against duplicates.

## Output — `/output/result.json`

```json
{
  "hasLessons": true,
  "lessonAppendMarkdown": "\n### 2026-07-09 — run <runId>\n\n**Context:** <output id / model shape the feedback was about>\n\n- **Lesson:** <imperative, skill-general guidance>. **Why:** <the review comment that motivated it, one line>.\n- **Lesson:** ...\n",
  "prTitle": "draft-custom-programs: N lesson(s) from run <runId> review",
  "prBody": "<markdown PR body — see below>",
  "summary": "One sentence for the human: what the skill will now do better."
}
```

- **`lessonAppendMarkdown`** is *only the new block* to append — never the whole
  file. Start it with a leading newline and a dated `###` heading so appended
  blocks stay separated. The next step appends it verbatim; you own its exact
  bytes.
- Emit `hasLessons: false` and `lessonAppendMarkdown: ""` when there is nothing
  worth codifying (see Empty case). Every other field may be a short placeholder.

## Workflow

### Step 1 — Read the feedback

Read `/workspace/review_feedback.jsonl`. If missing or empty → Empty case. Parse
every line into a list of `(iteration, comment)`. Read the approved
`/workspace/code/*.R` and `coverage.json` to understand what the accepted program
did that the first draft did not.

### Step 2 — Decide what is a durable lesson

A comment becomes a lesson only when it is **general** — it would help the agent
on a *future, different* study/output, not just this run. Good lessons:

- A recurring modelling or binding mistake (wrong population source, wrong
  contrast, missing covariate, wrong `PARAMCD`/`AVISIT` filter, a display
  convention the reviewer insists on).
- A contract or scope violation the reviewer caught (touched a standard output,
  dropped an `operation_id`, hand-typed a number).

Skip comments that are:

- Run-specific data corrections ("this study's ADSL has a typo") — not general.
- One-off wording nits with no reusable rule.
- Anything already stated in the current `lessons-learned.md`.

Aim for **0–3** lessons. Zero is a valid outcome (Empty case). Fewer, sharper,
reusable lessons beat a long list.

### Step 3 — Write each lesson

Each lesson is one imperative bullet the future agent can act on, plus a one-line
`Why` naming the review comment that motivated it. Keep them skill-general: phrase
as a rule ("Always take population N from ADSL after applying the analysisSet
filter"), not a narrative of this run. Ground the phrasing in what the approved
program actually did.

### Step 4 — Compose the PR body

```markdown
## Summary

<one paragraph: the drafted programs for run <runId> took <N> revision(s) to
approve; these lessons codify the reviewer feedback so the next run drafts it
right the first time.>

## Proposed lessons

- <lesson 1> — from review comment: "<comment>"
- <lesson 2> — ...

## Source run

- Run: `<runId>`
- Custom outputs reviewed: `<ids from coverage.json>`
- Revisions before approval: `<N>`

## Review checklist

- [ ] Each lesson is skill-general, not run-specific
- [ ] No duplicate of an existing lesson in lessons-learned.md
- [ ] Guidance is actionable at draft time, not a post-hoc narrative
```

### Step 5 — Write `/output/result.json`

Write the object above. `lessonAppendMarkdown` is the exact block to append. Set
`hasLessons` to whether it contains at least one lesson.

## Empty case (valid, common)

No `review_feedback.jsonl`, empty file, or no comment survives Step 2:

```json
{
  "hasLessons": false,
  "lessonAppendMarkdown": "",
  "prTitle": "",
  "prBody": "",
  "summary": "No revisions this run (or no general lesson) — nothing to codify."
}
```

The `open-skill-pr` step sees `hasLessons: false` and opens no PR.

## Boundaries

- **Append-only.** Propose only a new block. Never edit or delete existing
  lessons — that is the reviewer's job on the PR.
- **General, not run-specific.** A lesson must help a future, different run.
- **Ground it in the accepted program.** Do not invent guidance the feedback did
  not ask for.
- **No fabrication.** Every lesson traces to a real line in
  `review_feedback.jsonl`.
- **Empty is fine.** First-pass approvals produce no lesson and no PR.
