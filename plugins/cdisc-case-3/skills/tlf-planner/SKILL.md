---
name: tlf-planner
description: "Derive the exhaustive, traceable list of required TLFs (Tables, Listings, Figures) for a clinical study from its USDM metadata JSON. Use this skill when the user has a USDM / CDISC DDF study definition (or asks 'what TLFs/tables/listings/figures do we need', 'derive the TLF list', 'plan the reporting package from USDM', 'map objectives and endpoints to tables', or 'run the TLF planner'). This is the planning/inventory step that runs before ARD dataset creation and before {cards}/{cardx} TLF generation. It interprets objectives and endpoints, adds the ICH E3 regulatory tables no objective points to, fans out statistical analyses (imputation, subgroups, timepoints, sensitivity models), checks data feasibility, and produces a numbered, human-reviewable TLF index. Pair with the tlf-plan-critic skill, which independently audits the result for coverage and completeness."
---

# TLF Planner

## Purpose

Given a study's **USDM metadata JSON**, produce an **exhaustive, traceable list of required
TLFs** — every output justified by either an objective/endpoint or a regulatory rule, with
nothing missing and nothing orphaned. This is **Step 1** of the automated TLF workflow:

```
USDM JSON ──▶ [tlf-planner] ──▶ [tlf-plan-critic] ──▶ HUMAN REVIEW ──▶ ARD datasets ──▶ {cards}/{cardx} TLFs
```

Accuracy is the priority. The whole plan is produced in **one context** so cross-endpoint
reasoning stays intact (e.g. ADAS-Cog appearing in both a primary Week-24 objective and a
secondary Week-8/16 objective must be reconciled, not fragmented). The independent adversarial
check is a **separate** skill (`tlf-plan-critic`) run afterward — do not self-certify here.

## Core principle: fan-out + merge, not lookup

Deriving TLFs draws on four independent sources; the list is their union:

1. **Objectives/endpoints** define *what to measure* (the seed).
2. **Statistical conventions / SAP** *multiply* each endpoint into method + imputation + subgroup + timepoint variants.
3. **ICH E3 scaffolding** *adds* population/disposition/exposure tables no objective points to.
4. **Data availability** *filters/flags* what can actually be produced.

A planner that reads only objectives/endpoints under-produces. See
the protocol-to-tfl design notes (objective-endpoint-tlf-mapping, tlf-planner-agent-design) for the full rationale and the worked CDISCPILOT01 example.

## Inputs

- **Required:** path to the USDM study-definition JSON.
- **Optional:** a SAP (PDF/text) — if present, extract the *actual* pre-specified analysis
  variants in phase 4 instead of applying conventional defaults.
- **Optional:** the SDTM/ADaM data directory — used in phase 5 for feasibility. Defaults to
  `test-docs/{study}/sdtm/` and `outputs/{study}-outputs/adam/data/` if present.

## Output

Per `references/pipeline-contract.md`, write to `outputs/{study-folder}/tlf-plan/`:

- `study-model.json` — the normalized USDM (reviewable intermediate; the critic audits against it)
- `tlf-plan.json` — the final numbered array of TLF candidates (`references/tlf-candidate-schema.md`)
- `tlf-index.md` — the human-readable numbered index (the deliverable; structured to feed `mock-tlg-generator`)

Then tell the user to run **`tlf-plan-critic`** for the independent coverage/completeness audit
before human review.

## Workflow

Run all six phases in order, in one pass. Read the referenced knowledge pack at the start of
each phase — they encode the accuracy-critical domain rules.

### Phase 1 — Interpret USDM → study model
Read `references/usdm-parsing-guide.md` and `references/study-model-schema.md`. Walk
`study.versions[].studyDesigns[]`. Extract objectives (decode Primary/Secondary/Exploratory
from `level`), endpoints (nested under each objective; parse the free text into
`measure` / `measure_type` / `timepoints` / `domain_hint`), estimands (variable of interest,
population, intercurrent-event strategy), analysis populations, treatment arms, visit schedule.
**Flag unresolved endpoints** (placeholder text like `*** To be determined ***`, empty text)
with `resolved:false` — never drop them. Write `study-model.json`. Fidelity over completeness:
never fabricate; use nulls + `normalizer_notes`.

### Phase 2 — Characterize the study (feature flags)
Read `references/characterization-rules.md`. From the study model, determine phase, design,
therapeutic area, blinding, arm count, multi-site, and the boolean feature flags that gate the
later phases: `needs_pk`, `needs_pd`, `needs_immunogenicity`, `needs_oncology_response`,
`needs_pro_hrqol`, `needs_tte_safety_figure`, `needs_subgroup_by_sex`, `needs_subgroup_by_region`.
Keep these in working memory (they need not be a separate file).

