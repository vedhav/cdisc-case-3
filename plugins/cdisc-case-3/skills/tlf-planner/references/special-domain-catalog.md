# Special-Domain Candidate Catalog

Per-flag catalogs of the TLF candidates that `special-domain-planner` emits. Each entry maps a
`study-profile.json` feature flag to a base candidate set. **Every candidate conforms to the
shared schema** in `tlf-candidate-schema.md`, sets
`produced_by: "special-domain-planner"`, and leaves `final_id: null` (numbered later by
`tlf-consolidator`).

These are **base** candidates. Population, subgroup, imputation, and timepoint fan-out is the
job of agent 7 (`analysis-variant-expander`) — do NOT pre-expand here. Over-produce within the
flagged lane; dedup and feasibility filtering happen downstream.

**Gating rule (strict):** emit a catalog only if its flag is `true` in `study-profile.json`. A
flag that is absent, `false`, or `null` produces nothing. If **no** flag is true, the entire
output is the empty array `[]` — see the CDISCPILOT01 section at the end.

---

## `needs_pk` / `needs_pd` — Pharmacokinetics / Pharmacodynamics

`category: "pk"` (ICH E3 §14-4). Fan out one summary set per **dose level** from
`study-model.json` `treatment_arms[].dose`. PD, when flagged, reuses the same table family
against the pharmacodynamic marker.

| candidate_id (pattern) | type | title | method | data_requirements |
|---|---|---|---|---|
| `pk-conc-time-summary` | Table | Summary of Plasma Concentrations by Nominal Time and Dose | Descriptive | ADPC / PC, PP |
| `pk-conc-time-fig-lin` | Figure | Mean Concentration-Time Profile (Linear Scale) by Dose | Descriptive | ADPC / PC |
| `pk-conc-time-fig-log` | Figure | Mean Concentration-Time Profile (Semi-Log Scale) by Dose | Descriptive | ADPC / PC |
| `pk-param-summary` | Table | Summary of PK Parameters (Cmax, AUC0-t, AUC0-inf, Tmax, t½, CL/F, Vz/F) by Dose | Descriptive | ADPP / PP |
| `pk-trough-steady-state` | Table | Summary of Trough (Ctrough) Concentrations by Visit — Steady-State Assessment | Descriptive | ADPC / PC |
| `pk-param-listing` | Listing | Individual PK Parameters by Subject and Dose | none | ADPP / PP |
| `pd-marker-summary` *(needs_pd only)* | Table | Summary of Pharmacodynamic Marker by Time and Dose | Descriptive | ADPD |
| `pd-conc-effect-fig` *(needs_pd only)* | Figure | Concentration-Effect (PK/PD) Relationship by Dose | Descriptive | ADPC, ADPD |

Notes: PK parameter tables report geometric mean (CV%), median, range per parameter. Include a
`Total` where a pooled column is meaningful. `analysis.comparison` = "by dose level".

---

## `needs_oncology_response` — Oncology Tumor Response

`category: "other"` (special §14-x), except KM survival which downstream consolidation may place
in efficacy. Read an oncology TLG guide for RECIST
categories, CI methods, censoring rules, and figure conventions.

| candidate_id (pattern) | type | title | method | data_requirements |
|---|---|---|---|---|
| `onc-recist-bor` | Table | Best Overall Response per RECIST v1.1 (CR/PR/SD/PD/NE) by Treatment | Incidence | ADRS / RS |
| `onc-orr-ci` | Table | Objective Response Rate (CR+PR) with 95% CI by Treatment | Incidence | ADRS / RS |
| `onc-dcr-ci` | Table | Disease Control Rate (CR+PR+SD) with 95% CI by Treatment | Incidence | ADRS / RS |
| `onc-dor-summary` | Table | Duration of Response (responders) — Kaplan-Meier Survival Summary | KaplanMeier | ADTTE / RS |
| `onc-pfs-km-table` | Table | Progression-Free Survival — Kaplan-Meier Survival Summary (median, landmark rates, HR, log-rank) | KaplanMeier | ADTTE |
| `onc-pfs-km-fig` | Figure | Progression-Free Survival Kaplan-Meier Survival Curve with Number at Risk | KaplanMeier | ADTTE |
| `onc-os-km-table` | Table | Overall Survival — Kaplan-Meier Survival Summary (median, landmark rates, HR, log-rank) | KaplanMeier | ADTTE |
| `onc-os-km-fig` | Figure | Overall Survival Kaplan-Meier Survival Curve with Number at Risk | KaplanMeier | ADTTE |
| `onc-waterfall` | Figure | Waterfall Plot of Best Percent Change in Tumor Burden | Descriptive | ADTR / TR |
| `onc-spider` | Figure | Spider Plot of Tumor Burden Change Over Time | Descriptive | ADTR / TR |
| `onc-swimmer` | Figure | Swimmer Plot of Response Duration by Subject | Descriptive | ADRS, ADTTE |
| `onc-response-listing` | Listing | Individual Tumor Response by Subject and Visit | none | ADTR, ADRS |

