# Safety Table Families

How the `safety-analysis-planner` turns each terse safety **endpoint keyword** into a whole
**family** of standard CSR outputs. Every candidate this skill emits conforms to
`tlf-candidate-schema.md`.

A safety endpoint in a USDM is a keyword, not a table. "Adverse events" is not one table — it is
the AE family. This file is the lookup from keyword → family, and the record of which members use
which method, how they are gated, and the fully worked CDISCPILOT01 output.

---

## Keyword → family mapping

### AE family — trigger: "adverse events", domain_hint `safety-ae`

| Family member | `type` | `method` | `category` | Notes |
|---|---|---|---|---|
| TEAE incidence by SOC / PT, by treatment group | Table | `Incidence` | `safety-ae` | Counts n(%) and event counts by System Organ Class and Preferred Term. |
| SAE incidence by SOC / PT | Table | `Incidence` | `safety-ae` | Serious TEAEs only. |
| AEs leading to discontinuation | Table | `Incidence` | `safety-ae` | Standard family member; emit when the study reports it. |
| Deaths | Table | `Incidence` | `safety-ae` | Standard family member. |
| AEs by maximum severity / by relationship | Table | `Incidence` | `safety-ae` | Standard family members. |
| **Time-to-event safety figure (Kaplan-Meier)** | **Figure** | **`KaplanMeier`** | `safety-ae` | **Gated on `study-profile.flags.needs_tte_safety_figure`.** Log-rank comparison. e.g. "Time to Dermatologic Event by Treatment Group". |

The **TEAE incidence** and **SAE incidence** tables are the always-present core. Discontinuation /
deaths / severity / relationship tables are conventional family members; emit them where the study
reports separate displays. The `data-feasibility-checker` (agent 8) downgrades any member the study
data cannot support, and the `tlf-consolidator` (agent 9) dedups. Over-produce rather than
self-censor — but see the CDISCPILOT01 worked output below for the members that map to that study's
CSR ground truth.

### Lab family — trigger: "laboratory evaluations", "lab", domain_hint `safety-lab`

| Family member | `type` | `method` | `category` | Notes |
|---|---|---|---|---|
| Summary statistics for continuous lab values (+ change from baseline) | Table | `Descriptive` | `safety-lab` | Mean (SD) and CFB by visit, by lab parameter. |
| Frequency of normal / abnormal — beyond normal range | Table | `ShiftTable` | `safety-lab` | Shift counts vs. reference range. |
| Frequency of normal / abnormal — clinically significant change from previous visit | Table | `ShiftTable` | `safety-lab` | Shift counts. |
| Shifts vs. threshold ranges, **by visit** | Table | `ShiftTable` | `safety-lab` | **Tested with CMH (Cochran-Mantel-Haenszel).** Record `analysis.comparison: "Cochran-Mantel-Haenszel"`. |
| Shifts vs. threshold ranges, **overall** | Table | `ShiftTable` | `safety-lab` | **CMH.** |
| Hy's Law shifts | Table | `ShiftTable` | `safety-lab` | Transaminase / bilirubin threshold shifts. |

**CMH usage:** the threshold-based shift tables (by-visit and overall) apply a Cochran-Mantel-Haenszel
test across the ordered shift categories; note "CMH" / "Cochran-Mantel-Haenszel" in
`analysis.comparison`. The frequency and Hy's Law tables are descriptive shift counts.

### Vitals family — trigger: "vital signs (...)", "weight", "blood pressure", domain_hint `safety-vs`

| Family member | `type` | `method` | `category` | Notes |
|---|---|---|---|---|
| Vital signs at baseline & end of treatment | Table | `Descriptive` | `safety-vs` | By vital parameter (SBP, DBP, HR, temp, weight). |
| Vital signs change from baseline at EOT | Table | `Descriptive` | `safety-vs` | CFB summary. |
| Weight change from baseline at EOT | Table | `Descriptive` | `safety-vs` | Weight-specific CFB. |

### ECG family — trigger: "ECG", "electrocardiogram" endpoint present

| Family member | `type` | `method` | `category` | Notes |
|---|---|---|---|---|
| ECG (QT/QTc) summary & change from baseline | Table | `Descriptive` | `safety-vs` | Emit **only** when an ECG endpoint keyword is present in `study-model.json`. No dedicated profile flag — gate on the endpoint. |
| ECG shifts (normal / abnormal, categorical QTc bands) | Table | `ShiftTable` | `safety-vs` | Same gating. |

### Conmeds — trigger: concomitant-medication safety endpoint

| Family member | `type` | `method` | `category` | Notes |
|---|---|---|---|---|
| Summary of concomitant medications | Table | `Incidence` | `conmeds` | The `conmeds` category exists in the shared schema, but the standard conmeds table is **objective-independent scaffolding produced by `regulatory-scaffolding-planner` (agent 3)**. Emit here **only** if a safety endpoint explicitly names conmed safety and agent 3 is not producing it. For CDISCPILOT01, do **not** emit — T-14-7.04 belongs to agent 3. |

---

## Gating rules

| Family member | Gate |
|---|---|
| AE core (TEAE, SAE incidence) | any `safety-ae` endpoint present |
| Kaplan-Meier time-to-event safety figure | `study-profile.flags.needs_tte_safety_figure == true` |
| Lab family | any `safety-lab` endpoint present |
| Vitals family | any `safety-vs` endpoint present |
| ECG family | an ECG endpoint keyword present in `study-model.json` (no profile flag) |
| Conmeds | conmed-safety endpoint present **and** not produced by agent 3 (normally skip) |