### Phase 3 — Derive candidate TLFs from all four sources
Emit `references/tlf-candidate-schema.md`-conforming candidates. **Over-produce**; dedup/feasibility
come later. Every candidate MUST populate `traces_to`.
- **3a Regulatory scaffolding** — read `references/ich-e3-scaffolding-catalog.md`. Emit the
  objective-independent §14 tables (disposition, populations, by-site if multi-site, demographics,
  exposure, conmeds, medical history / deviations as applicable). `traces_to.regulatory_rule` set,
  objective/endpoint ids empty.
- **3b Efficacy analyses** — read `references/efficacy-methods-catalog.md`. For each *resolved*
  efficacy endpoint, enumerate the base method families (ANCOVA, MMRM, descriptive-over-time,
  CMH/categorical, responder…), respecting objective level (primary → headline + sensitivity;
  secondary → single analyses). Split explicit multi-timepoint endpoints (e.g. "Weeks 8 and 16")
  here. Emit nothing for `resolved:false` endpoints.
- **3c Safety families** — read `references/safety-table-families.md`. Expand each safety endpoint
  keyword into its standard family (AE→TEAE/SAE/deaths/D-C; labs→continuous+shift+Hy's-Law;
  vitals→baseline/EOT/CFB/weight). Emit the Kaplan-Meier time-to-event **figure** only if
  `needs_tte_safety_figure`.
- **3d Special domains** — read `references/special-domain-catalog.md`. For each TRUE special-domain
  flag emit its candidate set (PK, oncology RECIST/KM/waterfall, immunogenicity, PRO/HRQoL). If no
  flags are set, emit nothing (clean degradation — the CDISCPILOT01 case).

### Phase 4 — Expand analysis variants
Read `references/variant-expansion-rules.md`. Multiply each *seed* candidate across imputation
(LOCF vs OC), analysis population, subgroups (sex/region — gated on the phase-2 flags), and any
un-split timepoints. Treat scaffolding, descriptive companions, MMRM, and safety families as
**leaves** (do not over-expand). If a SAP was provided, extract the pre-specified variants; else
apply conventional defaults and add a `notes` entry `"variant assumed — no SAP provided"`. Keep
`candidate_id`s unique and deterministic.

### Phase 5 — Check data feasibility
Read `references/data-domain-map.md`. Discover the available SDTM domains and ADaM datasets from
the data directory. Set each candidate's `status`: `planned` (data satisfiable), `blocked` (required
domain absent — e.g. no DV → protocol-deviations listing) with `status_reason`, or
`needs-clarification` (traces to a `resolved:false` endpoint, or measure has no plausible source).
Never delete candidates — only annotate.

### Phase 6 — Consolidate & number
Read `references/numbering-and-dedup-rules.md`. Deduplicate candidates describing the same output
(record merges in the survivor's `notes`), resolve each to a §14 section, assign `final_id`
(T/F/L 14-{section}.{seq}, figures on one global sequence), and order by section → priority →
timepoint. Leave `blocked` / `needs-clarification` items unnumbered and list them in a separate
"Flagged / not currently producible" section of the index. Write `tlf-plan.json` and `tlf-index.md`.

### Finish
Print a summary: total TLF count (T/L/F), breakdown by §14 section, flagged items, and any
`notes` about assumed variants. Direct the user to run `tlf-plan-critic`.

## Reference files

**Shared contracts (obey exactly):**
- `references/study-model-schema.md` — phase-1 output shape
- `references/tlf-candidate-schema.md` — the candidate object every phase emits/edits
- `references/pipeline-contract.md` — directories, output artifacts, §14 numbering, the 3-step vision

**Knowledge packs (read at the start of each phase — the accuracy asset):**
- `references/usdm-parsing-guide.md` — phase 1
- `references/characterization-rules.md` — phase 2
- `references/ich-e3-scaffolding-catalog.md` — phase 3a
- `references/efficacy-methods-catalog.md` — phase 3b
- `references/safety-table-families.md` — phase 3c
- `references/special-domain-catalog.md` — phase 3d
- `references/variant-expansion-rules.md` — phase 4
- `references/data-domain-map.md` — phase 5
- `references/numbering-and-dedup-rules.md` — phase 6

> Note on provenance: the knowledge packs were originally authored as separate "agents" and may
> refer to themselves that way internally. In this distilled skill each pack is simply the
> reference for the workflow phase listed above — the agent names map 1:1 to the phases.
