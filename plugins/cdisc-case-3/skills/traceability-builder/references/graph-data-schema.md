# Traceability graph — data model & HTML constraints

This documents the JSON model the explorer consumes and the hard constraints on the emitted HTML, so
the page **regenerates for any study**, not just CDISCPILOT01. The assembler builds one object and
embeds it verbatim in `<script id="graph-data" type="application/json">…</script>`.

## Top-level object

```jsonc
{
  "study":  { "id", "name", "title", "phase" },
  "counts": { "objectives", "endpoints", "endpoints_unresolved",
              "sdtm", "sdtm_absent", "adam", "tlf", "tlf_producible" },
  "status": { "match", "partial", "blocked", "needs-clarification" },  // TLF tallies
  "nodes":  [ Node, … ],
  "edges":  [ Edge, … ]
}
```

## Node

```jsonc
{
  "id":       "obj:Objective_1",       // "<typePrefix>:<sourceId>" — globally unique
  "type":     "Objective",             // Objective | Endpoint | Regulatory | TLF | ADaM | SDTM
  "tier":     0,                        // layout column (see tiers below)
  "label":    "OBJ1",                  // short id shown in the node (mono)
  "sublabel": "Primary",               // small uppercase caption
  "title":    "To determine if …",     // full human title (panel + search)
  "status":   "match",                 // TLF only: match|partial|blocked|needs-clarification
  "unresolved": false,                  // endpoint with placeholder text, or unplanned TLF
  "absent":   false,                    // SDTM domain required but not in inventory
  "isFigure": false,                    // TLF that is a Figure (e.g. Kaplan-Meier)
  "meta":     { … }                     // type-specific payload (see below)
}
```

`id` prefixes: `obj:`, `end:`, `reg:`, `tlf:`, `adam:`, `sdtm:`. TLF node ids use the **candidate_id**
(`tlf:eff-END1-ancova-wk24-locf`) so unplanned candidates without a `final_id` still get a stable id.

### `meta` by type
- **Objective** — `level`, `description`, `text`, `endpoints[]` (endpoint ids).
- **Endpoint** — `level`, `text`, `objective` (id), `resolved`, `measure`, `measure_type`,
  `timepoints[]`, `domain_hint`.
- **Regulatory** — `standard` ("ICH E3"), `note`. A single shared source node for scaffolding outputs.
- **TLF** — `candidate_id`, `final_id`, `dir_id`, `type`, `category`, `cat_label`, `title`, `status`,
  `status_reason`, `priority`, `produced_by`, `notes[]`, `method`, `population`, `timepoint`,
  `imputation`, `subgroup`, `comparison`, `objectives[]`, `endpoints[]`, `regulatory_rule`, `adam[]`,
  `sdtm[]`, `analysisSet`, `analysisSetCond`, `dataSubset`, `purpose`,
  `match:{klass,label,cause,rate}`, and embedded raw content
  `generatedMd`, `diffReport`, `ardJson`, `generateR`, `generateRPath`, `isFigure`.
- **ADaM** — `klass`, `sdtm_source[]`, `used_by_tables[]`, `parameters[]`, `variables[]`,
  `derivation_requirements[]`.
- **SDTM** — `domain`, `label`, `absent`.

## Edge

```jsonc
{ "source": "<nodeId>", "target": "<nodeId>", "kind": "end-tlf", "dashed": false, "rule": null }
```

| kind | direction | source | built from |
|---|---|---|---|
| `obj-end`   | Objective → Endpoint | study-model `objectives[].endpoint_ids` |
| `end-tlf`   | Endpoint → TLF | tlf-plan `traces_to.endpoint_ids` |
| `reg-tlf`   | Regulatory → TLF | tlf-plan `traces_to.regulatory_rule` (rule stored on edge) |
| `tlf-adam`  | TLF → ADaM | adam-spec `datasets[].used_by_tables` (authoritative); fall back to tlf-plan `data_requirements.adam` for unplanned tables |
| `adam-sdtm` | ADaM → SDTM | adam-spec `datasets[].sdtm_source` |
| `tlf-sdtm`  | TLF → SDTM (**dashed**) | only when a table *declares* an SDTM source but has **no** ADaM bridge to it (blocked/clarify) — "declared, not derived" |

