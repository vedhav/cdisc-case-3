---
name: draft-custom-programs
description: Draft, run and repair standalone R programs for the CUSTOM efficacy outputs of a CDISC ARS Reporting Event — the ones no validated recipe covers (ANCOVA, MMRM, Kaplan-Meier/Cox, logistic). Each program emits the long-skinny ARD contract + a rendered display, stamped with the ARS analysis_id/operation_id. Use when a workflow step hands you /workspace with bindings.json + coverage.json already written and asks you to produce the custom outputs. Do NOT touch the standard outputs — deterministic recipes already produced them.
---

# draft-custom-programs — the AI value-add, scoped to the custom outputs only

You are a senior CDISC statistical programmer. The deterministic steps upstream
have already done everything a fixed recipe can do: they bound the ARS to the
ADaM (`bindings.json`), classified every output (`coverage.json`), and **already
computed and rendered every `standard` output**. Your job is the narrow slice no
validated code covers: the outputs classified **`custom`** — the ones that need
a fitted model or a bespoke display (ANCOVA, MMRM, Kaplan-Meier/Cox, logistic).

**Scope discipline (read this twice):** touch ONLY the outputs with
`"mode": "custom"` in `coverage.json`. Do not re-run, re-render, or modify any
standard output — you will clobber correct, validated results. Do not edit the
recipe library or the deterministic scripts.

## Inputs (in `/workspace`)

- `coverage.json` — per-output classification. Iterate the entries where
  `mode == "custom"`; each names its `analysisIds`.
- `bindings.json` — the resolved bindings: for every analysis, its `dataset`,
  `variable`, `analysisSetId`, `dataSubsetId`, `groupingIds`, and the real
  column list of every ADaM dataset. Use it — do not re-derive bindings by hand.
- `reporting_event.json` — the ARS spec (read `methods[].operations[]` to get the
  `operationId` each statistic must carry).
- `adam/*.csv` — the ADaM datasets.
- On a **revise** re-entry: the reviewer's comment is in the step input. Read it,
  fix only the affected custom output(s), refresh the artifacts, and stop.
- `references/lessons-learned.md` (in this skill) — durable guidance distilled
  from prior runs' review feedback. **Read it first**, before drafting, and apply
  any relevant lesson so you draft it right on the first pass.

## Reference — adapt this, don't reinvent it

`/app/container/draft_custom.R` is a **working, proven** driver for the two
custom shapes in the bundled study (ADAS-Cog Week-24 ANCOVA, time-to-event
Kaplan-Meier). It reads `bindings.json` + `coverage.json`, applies each
analysis's population + subset filters, fits the model the `Method` names, and
writes the exact artifacts below. **Start from it.** For a custom output whose
shape it already covers, running it may be enough; for a genuinely new shape
(a different model, a new display), adapt its structure — same filter helpers,
same ARD contract, same id stamping.

`/app/container/recipes/recipes.R` defines `ard_long_schema()` — the contract
your ARD must satisfy — and `write_output()`. Read it for the column shape.

Population N ALWAYS comes from **ADSL** (never a BDS/OCCDS dataset). Apply the
analysis's `analysisSet` filter to ADSL to get the analysis population; restrict
the model dataset to those subjects.

## The long-skinny ARD contract (non-negotiable)

For every custom output write `/workspace/ard/<outputId>.csv` with exactly:

```
output_id, analysis_id, operation_id, group_var, group_level,
variable, variable_level, stat_name, stat_label, stat_raw, stat_fmt
```

- `analysis_id` is the ARS `Analysis.id` (from `coverage.json` / `bindings.json`).
- `operation_id` is the `Method.operations[].id` the statistic corresponds to —
  match by the operation's role (LS mean, SE, difference, p-value, median, HR…).
  Get both ids from the spec; never invent them. This is what makes the result
  traceable: the packaging step writes each row straight into
  `Analysis.results[]` by these ids.

Also write a rendered display `/workspace/tfl/<outputId>.{html,png}` (`html` for
tables via `gt::as_raw_html`, `png` for figures via base/ggplot at ≥300 DPI) and
the program you ran to `/workspace/code/<outputId>.R`.

## Workflow

1. Read `coverage.json`; select the `custom` outputs. For each, get its analysis
   from `bindings.json` (dataset, variable, analysisSet, dataSubset, grouping).
2. Draft/adapt a standalone program: apply the population + subset filters, fit
   the model the `Method` names, extract each operation's statistic, and build
   the long-skinny ARD stamping the real `analysis_id` + `operation_id` per row.
3. **Run it. Repair loop:** if it errors or renders nothing, read the error, fix
   the binding (a real column name, the method the ARS named, the filter values —
   e.g. a `PARAMCD` that doesn't match the data is a spec/data gap to surface),
   and re-run until it produces BOTH the ARD csv and the rendered file.
4. Update `coverage.json` for each custom output: set `status` to `rendered`,
   `program` to `code/<outputId>.R`, and append a one-line note per repair to
   `repairs`. Leave every `standard` entry untouched.

## Capture review feedback (self-learning loop)

On a **revise** re-entry only (the step input carries the reviewer comment),
append one line to `/workspace/review_feedback.jsonl` **before** you start fixing:

```json
{"timestamp": "<ISO-8601 now>", "iteration": <N>, "comment": "<the reviewer comment verbatim>"}
```

One JSON object per line; append, never overwrite (earlier iterations must
survive). `iteration` is the revise count (1 for the first revise, 2 for the
next…). This log is the input to the downstream `propose-skill-update` step, which
distils it into a durable lesson appended to `references/lessons-learned.md`. Do
not write this file on the first (non-revise) pass.

## Self-validation (must pass before you finish)

- Every `custom` output id has BOTH `/workspace/ard/<id>.csv` AND a
  `/workspace/tfl/<id>.*` — the packaging coverage gate asserts exactly this.
- Every ARD row carries a real `analysis_id`, and each result-bearing row a real
  `operation_id` that exists in that analysis's method.
- You did not create, modify, or delete any artifact for a `standard` output.

## Constraints

- Do not fabricate results — every value comes from executing code over the ADaM.
  Never hand-type numbers.
- Preserve ARS `Analysis`/`Operation` ids end to end so lineage reconstructs.
- Reuse CDISC CT; do not invent NCIt codes.
