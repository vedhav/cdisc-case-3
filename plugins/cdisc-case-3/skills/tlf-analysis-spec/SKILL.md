---
name: tlf-analysis-spec
description: "Turn a reviewed TLF plan into the analysis specs + ADaM variable spec that drive ADaM derivation and TLF generation. Use this skill when the user has a tlf-plan.json (from tlf-planner / tlf-plan-critic) and asks to 'author the analysis spec', 'build the ADaM spec', 'map the TLF plan to specs', 'create the analysis metadata', 'write the statistical method spec', 'produce ARS-aligned analysis specs', or 'run the bridge before ADaM / generation'. This is Step 2 of the TLF pipeline — the human-review gate between planning and compute: for every producible TLF it authors an ARS-aligned analysis-spec entry (analysisSet, groupingFactor, dataSubset, analysisVariables, methods with operations/model/lsmeans/contrasts, rounding), and aggregates the union of all TLFs' data needs into a reviewable adam-spec.json (datasets, parameters, variables, flags, the mandatory derivation rules, and the data-quality N-gate). It does NOT run R or derive ADaM — it produces specs only. Run before sdtm-to-adam and tlf-generator."
---

# TLF Analysis Spec

## Purpose

Turn a **human-reviewed TLF plan** into the three artifacts that drive the rest of the pipeline:

1. **`analysis-spec.json`** — one ARS-*aligned* analysis recipe per producible TLF (population,
   grouping, record filter, analysis variables, statistical method(s) + operations, rounding).
2. **`adam-spec.json`** — the variable-level ADaM requirements aggregated across *all* TLFs
   (datasets, parameters, variables, flags, populations) plus the mandatory derivation rules and
   the data-quality N-gate.
3. **`reporting-event.json`** — a CDISC **ARS (Analysis Results Standard) ReportingEvent** that
   re-expresses the same analyses in the standard ARS Low-level Data Model (analysisSets, methods,
   analysisGroupings, analyses, outputs, a mainListOfContents), so downstream traceability and
   conformance anchor to the CDISC standard rather than a bespoke shape. The automated
   `validate-ars` gate validates it against the ARS LDM JSON Schema **immediately after this step**
   and sends the run back here (with the specific errors) if it does not conform — so it must be
   schema-valid, not merely "ARS-aligned".

This is **Step 2** of the automated TLF workflow — the bridge between the plan and compute:

```
USDM ─▶ tlf-planner ─▶ tlf-plan-critic ─▶ [HUMAN REVIEW]
                                              │
                          reviewed tlf-plan.json + study-model.json
                                              │
                              ─▶ [tlf-analysis-spec] ◀── YOU ARE HERE
                                              │
          analysis-spec.json + adam-spec.json + reporting-event.json ─▶ [validate-ars gate] ─▶ [HUMAN REVIEW GATE]
                                              │
              sdtm-to-adam (consumes adam-spec)   tlf-generator (consumes analysis-spec + ADaM)
```

Both outputs are **reviewable, editable gate artifacts**. A biostatistician catches a wrong
analysis flag, population, or contrast *here* — before it silently corrupts every downstream
number. Per `adam-to-tlf-design.md` §6 the #1 battle is upstream in the ADaM flags/populations:
**review the adam-spec hardest.**

## When to use

Use immediately after `tlf-plan-critic` and human review of the plan, and before `sdtm-to-adam`.
Triggers: "author the analysis spec", "build the ADaM spec", "map TLF plan to specs", "analysis
metadata", "statistical method spec", "ARS-aligned spec", "the bridge before ADaM/generation".

**Do NOT** run R, derive ADaM, or compute any numbers here — this skill only produces specs.
**Do NOT** modify other skills.

## Inputs

- **Required:** `outputs/{study}/tlf-plan/tlf-plan.json` — the numbered candidate array
  (`../tlf-planner/references/tlf-candidate-schema.md`).
- **Required:** `outputs/{study}/tlf-plan/study-model.json` — normalized study (objectives,
  endpoints, populations, arms, visit schedule) for populations, treatment levels, and dose.