All edges flow left→right in tier order, so the graph is a legible near-DAG.

## Tiers (layout)

| tier | column | types |
|---|---|---|
| 0 | Objective | Objective |
| 1 | Endpoint / Reg. | Endpoint + the single Regulatory node (Regulatory placed first) |
| 2 | Deliverable (TLF) | TLF / Figure — the tallest column, the focal center |
| 3 | ADaM dataset | ADaM |
| 4 | SDTM domain | SDTM (present + any `absent` required domain) |

Layered layout: `x = MX + tier*COL`; within a tier, stack by a stable order and vertically center each
tier's block against the tallest column. Initial view fits the world box to the viewport. Nodes are
draggable; pan/zoom is a single `translate()+scale()` transform on the root `<g>`.

## Status model

Badges come from the **T9 scorecard** (authoritative), not from re-diffing:
`✅ match` (100% / effectively matching) · `⚠ partial` (specific ADaM-derivation gaps) ·
`⛔ blocked` (a required derivation/domain is absent) · `❓ needs-clarification` (traces to an
unresolved endpoint). Parse the numeric `match rate : NN%` from each `diff-report.txt` for the
detail panel; keep the scorecard's klass for the badge. Non-TLF nodes carry no status; a status
**filter** hides non-matching TLFs and dims upstream/data nodes that lose all visible connections.

## Lineage traversal (highlight rule)

Selecting a node highlights its **directed** lineage — *ancestors* (walk `edges` backward) ∪
*descendants* (walk forward) ∪ self — and dims the rest. This is deliberately **not** the undirected
connected component: a shared dataset like `ADSL` would otherwise pull in the whole graph. From a TLF
this yields the clean slice `Objective → Endpoint/Reg → TLF → ADaM → SDTM`; from an ADaM node it
yields "everything this dataset feeds." The panel breadcrumb renders the same lineage in reading order
`OBJ ▸ END ▸ SDTM ▸ ADaM ▸ TLF`.

## Self-contained HTML / CSP constraints (hard requirements)

The file must open offline and publish as a claude.ai Artifact, which enforces a strict CSP:

- **No external requests of any kind** — no `<script src>`, no `<link rel=stylesheet>`, no `@import`,
  no CDN, no web fonts, no remote images, no `fetch`/XHR/WebSocket. Inline all CSS and JS; use
  `system-ui` + a monospace stack (no downloaded faces); embed any raster as a `data:` URI.
- **Data embedded inline** as `<script type="application/json">`. When serializing, escape `</` as
  `<\/` so embedded `generate.R` / markdown / ARD can't terminate the script element early.
- **Graphics are vanilla SVG** built with `createElementNS`; no D3 or graph library.
- **Theme-aware**: default to `prefers-color-scheme`, plus a toggle that stamps `data-theme` on the
  root (the toggle must win both ways). Define colors as CSS custom properties so light/dark swap in
  one place.
- **Responsive**: the page body never scrolls horizontally; wide content (rendered tables, ARD, code)
  scrolls inside its own `overflow:auto` container. Respect `prefers-reduced-motion`.

## Palette (categorical, validated)

Node identity uses dataviz categorical slots 1–5 in graph-chain order (validated for CVD in both
modes); the lone Regulatory node uses an intentional neutral slate (secondary-encoded by position and
a dashed/neutral treatment). Status uses the **reserved** status palette, never a categorical slot.

| Type | Light | Dark |
|---|---|---|
| Objective | `#2a78d6` | `#3987e5` |
| Endpoint  | `#1baf7a` | `#199e70` |
| TLF       | `#eda100` | `#e0a836` |
| ADaM      | `#008300` | `#3ca63c` |
| SDTM      | `#4a3aa7` | `#9085e9` |
| Regulatory| `#64748b` | `#8b98ad` |

Because two categorical fills sit below 3:1 on the light surface, identity is reinforced by an ink
label, a solid color rail on each node, and per-type filter legend chips (the "relief rule") — color
is never the sole channel.

## Phase 2 hook

Phase 1 is table-level (node = entity). The TLF `meta` already carries `ardJson`; a future
cell→ARD drill-down attaches to a rendered-table cell click, looks up the matching ARD record, and
opens a sub-panel — no change to the node/edge model is required.
