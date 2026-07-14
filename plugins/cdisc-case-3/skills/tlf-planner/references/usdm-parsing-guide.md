# USDM Parsing Guide

Where each `study-model.json` field lives in a USDM (CDISC Unified Study Definitions Model /
DDF) tree, the CDISC code decode tables, and the endpoint free-text parsing heuristics.

Paths below were verified against the real file
`test-docs/cdiscpilot01/CDISC_Pilot_Study.json` (`usdmVersion` 4.0.0). The output schema this
guide serves is `study-model-schema.md`.

## 1. Top-level shape

```
{ "study": {...}, "usdmVersion": "4.0.0", "systemName": ..., "systemVersion": ... }
```

- `usdm_version`  ← `.usdmVersion` (top level, NOT inside study).
- `study.name`    ← `.study.name` (e.g. "CDISC PILOT - LZZT").
- The working study version is `.study.versions[0]`; the working design is
  `.study.versions[0].studyDesigns[0]`. If more than one exists, use the first/latest and add a
  `normalizer_notes` entry naming the choice.

Shorthand used below: **VER** = `study.versions[0]`, **SD** = `study.versions[0].studyDesigns[0]`.

## 2. Field-by-field source map

| study-model field | USDM source path | Notes |
|---|---|---|
| `study_id` | `VER.studyIdentifiers[].text` (sponsor) or `study.name` | CDISCPILOT01's sponsor id is `H2Q-MC-LZZT`; an NCT id (`NCT12345678`) is a second identifier. Pick the most recognizable/stable id; note the choice. The well-known dataset alias for this study is "CDISCPILOT01". |
| `study_name` | `study.name` | |
| `title` | `VER.titles[]` where `type.decode == "Official Study Title"` (code `C99905x2`) | Other title types: `C94108` Study Acronym, `C99905x1` Brief Study Title. |
| `phase` | `SD.studyPhase.standardCode.decode` | Decoded string, e.g. "Phase II Trial". Use the USDM value verbatim even if secondary docs say otherwise; note any discrepancy. `null` if absent. |
| `usdm_version` | `.usdmVersion` (top level) | |
| `source_file` | the input path the user gave | |
| `objectives[]` | `SD.objectives[]` | see §3 |
| `endpoints[]` | `SD.objectives[].endpoints[]` (nested under each objective) | see §3–§4 |
| `estimands[]` | `SD.estimands[]` | see §5 |
| `analysis_populations[]` | `SD.analysisPopulations[]` | see §6 |
| `treatment_arms[]` | `SD.arms[]` | see §7 |
| `visit_schedule[]` | `SD.encounters[]` (+ `SD.epochs[]`) | see §8 |

## 3. Objectives and endpoints

Objectives are at `SD.objectives[]`. Endpoints are **nested inside each objective** at
`SD.objectives[].endpoints[]` — there is no top-level endpoints array. Both objective and
endpoint carry their own `level` Code object.

Per objective:
- `id` ← `objective.id` (PRESERVE VERBATIM, e.g. `Objective_1`)
- `name` ← `objective.name` (e.g. `OBJ1`)
- `level` ← decode `objective.level.code` / `objective.level.decode` (see §9)
- `description` ← `objective.description`; `text` ← `objective.text`
- `endpoint_ids` ← `[e.id for e in objective.endpoints]`

Per endpoint (inside `objective.endpoints[]`):
- `id` ← `endpoint.id` (VERBATIM, e.g. `Endpoint_1`)
- `name` ← `endpoint.name` (e.g. `END1`)
- `objective_id` ← the enclosing objective's `id`
- `level` ← decode `endpoint.level.code` / `endpoint.level.decode` (see §9)
- `text` ← `endpoint.text`
- `parsed` ← from free-text parsing (§4)
- `resolved` ← `false` when text is a placeholder / empty (§4)

## 4. Endpoint free-text parsing heuristics (best-effort)

Populate `parsed` from `endpoint.text`. Never invent — leave a field `null` if the text does
not support it and add a `normalizer_notes` entry when a substantive endpoint yields nothing.