`{study}` mirrors the plan directory produced by `tlf-planner` (e.g. `cdiscpilot01-outputs`; if
unknown, derive from `study_id` lowercased). ADaM data, once derived, lives at
`outputs/{study}/adam/data/`.

## Output

Write to the same plan directory:

- `outputs/{study}/tlf-plan/analysis-spec.json` — a JSON **array** of analysis-spec objects, one
  per producible TLF, each conforming exactly to `references/analysis-spec-schema.md` and keyed by
  `table_id` (the `final_id` minus the `T-`/`F-`/`L-` prefix).
- `outputs/{study}/tlf-plan/adam-spec.json` — a single object conforming exactly to
  `references/adam-spec-schema.md`.
- `reporting-event.json` — the ARS ReportingEvent (Phase 2.5), validated by the `validate-ars`
  gate against `references/ars-reporting-event-schema.md`.

**In the workflow container**, write all three (`analysis-spec.json`, `adam-spec.json`,
`reporting-event.json`) to **both `/workspace` and `/output`** at the paths named above — the
`validate-ars` gate, `sdtm-to-adam`, and `tlf-generator` read them from there.

**On a `validate-ars` fail re-entry** (the automated gate found ARS errors), read
`/workspace/ars-validation.md`, fix ONLY the flagged schema/reference errors in
`reporting-event.json` (and any analysis-spec entry they trace to), and re-emit. Append the same
feedback to `/workspace/review_feedback.jsonl` as `{"skill":"tlf-analysis-spec",...}` so the
self-learning loop can distil a durable lesson.

Then print a summary and tell the user to **review the specs** before running `sdtm-to-adam`.

## Workflow

Run in one pass so cross-TLF reasoning stays intact (shared datasets, LOCF vs OC variants of the
same endpoint, aggregated flags). Read `references/analysis-spec-schema.md` and
`references/adam-spec-schema.md` first — they are the contracts you must obey.

### Phase 0 — Load and scope
Read `tlf-plan.json` and `study-model.json`. Select the **producible** candidates: `status ==
"planned"` with a non-null `final_id`. **Skip** `blocked` / `needs-clarification` items for the
analysis spec, but record them in the summary so the reviewer knows what was deferred. From
`study-model.json` pull the treatment arms (levels, order, reference = placebo/control, numeric
dose) and the population definitions once — they are reused by every entry.

### Phase 1 — Per-TLF analysis-spec entry
For each producible candidate, author one analysis-spec object:

1. **Header** — `id` = `AN-{table_id}`, `table_id` = `final_id` minus prefix, `title` (from the
   candidate), `protocol`, `reason` (SPECIFIED IN SAP if it traces to an objective/endpoint,
   CONVENTION/GAP-FILL if scaffolding-driven), `purpose`.
2. **`analysisSet`** — map `analysis.population` → flag condition:
   Efficacy→`EFFFL='Y'`, Safety→`SAFFL='Y'`, Intent-to-Treat→`ITTFL='Y'`,
   Completers→`COMPLFL='Y'`, All Subjects→randomized (no analysis-flag filter). `source` names the
   ADSL flag.
3. **`groupingFactor`** — treatment split (`TRTP`, character) with `levels[]` in explicit order,
   `isReference:true` on placebo/control, and `dose` on active arms; set `doseVariable`
   (`TRT01PN`) when a dose-response/trend test applies. Level order drives column order AND
   contrast sign.
4. **`subgroup`** — from `analysis.subgroup` (e.g. `{"variable":"SEX","level":"M"}`) or `null`.
5. **`dataSubset`** — `dataset` = the primary analysis ADaM (the non-ADSL dataset in
   `data_requirements.adam`); `condition` combines the parameter filter (`PARAMCD=…`), the
   timepoint (`AVISITN=…`), and the imputation-driven record flag:
   - **LOCF** → `ANL01FL='Y'` (the primary analysis record, which includes carried-forward rows;
     `DTYPE ∈ {'','LOCF'}`).
   - **OC / Completers / windowed** → the corresponding `ANLxxFL` (e.g. observed-cases + windowed
     completers flag); note in the entry which flag encodes the variant.