Notes: response-rate tables carry a CI-method footnote (Clopper-Pearson / Wilson — SAP-driven).
KM tables/figures MUST use "survival" in the title and "log-rank" for the comparative p-value
(per mock-tlg-generator conventions). If central + investigator assessment both apply, agent 7
fans those out — emit the base (central/primary) candidate here.

---

## `needs_immunogenicity` — Immunogenicity (ADA / nAb)

`category: "other"`.

| candidate_id (pattern) | type | title | method | data_requirements |
|---|---|---|---|---|
| `immuno-ada-incidence` | Table | Incidence of Anti-Drug Antibodies (baseline positive, treatment-emergent, persistent, transient) by Treatment | Incidence | ADIS / IS |
| `immuno-ada-titer` | Table | Summary of ADA Titers Among ADA-Positive Subjects | Descriptive | ADIS / IS |
| `immuno-nab` | Table | Incidence of Neutralizing Antibodies Among ADA-Positive Subjects | Incidence | ADIS / IS |
| `immuno-ada-listing` | Listing | Individual ADA / nAb Results by Subject and Visit | none | ADIS / IS |

Notes: impact-of-ADA-on-efficacy/safety cross-tabs are subgroup fan-outs — leave those to
agent 7. Emit the base incidence/titer/nAb candidates here.

---

## `needs_pro_hrqol` — Patient-Reported Outcomes / HRQoL

`category: "pro"` (§14-6/7). **Distinct from core efficacy cognitive/behavioral scales** (e.g.
ADAS-Cog, CIBIC+, NPI-X), which are handled by `efficacy-statistics-planner` (agent 4). This
lane is for dedicated HRQoL instruments — EORTC QLQ-C30, SF-36, EQ-5D, FACT-x, etc.

| candidate_id (pattern) | type | title | method | data_requirements |
|---|---|---|---|---|
| `pro-domain-summary` | Table | Summary of {Instrument} Domain/Subscale Scores by Visit and Treatment | Descriptive | ADQS / QS |
| `pro-cfb` | Table | Change from Baseline in {Instrument} Domain Scores by Visit and Treatment | Descriptive | ADQS / QS |
| `pro-cfb-fig` | Figure | Mean Change from Baseline in {Instrument} Score Over Time by Treatment | Descriptive | ADQS / QS |
| `pro-responder` | Table | Responder Analysis (Meaningful Change Threshold) in {Instrument} by Treatment | Incidence | ADQS / QS |
| `pro-completion` | Table | {Instrument} Questionnaire Completion / Compliance Rates by Visit | Descriptive | ADQS / QS |

Notes: substitute the actual instrument name from `study-model.json` endpoints in `{Instrument}`.
Timepoint and subgroup fan-out is agent 7.

---

## CDISCPILOT01 — the empty-array result

CDISCPILOT01 (Phase II Alzheimer's, xanomeline TTS vs placebo) has **no** special domain:

- **No PK/PD** — no concentration or parameter endpoints declared; `needs_pk` / `needs_pd` false.
- **No oncology** — CNS/Alzheimer's indication; no tumor response; `needs_oncology_response` false.
- **No immunogenicity** — small-molecule transdermal, no ADA endpoint; `needs_immunogenicity` false.
- **No separately-flagged HRQoL** — ADAS-Cog (11), CIBIC+, and NPI-X are the study's cognitive/
  behavioral **efficacy** measures (agent 4's lane, mapped to the 14-3.x efficacy tables in
  `objective-endpoint-tlf-mapping.md`), NOT dedicated HRQoL instruments. `needs_pro_hrqol` false.

With every special-domain flag false, `special-domain-planner` writes exactly:

```json
[]
```

to `outputs/cdiscpilot01/tlf-plan/candidates/special-domain.json`. This is the intended,
correct behavior — it demonstrates the system degrades cleanly and never pollutes a
non-specialty study with fabricated PK/oncology/immunogenicity/PRO outputs. The 31 CDISCPILOT01
TLFs all come from the other three planners (scaffolding, efficacy, safety) plus the variant
expander.
