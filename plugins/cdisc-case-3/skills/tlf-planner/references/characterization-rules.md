# Characterization Rules

How the `study-characterizer` skill infers each field of `study-profile.json` from
`study-model.json`. Rules are heuristics; when a value is inferred by convention rather than from
explicit study text, record the assumption in `characterizer_notes` so the traceability critic can
see it. **Fidelity over guessing:** if a dimension is genuinely undeterminable, use `null`/`unknown`
and add a note rather than inventing a value.

---

## 1. Descriptive dimensions

### phase
- Read `study-model.phase` directly (already decoded by the normalizer): `"Phase I"`, `"Phase II"`,
  `"Phase III"`, `"Phase IV"`.
- If missing/`null`, leave `null` and note it. Do not guess phase from arm count alone.

### arm_count / arms
- `arm_count` = length of `treatment_arms[]`.
- `arms[]` = each arm's `name`, `type`, `dose`, copied verbatim.

### control_type
- Any arm with `type == "Placebo"` → `placebo`.
- Else if ≥2 arms and no placebo → `active` (active-controlled).
- Else if exactly 1 arm → `none` (uncontrolled/single-arm).
- Else `unknown`.

### design
Decision order (first match wins):
1. **single-arm** — exactly 1 treatment arm.
2. **crossover** — `visit_schedule`/epochs indicate subjects receive more than one treatment in
   sequence (epoch names like "Period 1 / Period 2", "Crossover", washout epochs), or study text
   says crossover.
3. **dose-finding** — multiple arms that are **escalating dose levels of the same investigational
   drug** with no fixed comparator arm, usually Phase I (arm names like "Cohort 1 / 2 / 3", "10 mg /
   20 mg / 40 mg"). A placebo + two fixed doses of one drug that is being *confirmed* (not titrated
   to find a dose) is **parallel**, not dose-finding.
4. **parallel** — default for a randomized study with fixed, concurrently-run arms (incl.
   placebo + fixed active doses).
5. **unknown** — none of the above can be determined.

### blinding
- Search arm/objective/study text for keywords: `double-blind`/`double blind` → `double-blind`;
  `single-blind` → `single-blind`; `open-label`/`open label` → `open-label`.
- A placebo arm strongly implies at least single-blind; if a placebo exists but no keyword, default
  to `double-blind` for Phase II/III and note the assumption.
- Else `unknown`.

### therapeutic_area / indication
1. Infer the **indication** from the measures named in endpoints and from arm/drug names.
2. Map indication → **therapeutic_area** using the table below.

| Indication signals (measures, drugs, keywords) | indication | therapeutic_area |
|---|---|---|
| ADAS-Cog, CIBIC+, NPI-X, DAD, MMSE, "cognition", Alzheimer's, dementia, xanomeline | Alzheimer's Disease | CNS |
| tumor response, RECIST, ORR, PFS, OS, carcinoma, lymphoma, oncology drug names | (the cancer) | Oncology |
| HbA1c, fasting glucose, insulin, diabetes | Diabetes | Metabolic |
| LDL, blood pressure, ejection fraction, MACE, heart failure | (the CV condition) | Cardiology |
| FEV1, asthma, COPD, exacerbations | (the resp. condition) | Respiratory |
| PASI, EASI, psoriasis, atopic dermatitis, eczema | (the skin condition) | Dermatology |
| viral load, CD4, bacterial culture, antibiotic/antiviral names | (the infection) | Infectious Disease |
| DAS28, ACR20, RA, lupus, IBD, Crohn's | (the condition) | Immunology |

If no signal matches, set `indication: null`, `therapeutic_area: "other"`, and note it.

### multi_site
- `true` when there is evidence of more than one investigational site: an enrollment-by-site table
  in scaffolding, site/center references in the model, or a Phase II/III confirmatory design (these
  are effectively always multi-site).
- Default `true` for Phase II/III; `false` only when the study is clearly single-center.
- Note when the value is a convention default.

---

## 2. Special-domain flags (gate `special-domain-planner`, agent 6)

Scan objectives + endpoints `text`, `parsed.measure`, `parsed.domain_hint`, arm names, and the
inferred indication. Set `true` on any match; otherwise `false`.

| Flag | Fires when… | Keyword / pattern triggers |
|---|---|---|
| `needs_pk` | study measures drug exposure/kinetics | pharmacokinetic(s), PK, concentration, Cmax, Tmax, AUC, half-life, clearance, CL, Vd; `domain_hint == "pk"` |
| `needs_pd` | study measures a pharmacodynamic/target-engagement marker distinct from the efficacy endpoint | pharmacodynamic(s), PD, target engagement, receptor occupancy, biomarker response |
| `needs_immunogenicity` | biologic with anti-drug-antibody assessment | immunogenicity, anti-drug antibody, ADA, neutralizing antibody, NAb |
| `needs_oncology_response` | oncology indication **and** tumor-response endpoint | therapeutic_area == Oncology AND any of: ORR, objective response, DOR, PFS, OS, RECIST, tumor response, best overall response |
| `needs_pro_hrqol` | patient-reported / quality-of-life instrument | patient-reported, PRO, quality of life, HRQoL, EQ-5D, SF-36, EORTC QLQ, PROMIS, VAS pain |
| `needs_tte_safety_figure` | a safety event conventionally shown as a Kaplan-Meier time-to-event curve | "time to <safety event>"; dermatologic / application-site / injection-site event in a transdermal (TTS/patch) or injectable study; any safety endpoint whose analysis is survival/time-to-event |