6. **`analysisVariables`** — role→variable map: `baseline`→`BASE`, `response`→`CHG`,
   `value`→`AVAL` (name/label the roles the method needs).
7. **`methods[]`** — pick the method type(s) from the catalog by `analysis.method` (table below),
   set `operations`, `display` precision, and the `engine`. Add the descriptive companion when the
   inferential method reports summary stats alongside the model.
8. **`rounding`** — always the SAS half-away-from-zero rule (R defaults to banker's rounding; the
   generator must replicate SAS — see `adam-to-tlf-design.md` §6.2).
9. **`output`** — `ard`, `display` (`<table_id>.generated.md`).

**Method map** (`analysis.method` → analysis-spec `methods[]`; ⚠️ = assemble, ❌ = custom ARD):

| Planner `method` | analysis-spec method type(s) | Engine | Note |
|---|---|---|---|
| `Descriptive` | `Descriptive` | `cards::ard_continuous`/`ard_categorical` | ✅ |
| `Incidence` | `Incidence` | `cards::ard_hierarchical`/`cardx::ard_tabulate` | ✅ AE/CM by SOC/PT |
| `ShiftTable` | `ShiftTable` (+ `CMH` if `comparison` mentions CMH) | `cardx::ard_tabulate_shift`/`_abnormal` | ✅ labs |
| `ANOVA` | `Descriptive` + `ANOVA` | `cardx::ard_stats_aov` | ✅ |
| `ANCOVA` | `Descriptive` + `ANCOVA` (+ `DoseResponse` if `comparison`=dose-response) | `lm` + `emmeans` directly | ⚠️ assemble |
| `CMH` | `CMH` | `cardx::ard_stats_mantelhaen_test` | ✅ watch sparse strata |
| `Fisher`/`ChiSquare` | `Fisher`/`ChiSquare` | `cardx::ard_stats_fisher_test`/`ard_stats_chisq_test` | ✅ |
| `KaplanMeier` | `KaplanMeier` (+ `LogRank` if `comparison` mentions log-rank) | `cardx::ard_survival_survfit`; render `ggsurvfit` | ✅ figure |
| `LogRank` | `LogRank` | `cardx::ard_survival_survdiff` | ✅ |
| `Cox` | `Cox` | `cardx::ard_regression` on `survival::coxph` | ⚠️ |
| `MMRM` | `MMRM` (+ `Descriptive`) | `mmrm::mmrm` + `emmeans` → custom ARD | ❌ no cardx fn |
| `none` (listings) | omit `methods` or a single `Descriptive` selection | — | listing, no inferential stat |

For the ANCOVA `model`/`lsmeans`/`contrasts` sub-objects use the validated pattern in
`references/analysis-spec-schema.md` (model `CHG ~ TRTP + SITEGR1 + BASE`, explicit contrast coef
lists, `adjust:"none"`). Prefer `emmeans` directly — `cardx::ard_emmeans_contrast` was broken in
the tested build (see `../tlf-generator/references/generation-idioms.md`).

### Phase 2 — Aggregate the ADaM spec
Build one `adam-spec.json` from the **union** of all producible candidates' data needs:

1. **Datasets** — group by ADaM dataset name across `data_requirements.adam`. For each: `class`
   (ADSL/BDS/OCCDS/TTE), `sdtm_source`, `used_by_tables` (every `table_id` that consumes it),
   `parameters` (the PARAMCDs each consuming table selects — apply the known CDISCPILOT01 gotchas:
   ADAS-Cog(11) total is **`ACTOT11`**, not `ACTOT`), and `variables` (the union of columns the
   consuming tables need: analysis/baseline/change values, `AVISIT`/`AVISITN`, `ABLFL`, the
   `ANLxxFL` flags every variant requires, `DTYPE`, `TRTP`, `TRT01PN`, plus `SITEGR1`/population
   flags sourced from ADSL).