Unresolved safety endpoints (`resolved: false`) produce **no** candidates — record them in the
summary so `tlf-traceability-critic` raises clarification action items.

---

## Method quick reference

| Method | Used by |
|---|---|
| `Incidence` | AE / SAE incidence, discontinuation, deaths, severity/relationship (counts n(%)) |
| `Descriptive` | continuous lab summary, vital-signs summaries & change-from-baseline, ECG summary |
| `ShiftTable` | all lab shift/frequency tables, Hy's Law, ECG shifts (threshold shifts tested with **CMH**) |
| `KaplanMeier` | the gated time-to-event safety figure (log-rank comparison) |

---

## Fully worked CDISCPILOT01 output

CDISCPILOT01's OBJ2 (safety) has three endpoints. `study-profile.flags.needs_tte_safety_figure`
is `true` (transdermal therapy with a dermatologic AE signal), so the Kaplan-Meier figure **is**
emitted. This produces **12 candidates** that map 1:1 to the CSR ground truth
(`csr-outputs-md/`): 3 AE (incl. the figure), 6 lab, 3 vitals. The `final_id` column shows the
number the `tlf-consolidator` will assign; this planner leaves `final_id: null`.

| candidate_id | endpoint | category | method | title | → final_id |
|---|---|---|---|---|---|
| `ae-END3-teae-incidence-soc-pt` | Endpoint_3 | safety-ae | Incidence | Incidence of Treatment-Emergent Adverse Events by Treatment Group | T-14-5.01 |
| `ae-END3-sae-incidence` | Endpoint_3 | safety-ae | Incidence | Incidence of Treatment-Emergent Serious Adverse Events by Treatment Group | T-14-5.02 |
| `ae-END3-km-time-to-derm-event` | Endpoint_3 | safety-ae | KaplanMeier | Time to Dermatologic Event by Treatment Group | F-14-1 |
| `vs-END4-baseline-eot` | Endpoint_4 | safety-vs | Descriptive | Summary of Vital Signs at Baseline and End of Treatment | T-14-7.01 |
| `vs-END4-cfb-eot` | Endpoint_4 | safety-vs | Descriptive | Summary of Vital Signs Change from Baseline at End of Treatment | T-14-7.02 |
| `vs-END4-weight-cfb-eot` | Endpoint_4 | safety-vs | Descriptive | Summary of Weight Change from Baseline at End of Treatment | T-14-7.03 |
| `lab-END5-continuous-summary` | Endpoint_5 | safety-lab | Descriptive | Summary Statistics for Continuous Laboratory Values | T-14-6.01 |
| `lab-END5-freq-normal-abnormal-range` | Endpoint_5 | safety-lab | ShiftTable | Frequency of Normal and Abnormal (Beyond Normal Range) Laboratory Values During Treatment | T-14-6.02 |
| `lab-END5-freq-normal-abnormal-csc` | Endpoint_5 | safety-lab | ShiftTable | Frequency of Normal and Abnormal (Clinically Significant Change from Previous Visit) Laboratory Values During Treatment | T-14-6.03 |
| `lab-END5-shift-threshold-byvisit` | Endpoint_5 | safety-lab | ShiftTable (CMH) | Shifts of Laboratory Values During Treatment, Categorized Based on Threshold Ranges, by Visit | T-14-6.04 |
| `lab-END5-shift-threshold-overall` | Endpoint_5 | safety-lab | ShiftTable (CMH) | Shifts of Laboratory Values During Treatment, Categorized Based on Threshold Ranges | T-14-6.05 |
| `lab-END5-shift-hys-law` | Endpoint_5 | safety-lab | ShiftTable | Shifts of Hy's Law Values During Treatment | T-14-6.06 |

`T-14-4.01` (drug exposure) and `T-14-7.04` (concomitant medications) support OBJ2 but are
objective-independent scaffolding — **produced by `regulatory-scaffolding-planner` (agent 3), not
here.** Endpoints END9/END10/END11 are unresolved and belong to secondary objectives OBJ4-6; they
are not safety endpoints and produce nothing here.

### Example candidate object (the gated Kaplan-Meier figure)

```jsonc
{
  "candidate_id": "ae-END3-km-time-to-derm-event",
  "type": "Figure",
  "category": "safety-ae",
  "title": "Time to Dermatologic Event by Treatment Group",
  "traces_to": {
    "objective_ids": ["Objective_2"],
    "endpoint_ids": ["Endpoint_3"],
    "regulatory_rule": null
  },
  "analysis": {
    "method": "KaplanMeier",
    "population": "Safety",
    "timepoint": null,
    "imputation": "none",
    "subgroup": null,
    "comparison": "log-rank, by treatment group"
  },
  "data_requirements": {
    "adam": ["ADTTE", "ADAE", "ADSL"],
    "sdtm_source": ["AE", "DM"]
  },
  "status": "planned",
  "status_reason": null,
  "priority": "primary",
  "produced_by": "safety-analysis-planner",
  "final_id": null,
  "notes": ["Emitted because study-profile.flags.needs_tte_safety_figure=true (dermatologic AE signal, transdermal therapy)."]
}
```

The TEAE incidence table (`Incidence`) and a lab threshold-shift table (`ShiftTable` with
`comparison: "Cochran-Mantel-Haenszel"`) follow the same shape with `type: "Table"` and their own
`category` / `method` / `data_requirements`.