**Unresolved detection (do this first).** If `text` matches a placeholder — contains
`"*** To be determined"` / `"To be determined from protocol"`, is empty/whitespace, or is
otherwise non-substantive — set `resolved: false`, leave all `parsed` fields `null`, add the id
to `unresolved_endpoints`, and note it. Do not attempt to parse a measure out of a placeholder.

**`measure`** — the instrument/parameter name. Extract the recognizable clinical instrument or
safety domain. Known instruments in this study family:
- `Alzheimer's Disease Assessment Scale - Cognitive Subscale, total of 11 items` → `ADAS-Cog (11)`
- `... 14 items` → `ADAS-Cog (14)`
- `Video-referenced Clinician's Interview-based Impression of Change (CIBIC+)` → `CIBIC+`
- `Revised Neuropsychiatric Inventory (NPI-X)` → `NPI-X`
- `Disability Assessment for Dementia (DAD)` → `DAD`
- Safety phrases stay as-is: `Adverse events`, `Vital signs (...)` → `Vital signs`,
  `Laboratory evaluations (...)` → `Laboratory evaluations`.

**`measure_type`**:
- Cognitive/lab/vital numeric scores and change-from-baseline → `continuous`
- CIBIC+ (7-point clinician global rating) → `global-impression`
- Ordinal category responses → `ordinal`; frequency/shift categories → `categorical`
- `Adverse events` / time-to-event → `event`
- Simple counts → `count`

**`timepoints`** — pull explicit visits/weeks from the text; return a list, `[]` if none:
- "at Week 24" → `["Week 24"]`
- "at Weeks 8 and 16" → `["Week 8", "Week 16"]`
- "from Week 4 to Week 24" → `["Week 4", "Week 24"]` (range endpoints; note it is windowed)

**`domain_hint`**:
- Cognition (ADAS-Cog) → `efficacy-cognition`
- Global impression (CIBIC+) → `efficacy-global`
- Behavior (NPI-X) → `efficacy-behavior`
- `Adverse events` → `safety-ae`; `Laboratory evaluations` → `safety-lab`;
  `Vital signs` → `safety-vs`; PK params → `pk`; otherwise → `other`.

## 5. Estimands — `SD.estimands[]`

| field | source |
|---|---|
| `id` / `name` | `estimand.id` / `estimand.name` |
| `population_summary` | `estimand.populationSummary` |
| `analysis_population_id` | `estimand.analysisPopulationId` |
| `variable_of_interest_endpoint_id` | `estimand.variableOfInterestId` (an `Endpoint_*` id) |
| `intercurrent_events[]` | `estimand.intercurrentEvents[]` → `name`, `text`, `strategy` |