2. **Mandatory derivation rules** — attach the three rules from `references/adam-spec-schema.md`
   to the datasets they apply to. These were **real bugs** in this repo; they are non-negotiable:
   - **Visit windowing must NOT drop unscheduled/ET visits** — use day-based (`ADY`) windowing with
     midpoint boundaries, nearest-to-target within each subject×window. (BDS efficacy datasets.)
   - **LOCF record creation** — for every analysis-population subject with a baseline and ≥1
     post-baseline value but no observed endpoint record, carry the last value forward as a
     `DTYPE='LOCF'`, `ANL01FL='Y'` record at the endpoint `AVISITN`; exactly one primary record per
     subject per endpoint. (Every dataset feeding an LOCF table.)
   - **`SITEGR1` pooling on RANDOMIZED count** — pool a site into `900` when any planned arm at
     that site has **< 3 randomized (`ITTFL='Y'`)** subjects (not all-enrolled). Lives in ADSL,
     cascades to every ANCOVA/stratified table. For CDISCPILOT01 this yields 11 site groups.
3. **Populations** — list every flag referenced by any analysisSet (`EFFFL`, `SAFFL`, `ITTFL`,
   `COMPLFL`, …) with label + definition.
4. **Data-quality N-gate** — record the required assertion: after derivation, each analysis set's
   N must match its population flag count (e.g. Week-24 efficacy N == `EFFFL='Y'`), warning loudly
   on any shortfall — the visit-window bug would otherwise pass silently and tank the match.

### Phase 2.5 — Emit the ARS ReportingEvent (`reporting-event.json`)

Re-express the analyses you just authored as a **schema-valid ARS ReportingEvent**. The
`validate-ars` gate validates this against the ARS LDM schema and, on any error, routes the run
back to this step with the exact failures — so build it to conform. Read
`references/ars-reporting-event-schema.md` for the field-by-field contract; the essentials:

- **Root (required):** `id`, `name`, `mainListOfContents`.
- **`analysisSets[]`** — one per distinct population flag you used (EFFFL/SAFFL/ITTFL/…). Each needs
  `id`, `name`, `level`, `order`, and a `condition` `{dataset, variable, comparator:"EQ",
  value:["Y"]}`.
- **`analysisGroupings[]`** — the treatment grouping (`GRP.TRT`): `id`, `name`, `dataDriven:false`,
  `groupingVariable:"TRTP"`, and a `groups[]` entry per arm (`id`, `name`, `level`, `order`).
- **`methods[]`** — one per distinct statistical method (Descriptive/ANCOVA/Incidence/KaplanMeier/
  MMRM/…): `id`, `name`, and `operations[]` where each operation has `id`, `order`, `name`.
- **`analyses[]`** — **one per producible TLF**: `id` (`AN.<table_id>`), `name`, `methodId` (→ a
  `methods[].id`), `analysisSetId` (→ an `analysisSets[].id`), `orderedGroupings:[{order:1,
  groupingId, resultsByGroup:true}]`, `dataset`, and the two required controlled terms:
  - `reason` = `{controlledTerm:"SPECIFIED IN SAP"}` (or `"SPECIFIED IN PROTOCOL"` / `"DATA
    DRIVEN"`).
  - `purpose` = `{controlledTerm:"PRIMARY OUTCOME MEASURE"}` (or SECONDARY/EXPLORATORY) for outcome
    analyses. For non-outcome analyses (safety, disposition, demographics) the enum has no term —
    use a **sponsor purpose** `{"sponsorTermId":"SPT.SAFETY"}` and declare it once in
    `terminologyExtensions:[{id:"TE.PURPOSE", enumeration:"AnalysisPurposeEnum",
    sponsorTerms:[{id:"SPT.SAFETY", submissionValue:"SAFETY"}]}]`.
