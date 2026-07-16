---
name: traceability-builder
description: "Build an interactive, self-contained HTML traceability explorer that links the full clinical-deliverable chain Objective -> Endpoint -> SDTM domain -> ADaM dataset -> TLF, with the Analysis Results Data (ARD) as the connective data layer. Assembles a node/edge graph from the pipeline artifacts (study-model.json, tlf-plan.json, analysis-spec.json, adam-spec.json) and per-table outputs (generated.md, ard.json, generate.R), then emits ONE standalone .html file (vanilla JS + SVG, zero external libraries/CDN/fonts) with an interactive node graph, click-to-highlight lineage, per-node detail panels, status badges, filters and search. Use this skill when the user wants to SEE how outputs trace back to objectives/endpoints and forward to their data — phrases like 'traceability', 'traceability matrix', 'lineage', 'objective-to-TLF', 'end-to-end trace', 'where does this table come from', 'ARD explorer', 'deliverables dashboard', 'traceability explorer', 'link objectives to tables', 'coverage of endpoints', 'which endpoints have no output'. This is a reporting/visualization layer over an already-run Protocol->TLF pipeline; it reads existing artifacts and never recomputes statistics."
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
- Where is the chain **solid vs broken** — which deliverables were **generated**, which are
  **blocked**, need **clarification**, or are waiting on an **unresolved endpoint**?

The hero is an **interactive node graph** laid out as a convergent pipeline
(Plan -> Deliverable -> Data): objectives and endpoints on the left, the TLF deliverables in the
center, and the ADaM/SDTM data provenance on the right. Clicking any node lights its **full directed
lineage** across every tier and opens a **detail panel**; for a TLF the panel embeds the rendered
table, its status, the method, and collapsible ARD + generation code.

This is a **read-only reporting layer**. It never recomputes a statistic — every number shown is the
one already produced by `tlf-generator`.

```
study-model + tlf-plan + analysis-spec + adam-spec + per-table outputs (md/ard/R)
        │
        ▼
 [traceability-builder]  ──►  assemble graph JSON (nodes + edges + status)  ──►  ONE self-contained .html
```

## Two modes — render vs assemble

- **Render mode (the cdisc-case-3 workflow — default when it applies).** A deterministic
  step (`assemble-trace-graph` / `build_trace_graph.py`) has already built the authoritative
  graph model at **`/workspace/trace_graph.json`**, conforming to `references/graph-data-schema.md`.
  When that file exists, **read it and render only** — do NOT recompute nodes, edges, status,
  coverage, or the issues feed (the numbers are the proof and must stay deterministic). Skip
  Workflow steps 1–5 below; go straight to step 6 (Emit) and step 7 (Verify), consuming the
  `study`/`counts`/`status`/`issues`/`nodes`/`edges` object as-is. Per-TLF `generatedMd` /
  `ardJson` / `generateR` are already embedded in each TLF node's `meta`.
- **Assemble mode (standalone use).** When no `trace_graph.json` exists, run the full
  Workflow (steps 1–7) to assemble the model from the pipeline artifacts, then render.

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
| Per-table outputs | `outputs/<study>-outputs/tlf/<id>/` | `<id>.generated.md` (rendered TLF, embedded), `ard.json` (ARD), `generate.R` (code) |
| Issues (optional) | `outputs/<study>-outputs/tlf/issues.md` | Free-text data-quality / provenance notes from `tlf-generator`, if present — folded into the issues feed (Workflow 5) |

The ADaM spec's `variables[]` (name + `role`/derivation) and `parameters[]` (`paramcd`, `param`,
`note`) are the source for variable-level traceability (Workflow 4/6).

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
- **Issues surfaced**: a dedicated, collapsible **Issues panel** aggregates every problem (blocked
  tables, unresolved endpoints, absent domains, coverage gaps) as a clickable list that focuses the
  offending node; messages are built from data, never hard-coded (Workflow 5). Nodes with an issue
  also carry an on-graph warning marker.
- **Meaningful labels**: every node face shows a human-readable descriptor (e.g. an endpoint reads
  "ADAS-Cog(11) · Wk24", not just "END1"), with the full text in the panel + a hover tooltip.
- **Variable-level depth**: ADaM and SDTM detail panels drill down to variables / PARAMCDs and their
  cross-domain sources, and an ADaM node can expand into variable sub-nodes (Workflow 4/6).

## Workflow

1. **Read** the four spec JSONs and walk the `tlf/<id>/` tree for each table's
   `generated.md`, `ard.json`, and `generate.R` (code may also live in a shared
   `tlf/code/` runner — resolve by a small candidate list).
2. **Classify status** per TLF from the **plan** (`status` / `status_reason`) and whether its outputs
   exist: `generated` (a `.generated.md` was produced), `blocked`, or `needs-clarification`. Endpoint
   nodes carry their resolution status from the study model (`resolved` / `unresolved_endpoints`).
