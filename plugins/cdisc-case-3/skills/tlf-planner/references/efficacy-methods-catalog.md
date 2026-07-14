# Efficacy Methods Catalog

The domain knowledge behind `efficacy-statistics-planner`: how an endpoint's
`parsed.measure_type` maps to a *stack* of statistical methods, how the objective/endpoint
**level** prunes that stack, how the estimand's intercurrent-event strategy picks the
imputation, and the fully worked CDISCPILOT01 expansion.

Every method below becomes one [TLF candidate](tlf-candidate-schema.md)
with `analysis.method` set to the enum value in **bold**. This agent emits the **base method
set** only; `analysis-variant-expander` (agent #7) multiplies each base method across
imputation / subgroup / population / extra-timepoint dimensions.

---

## 1. `measure_type` → method-family mapping

| `measure_type` | Typical instruments | Primary analysis | Sensitivity / model-based | Descriptive companion | Categorical/responder |
|---|---|---|---|---|---|
| **continuous** (change-from-baseline) | ADAS-Cog (11/14), NPI-X total, lab CFB, weight CFB | **ANCOVA** (CFB ~ baseline + treatment + strata) | **MMRM** (repeated measures across visits, unstructured covariance) | **Descriptive** mean & mean-change over time | (responder cut-offs only if SAP defines them) |
| **global-impression** | CIBIC+, CGI-C, PGI-C | **ANOVA** (no baseline covariate; the score *is* the change) or **Descriptive** summary | — | **Descriptive** summary at timepoint | **CMH** (row-mean-score / ordinal, dose-stratified responder analysis) |
| **categorical** (nominal) | responder yes/no, best category | **CMH** (general association) or **Fisher** (small cells) | Logistic regression (`none` method → note) | **Descriptive** n(%) frequency | **CMH** |
| **ordinal** | ordered response scale | **CMH** (row-mean-score / modified ridit) | Proportional-odds model | **Descriptive** frequency | **CMH** |
| **event** (time-to-event efficacy) | time to progression / response / clinical worsening | **KaplanMeier** (curves + median) + **LogRank** (group test) | **Cox** proportional hazards (HR + 95% CI) | **Descriptive** event/censor counts, rate at timepoint | — |
| **count** / **rate** | exacerbation count, event rate/exposure | **Descriptive** mean count / rate | Poisson / Negative-Binomial regression (`method: "none"` + note; no dedicated enum) | **Descriptive** mean & rate | — |

Notes:
- **ANCOVA vs ANOVA.** Use ANCOVA when a genuine baseline exists as a covariate (ADAS-Cog).
  Use ANOVA when the instrument has no baseline and the measured value already represents change
  (CIBIC+ — see the statistical-methods-guide). Both are the `analysis.method` enum values
  `ANCOVA` / `ANOVA` respectively.
- **MMRM** is the standard repeated-measures sensitivity/confirmation for a continuous CFB
  primary endpoint. It uses all observed post-baseline visits under MAR, so it needs **no
  imputation** (`imputation: "none"`).
- **CMH** (Cochran-Mantel-Haenszel) is the categorical/ordinal companion to a
  global-impression primary endpoint — it tests the distribution of the ordered categories
  across treatment groups, optionally stratified (e.g. by pooled site), and supports a
  dose-response/row-mean-score reading.
- For **event** efficacy endpoints, always pair KM with a log-rank test and (usually) a Cox
  model; emit the KM as a `Figure`, the log-rank/Cox as `Table`s if the SAP tabulates them, else
  fold the log-rank p-value into the KM figure annotation.

---

## 2. The standard analysis stacks

### 2a. Continuous change-from-baseline endpoint (e.g. ADAS-Cog)

Primary-level stack (3 base candidates):

1. **ANCOVA** — "Primary Endpoint Analysis: CFB to {timepoint}". Model
   `CHG ~ BASE + treatment + pooled-site`; LS-means per arm, pairwise vs placebo, and a
   dose-response trend test (treatment coded as continuous dose) when the design is a dose study.
   `imputation` from the estimand (treatment-policy → LOCF).
2. **MMRM** — "Repeated Measures Analysis of CFB to {timepoint}". Longitudinal, all visits,
   unstructured covariance. Sensitivity/confirmation of the ANCOVA result. `imputation: "none"`.
3. **Descriptive** — "Mean and Mean Change from Baseline over Time". Per-arm mean, SD, median,
   range at every visit + change stats. `method: "Descriptive"`, `imputation: "none"`,
   `priority: "supportive"`.

Secondary-level: **ANCOVA only**, one candidate per stated timepoint. No MMRM, no
descriptive-over-time.

### 2b. Global-impression / categorical endpoint (e.g. CIBIC+)

Primary-level stack (2 base candidates):

1. **Descriptive/ANOVA** — "Primary Endpoint Analysis: Summary at {timepoint}". Per-arm n,
   mean, SD, median, range of the 1–7 scale + dose-response p-value (ANOVA on the score).
2. **CMH** — "Categorical Analysis". Frequency of each improvement/worsening category by arm +
   CMH row-mean-score p-value (dose-response over the ordered categories).

Secondary-level: **Descriptive/ANOVA summary only**, one per stated timepoint. No CMH.

### 2c. Time-to-event efficacy endpoint

Primary-level stack: **KaplanMeier** figure (+ log-rank annotation) + **LogRank** test table +
**Cox** HR table + **Descriptive** event/censor summary. Secondary-level: KM + descriptive.
(Note: CDISCPILOT01's only time-to-event output — F-14-1 — is a *safety* dermatologic KM
handled by agent #5, not here.)

### 2d. Count / rate efficacy endpoint

Primary-level: model-based (**Poisson**/Negative-Binomial — emit as `method: "none"` with a
`notes` entry naming the model, since there is no dedicated enum value) + **Descriptive** mean
count/rate. Secondary-level: descriptive only.

---

## 3. How objective LEVEL changes the stack

| Level | Continuous CFB | Global-impression / categorical | Event | Count/rate |
|---|---|---|---|---|
| **Primary** | ANCOVA + MMRM + Descriptive-over-time (3) | Descriptive/ANOVA + CMH (2) | KM + LogRank + Cox + Descriptive | Model + Descriptive |
| **Secondary** | ANCOVA, ×(stated timepoints) | Descriptive/ANOVA, ×(stated timepoints) | KM + Descriptive | Descriptive |
| **Exploratory** | Descriptive only | Descriptive only | KM (if any) | Descriptive |

Rationale: primary endpoints carry the confirmatory claim and the multiplicity budget, so they
must be shown robust across method families (headline + sensitivity + model-based + descriptive).
Secondary/exploratory endpoints are supportive and get a single descriptive-or-primary-method
analysis. **Per-timepoint replication of a timepoint the endpoint text explicitly names** (e.g.
"Weeks 8 and 16") is endpoint-intrinsic and belongs here; replication across *un-stated*
timepoints, imputation alternatives, subgroups, and populations is the variant expander's job.

---

## 4. Estimand intercurrent-event strategy → imputation

| Strategy | Base-candidate `imputation` | Reasoning |
|---|---|---|
| **Treatment Policy** | `LOCF` | Analyze regardless of interruption; LOCF is the conventional single-imputation primary. |
| **Hypothetical** | `MI` (or `none` for MMRM) | Estimate the value had the ICE not occurred; multiple imputation or a model under MAR. |
| **Composite** | `none` | ICE folded into a composite endpoint definition; note it. |
| **While-on-Treatment** | `none` | Only on-treatment data; no carry-forward. |
| **Principal Stratum** | `none` | Subpopulation-defined; per SAP. |

Always: MMRM and Descriptive-over-time candidates use `imputation: "none"`. When the strategy is
inferred rather than SAP-stated, add a `notes` entry (e.g.
`"LOCF assumed from treatment-policy strategy — no SAP provided"`).

---

## 5. Fully worked CDISCPILOT01 expansion

Study: Phase II, 3-arm dose study (Placebo / Xanomeline Low 54 mg / Xanomeline High 81 mg),
`comparison: "dose-response"`. Efficacy population. EST1 intercurrent-event strategy =
**Treatment Policy** → LOCF for single-imputation primaries.

### OBJ1 (Primary, efficacy) — END1 & END2

**END1 — ADAS-Cog (11), Week 24, `continuous`, Primary → 3 candidates**

| candidate_id | method | timepoint | imputation | priority | maps toward CSR |
|---|---|---|---|---|---|
| `eff-END1-ancova-wk24` | ANCOVA | Week 24 | LOCF | primary | T-14-3.01 (+ .07/.08/.09 via agent #7) |
| `eff-END1-mmrm` | MMRM | Week 24 | none | supportive | T-14-3.11 |
| `eff-END1-descriptive-time` | Descriptive | (over time) | none | supportive | T-14-3.10 |

**END2 — CIBIC+, Week 24, `global-impression`, Primary → 2 candidates**

| candidate_id | method | timepoint | imputation | priority | maps toward CSR |
|---|---|---|---|---|---|
| `eff-END2-anova-wk24` | ANOVA | Week 24 | LOCF | primary | T-14-3.02 |
| `eff-END2-cmh` | CMH | Week 24 | LOCF | primary | T-14-3.13 |

### OBJ3 (Secondary, behavior/dose-dependent improvement) — END6, END7, END8

**END6 — ADAS-Cog (11), Weeks 8 & 16, `continuous`, Secondary → 2 candidates**

| candidate_id | method | timepoint | imputation | priority | maps toward CSR |
|---|---|---|---|---|---|
| `eff-END6-ancova-wk8` | ANCOVA | Week 8 | LOCF | secondary | T-14-3.03 |
| `eff-END6-ancova-wk16` | ANCOVA | Week 16 | LOCF | secondary | T-14-3.05 |

**END7 — CIBIC+, Weeks 8 & 16, `global-impression`, Secondary → 2 candidates**

| candidate_id | method | timepoint | imputation | priority | maps toward CSR |
|---|---|---|---|---|---|
| `eff-END7-descriptive-wk8` | Descriptive | Week 8 | LOCF | secondary | T-14-3.04 |
| `eff-END7-descriptive-wk16` | Descriptive | Week 16 | LOCF | secondary | T-14-3.06 |

**END8 — Mean NPI-X total, Week 4→24 (windowed), `continuous`, Secondary → 1 candidate**

| candidate_id | method | timepoint | imputation | priority | maps toward CSR |
|---|---|---|---|---|---|
| `eff-END8-descriptive-windowed` | Descriptive | Weeks 4–24 (windowed) | none | secondary | T-14-3.12 |

### Excluded

- **END3/END4/END5** — safety endpoints (OBJ2). Handled by `safety-analysis-planner` (agent #5).
- **END9/END10/END11** — `resolved: false` (`"*** To be determined ***"`). Emit **nothing**;
  the feasibility/critic layer raises them as clarification action items.

### Total

**10 base efficacy candidates** (END1: 3, END2: 2, END6: 2, END7: 2, END8: 1). The
`analysis-variant-expander` grows these to the 13 §14-3 CSR tables by adding END1's completers /
observed-cases / windowed sensitivity (T-14-3.07) and Male/Female subgroup splits
(T-14-3.08/.09); `tlf-consolidator` assigns the final `T-14-3.xx` numbers.

---

## 6. Data-requirement hints (best-effort)

| Measure | ADaM | SDTM |
|---|---|---|
| ADAS-Cog (11/14) | `ADQSADAS`, `ADSL` | `QS`, `DM` |
| CIBIC+ | `ADQSCIBC`, `ADSL` | `QS`, `DM` |
| NPI-X | `ADQSNPIX`, `ADSL` | `QS`, `DM` |
| Generic questionnaire/PRO | `ADQS`, `ADSL` | `QS`, `DM` |
| Time-to-event efficacy | `ADTTE`, `ADSL` | derived, `DM` |

Always include `ADSL`/`DM` for population flags and treatment/site variables.