- **`outputs[]`** — one per TLF display: `id` (`OUT.<table_id>`), `name`, `displays:[{order:1,
  display:{id:"D.<table_id>", name}}]`.
- **`mainListOfContents`** — `{name, contentsList:{listItems:[{level:1, order:N, name, outputId}
  …]}}`; every `analysisId`/`outputId` referenced must resolve to a defined analysis/output.

Every `methodId`, `analysisSetId`, `groupingId`, `analysisId`, and `outputId` must resolve — the
gate rejects dangling references. Keep ids stable and derived from `table_id` so the traceability
graph can bridge ARS ↔ TLF.

### Phase 3 — Write and hand off
Write `analysis-spec.json` (array) and `adam-spec.json`. Validate each object against its schema
before writing. Then print a summary:

- count of analysis-spec entries authored, broken down by method type;
- the datasets in the ADaM spec and which tables drive each;
- any TLFs skipped (blocked / needs-clarification) and why;
- any variant assumptions carried from the plan `notes` (e.g. "LOCF assumed — no SAP").

End by telling the user: **review `analysis-spec.json` and `adam-spec.json` (this is a
human-review gate), then run `sdtm-to-adam`** with the ADaM spec, followed by `tlf-generator`.

## Worked mappings

**`T-14-3.01` (ADAS-Cog(11), ANCOVA, Efficacy, Week 24, LOCF)** — the reference worked example. `analysisSet` = `EFFFL='Y'`; `groupingFactor` = `TRTP` (Placebo ref / Low 54 / High 81),
`doseVariable=TRT01PN`; `dataSubset` = `ADQSADAS` where `PARAMCD='ACTOT11' AND AVISITN=24 AND
ANL01FL='Y'`; `analysisVariables` = BASE/AVAL/CHG; `methods` = `Descriptive` (N/mean/sd/median/
min/max on BASE,AVAL,CHG) + `ANCOVA` (`CHG ~ TRTP + SITEGR1 + BASE`, emmeans LS-means, three
pairwise contrasts) + `DoseResponse` (continuous `TRT01PN`, p-value). Its OC/windowed sibling
`T-14-3.07` is the *same dataset and method* differing only in the `ANLxxFL` in `dataSubset`.

**`T-14-5.01` (Incidence of TEAEs by treatment group, Safety)** — `analysisSet` = `SAFFL='Y'`;
`groupingFactor` = `TRTP` (same levels, no `doseVariable`); `subgroup` = null; `dataSubset` =
`ADAE` where `TRTEMFL='Y'` (treatment-emergent); `analysisVariables` map the hierarchy roles
(`AEBODSYS`→SOC, `AEDECOD`→PT); `methods` = a single `Incidence` (n(%) subjects and event counts
by SOC and PT, engine `cards::ard_hierarchical`); `rounding` = SAS. In the ADaM spec it adds an
`ADAE` (OCCDS) dataset with `TRTEMFL`/`AEBODSYS`/`AEDECOD`/`TRTP` and `used_by_tables`
`["14-5.01","14-5.02"]`, plus `ADSL` for `SAFFL` and the denominator.

## Reference files

**Shared contracts this skill PRODUCES (obey exactly — already authored, do not overwrite):**
- `references/analysis-spec-schema.md` — the per-TLF analysis-spec object + method catalog.
- `references/adam-spec-schema.md` — the aggregated ADaM variable spec + mandatory rules + N-gate.

**Upstream contracts this skill CONSUMES:**
- `../tlf-planner/references/tlf-candidate-schema.md` — the TLF candidate object.
- `../tlf-planner/references/pipeline-contract.md` — directories, §14 numbering, populations.
- `../tlf-planner/references/study-model-schema.md` — arms, populations, endpoints.

**Downstream (for context on how the specs are used):**
- `../tlf-generator/references/generation-idioms.md` — cards/cardx/emmeans idioms and gotchas.
- the protocol-to-tfl adam-to-tlf design note (repo root) — the Steps 2-3 design; §5 method map, §6 accuracy watch-list.