3. **Derive a meaningful label** for every node (see `references/graph-data-schema.md` "Node labels").
   Keep `label` as the short code chip (`OBJ1`, `END1`, `T-14-3.01`, `ADQSADAS`, `QS`) but set
   `sublabel` to something a reader understands without clicking: Endpoint -> `parsed.measure` + short
   timepoint (e.g. "ADAS-Cog(11) · Wk24"); Objective -> a concise descriptor from its `text` (or its
   child endpoints' measures). Full text stays in the panel + a hover tooltip. Fall back gracefully
   when `parsed`/`text` is missing (use `text` truncated, then `level`).
4. **Assemble the graph** — nodes and edges per the model in
   `references/graph-data-schema.md`. Six node types (Objective, Endpoint, Regulatory, TLF, ADaM,
   SDTM); edges: `obj-end`, `end-tlf`, `reg-tlf`, `tlf-adam`, `adam-sdtm`, plus dashed `tlf-sdtm`
   for domains a table *declares* but has no derived ADaM bridge to (e.g. blocked/clarify tables).
   Keep unresolved endpoints and blocked/needs-clarification TLFs as first-class visible nodes.
   **Enrich ADaM nodes** with their full `variables[]` (name + role/derivation) and `parameters[]`
   (PARAMCD + label + note) from the ADaM spec, and record each variable's source domain(s) — from
   the dataset `sdtm_source` and any domain named in the `role`/derivation text — so the detail panel
   and the optional variable drill-down (step 6) have data to show.
5. **Build the issues feed** — assemble a top-level `issues[]` (schema in
   `references/graph-data-schema.md`) from DATA, never hard-coded per node: every `blocked` /
   `needs-clarification` TLF (message = its `status_reason`), every unresolved endpoint, every
   `absent` SDTM domain (name the tables it blocks), coverage gaps (objectives/endpoints with no
   TLF), and any lines from `issues.md` if present. Each issue references its node id so the UI can
   focus it, and flags that node with a warning marker.
6. **Emit** the standalone HTML: inject the graph JSON (escape `</` as `<\/`), then the static
   template (head + CSS) and the app JS. Lay out by tier (layered columns), render SVG, wire the
   interactions: an aggregated **Issues panel** (severity tally + clickable rows that focus the
   node), on-node warning markers, meaningful labels, and variable-level ADaM/SDTM detail panels
   (Variables + PARAMCD tables; an ADaM node can **expand** into variable sub-nodes joined by
   `var-sdtm` edges to their source domains). Structure the TLF detail so a future **Phase 2**
   (cell -> ARD drill-down) can slot in without reshaping the node model.
7. **Verify** by opening the file in a browser: confirm no console errors; lineage highlight works;
   the Issues panel lists every problem and clicking a row focuses its node; Objective/Endpoint faces
   read meaningfully; an ADaM panel shows its Variables + PARAMCDs and expands to variable sub-nodes;
   rendered tables and collapsibles populate; and there are **zero** external network requests.

## Design notes

- **Layout is meaning**: the convergent Plan -> Deliverable -> Data pipeline reads left to right and
  every edge flows one direction, so crossings stay legible even at ~75 nodes / ~120 edges.
- **Color encodes node type** (a validated categorical palette; see the graph schema). **Status is a
  reserved palette** (never reused for a type) and always ships with an icon + label, never color
  alone — good for colorblind readers and print.
- **Issues are visible, not buried, and never hard-coded**: every problem appears both in the
  aggregated Issues panel and as an on-node warning marker (icon + label). The message text is always
  derived from data (`status_reason`, `absent`, unresolved endpoints, coverage gaps) so it
  generalizes to any study — do NOT special-case a particular node's message in the JS.
- **The node face must be legible on its own**: show a meaningful `sublabel` (measure + timepoint,
  short objective descriptor), keep the code as a mono chip, and put the full text in the panel + a
  `<title>` hover tooltip. A reader should grasp what a node is without clicking.
- **Variable-level stays a drill-down**: keep the hero graph at entity level; surface variable /
  PARAMCD detail in the ADaM/SDTM panels and behind an opt-in node expansion, so the main view stays
  legible while the depth is one click away.
- **Type wears text tokens, never the series color**: node labels/values stay in ink; the colored
  box/rail carries identity.
- Use the domain's real vernacular as structure — monospace dataset codes (`ADQSADAS`), section
  numbers (`14-3.01`), regulatory citations (`ICH E3 §11.1`) — rather than decorative ornament.

## Reference files

- `references/graph-data-schema.md` — the nodes/edges/status JSON model (field by field), the tier
  layout, the lineage-traversal rule, and the self-contained-HTML / CSP constraints. Read it before
  regenerating for a new study.
