---
name: traceability-builder
description: "Build an interactive, self-contained HTML traceability explorer that links the full clinical-deliverable chain Objective -> Endpoint -> SDTM domain -> ADaM dataset -> TLF, with the Analysis Results Data (ARD) as the connective data layer. Assembles a node/edge graph from the pipeline artifacts (study-model.json, tlf-plan.json, analysis-spec.json, adam-spec.json) and per-table outputs (generated.md, diff-report.txt, ard.json, generate.R, the T9 scorecard), then emits ONE standalone .html file (vanilla JS + SVG, zero external libraries/CDN/fonts) with an interactive node graph, click-to-highlight lineage, per-node detail panels, status badges, filters and search. Use this skill when the user wants to SEE how outputs trace back to objectives/endpoints and forward to their data — phrases like 'traceability', 'traceability matrix', 'lineage', 'objective-to-TLF', 'end-to-end trace', 'where does this table come from', 'ARD explorer', 'deliverables dashboard', 'traceability explorer', 'link objectives to tables', 'coverage of endpoints', 'which endpoints have no output'. This is a reporting/visualization layer over an already-run Protocol->TLF pipeline; it reads existing artifacts and never recomputes statistics."
---

# Traceability Builder

## Purpose

Turn the artifacts a Protocol->TLF run leaves on disk into a single **interactive traceability
explorer** — one self-contained HTML file a reviewer opens (or publishes as an Artifact) to answer,
for any study:

- Does every **objective** reach a **deliverable**, and does every deliverable trace back to an
  **objective or a regulatory rule**?
- What is the **data lineage** of a given table — which **ADaM** datasets and **SDTM** domains feed
  it, with the **ARD** as the connective layer?
- Where is the chain **solid vs broken** — which outputs match the reference, which are partial,
  **blocked**, or waiting on an **unresolved endpoint**?

The hero is an **interactive node graph** laid out as a convergent pipeline
(Plan -> Deliverable -> Data): objectives and endpoints on the left, the TLF deliverables in the
center, and the ADaM/SDTM data provenance on the right. Clicking any node lights its **full directed
lineage** across every tier and opens a **detail panel**; for a TLF the panel embeds the rendered
table, the match %/status, the method, and collapsible ARD + generation code.

This is a **read-only reporting layer**. It never recomputes a statistic — every number shown is the
one already produced by `tlf-generator`.

```
study-model + tlf-plan + analysis-spec + adam-spec + per-table outputs (md/diff/ard/R) + T9 scorecard
        │
        ▼
 [traceability-builder]  ──►  assemble graph JSON (nodes + edges + status)  ──►  ONE self-contained .html
```

## When to use

Use after a pipeline run (Stages 1-4) has produced a `tlf/` output tree. Trigger on any request to
*visualize, audit, or explain* traceability/lineage/coverage — not to plan or generate outputs.

Do **not** use it to generate TLFs (that is `tlf-generator`), to plan outputs (`tlf-planner`), or to
derive ADaM (`sdtm-to-adam`). If those artifacts are missing, build them first, then run this.

## Inputs (all read from disk — never fabricated)

| Artifact | Path (Pilot example) | Supplies |
|---|---|---|
| Study model | `testing-tlf-planner/study-model.json` | Objectives (with `level`) + endpoints; objective->endpoint links; endpoint `resolved` flag; `unresolved_endpoints` |
| TLF plan | `testing-tlf-planner/tlf-plan.json` | TLF candidates: `traces_to` (objective_ids / endpoint_ids / regulatory_rule), `category`, `type`, `final_id`, `status`, `status_reason`, `data_requirements` |
| Analysis spec | `testing-tlf-planner/analysis-spec.json` | Per-TLF `method`, `analysisSet`, `dataSubset` (dataset), `purpose` |
| ADaM spec | `testing-tlf-planner/adam-spec.json` | `datasets[]` with `sdtm_source` (ADaM->SDTM) and `used_by_tables` (ADaM->TLF); variables, parameters, derivation requirements |
| Per-table outputs | `outputs/<study>-outputs/tlf/<id>/` | `<id>.generated.md` (rendered TLF, embedded), `diff-report.txt` (match rate), `ard.json` (ARD), `generate.R` (code) |
| Scorecard | `outputs/<study>-outputs/tlf/T9-scorecard.md` | Per-table match % and status classification -> badges |

Paths are conventions, not hard-coded: the assembler locates artifacts by the study's output layout.
Every field is optional at the leaf level — a missing `generate.R`, a blocked table with only a
`.generated.md`, or an unresolved endpoint must still appear (clearly marked), never dropped.

## Output

A single file: `outputs/<study>-outputs/traceability/<study>-traceability.html`.

- **Self-contained**: the graph model is embedded inline as JSON in a `<script type="application/json">`
  block; every TLF's rendered table, ARD, and code is embedded; all CSS/JS is inline. **Zero** external
  requests (no CDN, no web fonts, no remote images) so it opens offline and can publish as an Artifact.
- **Interactive**: pan / zoom / drag; click-to-highlight directed lineage with a dimmed rest; type +
  status filters; id/title search; a summary bar of entity counts and status tallies; light/dark
  theme-aware; responsive with wide content scrolling inside its own container.

## Workflow

1. **Read** the four spec JSONs, the scorecard, and walk the `tlf/<id>/` tree for each table's
   `generated.md`, `diff-report.txt`, `ard.json`, and `generate.R` (code may also live in a shared
   `tlf/code/` runner — resolve by a small candidate list).
2. **Classify status** per TLF from the T9 scorecard (`match` / `partial` / `blocked` /
   `needs-clarification`); parse the numeric match rate from `diff-report.txt` where present.
3. **Assemble the graph** — nodes and edges per the model in
   `references/graph-data-schema.md`. Six node types (Objective, Endpoint, Regulatory, TLF, ADaM,
   SDTM); edges: `obj-end`, `end-tlf`, `reg-tlf`, `tlf-adam`, `adam-sdtm`, plus dashed `tlf-sdtm`
   for domains a table *declares* but has no derived ADaM bridge to (e.g. blocked/clarify tables).
   Keep unresolved endpoints and blocked/needs-clarification TLFs as first-class visible nodes.
4. **Emit** the standalone HTML: inject the graph JSON (escape `</` as `<\/`), then the static
   template (head + CSS) and the app JS. Lay out by tier (layered columns), render SVG, wire the
   interactions. Structure the TLF detail so a future **Phase 2** (cell -> ARD drill-down) can slot in
   without reshaping the node model.
5. **Verify** by opening the file in a browser: confirm no console errors, lineage highlight works,
   the rendered tables and collapsibles populate, and there are **zero** external network requests.

## Design notes

- **Layout is meaning**: the convergent Plan -> Deliverable -> Data pipeline reads left to right and
  every edge flows one direction, so crossings stay legible even at ~75 nodes / ~120 edges.
- **Color encodes node type** (a validated categorical palette; see the graph schema). **Status is a
  reserved palette** (never reused for a type) and always ships with an icon + label, never color
  alone — good for colorblind readers and print.
- **Type wears text tokens, never the series color**: node labels/values stay in ink; the colored
  box/rail carries identity.
- Use the domain's real vernacular as structure — monospace dataset codes (`ADQSADAS`), section
  numbers (`14-3.01`), regulatory citations (`ICH E3 §11.1`) — rather than decorative ornament.

## Reference files

- `references/graph-data-schema.md` — the nodes/edges/status JSON model (field by field), the tier
  layout, the lineage-traversal rule, and the self-contained-HTML / CSP constraints. Read it before
  regenerating for a new study.