The `strategy` string in the USDM may be verbose (e.g. "Treatment Policy – Continue to
measure effect ..."). Normalize to one of: Treatment Policy | Hypothetical | Composite |
While-on-Treatment | Principal Stratum (match on the leading phrase); keep the full text if it
does not map cleanly and note it. CDISCPILOT01 has one estimand: `Estimand_1` (EST1) with
`variableOfInterestId → Endpoint_1` and a "Treatment Policy" intercurrent-event strategy.

## 6. Analysis populations — `SD.analysisPopulations[]`

- `id` ← `.id`; `name` ← `.name`; `text` ← `.text` (may hold the description).
- `role` — infer from name/text: itt | mitt | safety | efficacy | pp | completers | other.
  CDISCPILOT01 declares a single population `AnalysisPopulation_1` (name `AP_1`); when the name
  is opaque, infer `role` from context or use `other` and note it. (The downstream CSR uses
  ITT / Safety / Efficacy / Completers sets; those are not all enumerated in this USDM.)

## 7. Treatment arms — `SD.arms[]`

- `id` ← `.id`; `name` ← `.name`; `type` ← `.type.decode`
  (e.g. "Placebo Control Arm", "Active Comparator Arm").
- `dose` — arms do NOT carry a dose field directly. Best-effort only: derive from the arm name
  ("Low Dose"/"High Dose") or from dose text in an objective (OBJ1 mentions
  "50 cm2 [54 mg], and 75 cm2 [81 mg]"), or inspect
  `VER.studyInterventions[].administrations[]`. If not cleanly available, set `dose: null` and
  note it. CDISCPILOT01 arms: `StudyArm_1` Placebo, `StudyArm_2` Xanomeline Low Dose (~54 mg),
  `StudyArm_3` Xanomeline High Dose (~81 mg).

## 8. Visit schedule — `SD.encounters[]` and `SD.epochs[]`

- Each encounter: `name` ← `.name` (e.g. "E4"), and the human label ← `.label`
  (e.g. "Week 2", "Baseline", "Screening 1"). Prefer the label for the schema `name` field, or
  keep both if useful.
- `study_day` — not directly on the encounter. It can be derived from
  `SD.scheduleTimelines[].timings[]` (ISO-8601 durations like `P2D`, relative anchors) but this
  is complex; set `study_day: null` best-effort unless a clean value is available, and note it.
- `epoch` — from `SD.epochs[]` (Screening, Treatment 1/2/3, Follow-Up). Map an encounter to its
  epoch only when the linkage is clear; otherwise `null`.
- CDISCPILOT01 encounters (label): Screening 1, Screening 2, Baseline, Week 2, Week 4, Week 6,
  Week 8, Week 12, Week 16, Week 20, Week 24, Week 26. Epochs: Screening, Treatment 1/2/3,
  Follow-Up.

## 9. CDISC code decode tables

Levels are `Code` objects with `.code`, `.decode`, `.codeSystem`. Decode by `.code` (authoritative)
and fall back to `.decode`.

**Objective level** (`objective.level.code`):

| C-code | decode | study-model `level` |
|---|---|---|
| C85826 | Primary Objective | `Primary` |
| C85827 | Secondary Objective | `Secondary` |
| C85828 | Exploratory Objective | `Exploratory` |

**Endpoint level** (`endpoint.level.code`):

| C-code | decode | study-model `level` |
|---|---|---|
| C94496 | Primary Endpoint | `Primary` |
| C139173 | Secondary Endpoint | `Secondary` |
| C188874 | Exploratory Endpoint | `Exploratory` |

(If a code is unrecognized, decode from the `.decode` string — strip the trailing
" Objective"/" Endpoint" — and note the unmapped code.)

## 10. CDISCPILOT01 ground-truth cross-check

A correct normalization of `test-docs/cdiscpilot01/CDISC_Pilot_Study.json` yields:

- **6 objectives**: OBJ1, OBJ2 = Primary (C85826); OBJ3–OBJ6 = Secondary (C85827).
- **11 endpoints**: END1–END5 Primary (C94496); END6–END11 Secondary (C139173).
- **8 resolved** endpoints (END1–END8) with parsed measures:
  - END1 ADAS-Cog (11), Week 24, continuous, efficacy-cognition (Primary)
  - END2 CIBIC+, Week 24, global-impression, efficacy-global (Primary)
  - END3 Adverse events, event, safety-ae (Primary)
  - END4 Vital signs, continuous, safety-vs (Primary)
  - END5 Laboratory evaluations, continuous, safety-lab (Primary)
  - END6 ADAS-Cog (11), Weeks 8 & 16, continuous, efficacy-cognition (Secondary)
  - END7 CIBIC+, Weeks 8 & 16, global-impression, efficacy-global (Secondary)
  - END8 NPI-X, Week 4–24 windowed, continuous, efficacy-behavior (Secondary)
- **3 UNRESOLVED** endpoints — **Endpoint_9, Endpoint_10, Endpoint_11** — text
  "*** To be determined from protocol ***". These get `resolved: false`, `parsed` all `null`,
  and appear in `unresolved_endpoints`.
- **1 estimand** EST1 → Endpoint_1, Treatment Policy.
- **3 arms** (Placebo / Xanomeline Low / High), **1 declared analysis population**,
  **12 encounters**, **5 epochs**.