**Disambiguation notes:**
- **Clinician-rated cognitive/behavioral scales** (ADAS-Cog, CIBIC+, NPI-X) are **efficacy**, not
  PRO. `needs_pro_hrqol` stays `false` for them. A PRO is completed *by the patient*.
- `needs_pd` is only for a pharmacodynamic marker that is *separate* from the primary efficacy
  measure; do not set it just because efficacy is measured.
- `needs_tte_safety_figure` is a **safety** flag (drives F-14-x from `safety-analysis-planner`), not
  an efficacy time-to-event. Oncology PFS/OS survival curves are covered by
  `needs_oncology_response`, not this flag.

---

## 3. Subgroup flags (drive `analysis-variant-expander`, agent 7)

| Flag | Fires when… |
|---|---|
| `needs_subgroup_by_sex` | an estimand/SAP names sex as a subgroup, OR (convention) a Phase III confirmatory efficacy study — default `true`, mark as assumption |
| `needs_subgroup_by_region` | multi-national / multi-region enrollment, or region/geography named as a stratification factor. Default `false` for single-country studies |

Convention-set subgroup flags **must** be justified in `characterizer_notes`.

---

## 4. Worked example — CDISCPILOT01

Input: `study-model.json` for the CDISC Pilot Study (xanomeline in Alzheimer's).

Signals in the model:
- `phase == "Phase III"`.
- 3 arms: Placebo, Xanomeline Low Dose (54 mg), Xanomeline High Dose (81 mg) → placebo + two fixed
  doses of one drug, run concurrently.
- Efficacy measures: ADAS-Cog (11), CIBIC+, NPI-X (clinician-rated cognition/behavior).
- Safety endpoints: adverse events, vital signs, laboratory evaluations. Xanomeline is delivered by
  a **transdermal therapeutic system (TTS)** and carries a dermatologic (application-site) AE
  signal.
- Estimand EST1 references group mean change in the primary efficacy parameters; SAP slices the
  primary endpoint by **sex** (Male / Female subgroup tables T-14-3.08 / .09).

Resulting `study-profile.json`:

```jsonc
{
  "study_id": "CDISCPILOT01",
  "study_name": "Safety and Efficacy of Xanomeline TTS in Subjects with Mild to Moderate Alzheimer's Disease",
  "source_model": "outputs/cdiscpilot01/tlf-plan/study-model.json",

  "phase": "Phase II",
  "design": "parallel",
  "therapeutic_area": "CNS",
  "indication": "Alzheimer's Disease",
  "blinding": "double-blind",
  "arm_count": 3,
  "arms": [
    { "name": "Placebo", "type": "Placebo", "dose": null },
    { "name": "Xanomeline Low Dose", "type": "Active", "dose": "54 mg" },
    { "name": "Xanomeline High Dose", "type": "Active", "dose": "81 mg" }
  ],
  "control_type": "placebo",
  "multi_site": true,

  "flags": {
    "needs_pk": false,
    "needs_pd": false,
    "needs_immunogenicity": false,
    "needs_oncology_response": false,
    "needs_pro_hrqol": false,
    "needs_tte_safety_figure": true,
    "needs_subgroup_by_sex": true,
    "needs_subgroup_by_region": false
  },

  "characterizer_notes": [
    "phase from study-model.phase = 'Phase II'.",
    "design=parallel: 3 fixed arms (Placebo + 2 xanomeline doses) run concurrently; no crossover epochs and not dose-titration, so not dose-finding.",
    "control_type=placebo: one arm has type Placebo.",
    "blinding=double-blind: placebo-controlled Phase II; assumed double-blind (no explicit keyword in study-model).",
    "therapeutic_area=CNS / indication=Alzheimer's Disease: inferred from ADAS-Cog, CIBIC+, NPI-X measures and xanomeline.",
    "multi_site=true: multi-site study convention (by-site enrollment table expected).",
    "needs_pk/needs_pd=false: no pharmacokinetic or pharmacodynamic endpoints declared.",
    "needs_immunogenicity=false: small-molecule transdermal therapy, no ADA assessment.",
    "needs_oncology_response=false: not an oncology indication.",
    "needs_pro_hrqol=false: ADAS-Cog/CIBIC+/NPI-X are clinician-rated efficacy scales, not patient-reported outcomes.",
    "needs_tte_safety_figure=true: xanomeline TTS carries a dermatologic (application-site) AE signal; conventionally shown as a Kaplan-Meier time-to-dermatologic-event figure (F-14-1).",
    "needs_subgroup_by_sex=true: SAP pre-specifies sex subgroup analyses of the primary endpoint (Male/Female tables).",
    "needs_subgroup_by_region=false: single-region study; region not a stratification factor."
  ]
}
```

**Key takeaway for generalization:** every classification above is derived from signals present in
`study-model.json` plus the rules in this file — nothing is hard-coded to CDISCPILOT01. A different
study (e.g. an oncology Phase II with RECIST endpoints and PK sampling) flows through the same rules
and lights up `needs_oncology_response` and `needs_pk` instead, gating `special-domain-planner`
accordingly.
