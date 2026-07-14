# ICH E3 §14 Regulatory Scaffolding Catalog

The catalog of **objective-independent** Tables and Listings that ICH E3 expects of every
clinical study report. These describe *how the study was conducted and who was in it* — they
are mandated by regulatory convention, not by any study objective or endpoint. The
regulatory-scaffolding-planner emits one TLF candidate per catalog entry whose **feature gate**
is satisfied by the study profile.

Each candidate conforms to the shared schema at
`tlf-candidate-schema.md` and MUST carry:

- `traces_to.objective_ids = []` and `traces_to.endpoint_ids = []`
- `traces_to.regulatory_rule =` the ICH E3 section listed below (never null)
- `produced_by = "regulatory-scaffolding-planner"`, `final_id = null`, `priority = "supportive"`

## ICH E3 section reference

The tables below trace to the substantive ICH E3 sections that mandate the *content*; the
tlf-consolidator later files them into the CSR **§14** appendix under the numbering scheme in
`pipeline-contract.md`.

| ICH E3 § | Title | Scaffolding content it mandates |
|---|---|---|
| §10.1 | Disposition of Patients | Enrollment, randomization, completion/withdrawal, by-site accounting |
| §10.2 | Protocol Deviations | Important protocol deviations |
| §11.1 | Data Sets Analysed | Analysis-population/analysis-set accounting (ITT/Safety/Efficacy/Completers) |
| §11.2 | Demographic and Other Baseline Characteristics | Demographics, baseline disease, medical history, prior/concomitant medications |
| §12.1 | Extent of Exposure | Duration/dose/cumulative study-drug exposure |
| §12.3 | Deaths, Other Serious AEs, and Other Significant AEs | Deaths / SAE / AE-leading-to-discontinuation listings (if not tabled by safety planner) |

## Catalog entries

Legend for **Gate**: `always` = emit for every study; otherwise the study-profile flag that
must be true. Category values map to §14 sections per the candidate schema (`disposition`→14-1,
`demographics`→14-2, `exposure`→14-4, `conmeds`→14-7).

| # | Candidate slug | Title | type | category | regulatory_rule | Gate | Notes |
|---|---|---|---|---|---|---|---|
| 1 | `reg-populations-summary` | Summary of Populations | Table | `disposition` | ICH E3 §11.1 | **always** | Analysis-set accounting; defines the denominators every other table cites. |
| 2 | `reg-disposition-eos` | Summary of End of Study Data | Table | `disposition` | ICH E3 §10.1 | **always** | Completion vs. early termination + reasons for discontinuation. |
| 3 | `reg-subjects-by-site` | Summary of Number of Subjects by Site | Table | `disposition` | ICH E3 §10.1 | `multi_site` | Enrollment by (pooled) site; skip for single-site studies. |
| 4 | `reg-demographics-baseline` | Summary of Demographic and Baseline Characteristics | Table | `demographics` | ICH E3 §11.2 | **always** | Age/sex/race/baseline disease severity; baseline comparability of arms. |
| 5 | `reg-exposure-planned` | Summary of Planned Exposure to Study Drug | Table | `exposure` | ICH E3 §12.1 | **always** | Duration and average/cumulative dose; Safety population. |
| 6 | `reg-conmeds-summary` | Summary of Concomitant Medications | Table | `conmeds` | ICH E3 §11.2 | **always** | Concomitant meds by therapeutic class; safety context. |
| 7 | `reg-medical-history` | Summary of Medical History | Table | `disposition` | ICH E3 §11.2 | `medical_history_available` | Baseline medical history by SOC/PT; emit when MH domain in scope. |
| 8 | `reg-protocol-deviations` | Summary of Important Protocol Deviations | Table | `disposition` | ICH E3 §10.2 | `deviations_tracked` | Emit when DV domain / deviation tracking is in scope. |
| 9 | `reg-deaths-listing` | Listing of Deaths | Listing | `disposition` | ICH E3 §12.3 | `not_covered_by_safety` | Emit only if the safety planner is not producing a deaths table. |
| 10 | `reg-sae-listing` | Listing of Serious Adverse Events | Listing | `disposition` | ICH E3 §12.3 | `not_covered_by_safety` | Emit only if safety planner is not tabling SAEs. |
| 11 | `reg-ae-discontinuation-listing` | Listing of AEs Leading to Discontinuation | Listing | `disposition` | ICH E3 §12.3 | `not_covered_by_safety` | Emit only if safety planner is not covering it. |

Entries 1–6 form the **core set** present in essentially every multi-arm CSR. Entries 7–11 are
feature-gated and are typically **absent** from the CDISCPILOT01 CSR ground truth (see below):
CDISCPILOT01 does not report standalone medical-history or protocol-deviation summary tables,
and its deaths/SAE/discontinuation information is carried inside the safety §14-5 tables and the
End-of-Study disposition table — so the scaffolding planner does not duplicate them.

## Feature-gating rules

- **`multi_site`** — from study-profile. If true, emit `reg-subjects-by-site`; if false or a
  single-site study, skip it (there is nothing to break out by site).
- **Single-arm vs. comparative** — from `treatment_arms` in study-model. Comparative studies
  get a between-group comparison / p-value column on disposition, demographics, and end-of-study
  tables; single-arm studies omit it. This affects shell content, not whether the candidate is
  emitted. Record the choice in `notes`.
- **`medical_history_available` / `deviations_tracked`** — emit entries 7–8 only when the study
  actually collects that data (MH / DV domains in scope). Default off unless the profile flags it.
- **`not_covered_by_safety`** — entries 9–11 exist to guarantee ICH E3 §12.3 information appears
  *somewhere*. Because the safety-analysis-planner normally tables deaths/SAEs/discontinuations,
  the default is to **not** emit these as separate listings; emit them (as `Listing`) only when
  the study has a safety signal not otherwise tabled, and always add a `notes` entry saying they
  may be deduped at consolidation.
- **Missing study-profile.json** — fall back conservatively: assume `multi_site = true`, emit the
  core set (1–6), skip 7–11, and note the assumption in each candidate.

## CDISCPILOT01 expected candidates (exact)

CDISCPILOT01 is Phase II, 3-arm (Placebo / Xanomeline Low 54 mg / Xanomeline High 81 mg),
multi-site (18 sites, some pooled). The scaffolding planner emits exactly the **6 core-set**
candidates — matching Section 3 of `objective-endpoint-tlf-mapping.md` and the CSR ground-truth
tables `csr-outputs-md/cdiscpilot01-tlf-T-14-*`:

| candidate_id | title | type | category | regulatory_rule | population | → final_id |
|---|---|---|---|---|---|---|
| `reg-populations-summary` | Summary of Populations | Table | `disposition` | ICH E3 §11.1 | All Subjects | T-14-1.01 |
| `reg-disposition-eos` | Summary of End of Study Data | Table | `disposition` | ICH E3 §10.1 | Intent-to-Treat | T-14-1.02 |
| `reg-subjects-by-site` | Summary of Number of Subjects by Site | Table | `disposition` | ICH E3 §10.1 | All Subjects | T-14-1.03 |
| `reg-demographics-baseline` | Summary of Demographic and Baseline Characteristics | Table | `demographics` | ICH E3 §11.2 | Intent-to-Treat | T-14-2.01 |
| `reg-exposure-planned` | Summary of Planned Exposure to Study Drug | Table | `exposure` | ICH E3 §12.1 | Safety | T-14-4.01 |
| `reg-conmeds-summary` | Summary of Concomitant Medications | Table | `conmeds` | ICH E3 §11.2 | Safety | T-14-7.04 |

The by-site table (entry 3) is included because `multi_site` is true. Entries 7–11 are **not**
emitted — CDISCPILOT01's CSR has no standalone medical-history, protocol-deviation, or
deaths/SAE/discontinuation scaffolding output (that content lives in the disposition and safety
tables). The `→ final_id` column is what the tlf-consolidator assigns; the planner leaves
`final_id = null`.

### Example candidate (CDISCPILOT01 `reg-populations-summary`)

```jsonc
{
  "candidate_id": "reg-populations-summary",
  "type": "Table",
  "category": "disposition",
  "title": "Summary of Populations",
  "traces_to": {
    "objective_ids": [],
    "endpoint_ids": [],
    "regulatory_rule": "ICH E3 §11.1"
  },
  "analysis": {
    "method": "Descriptive",
    "population": "All Subjects",
    "timepoint": null,
    "imputation": "none",
    "subgroup": null,
    "comparison": null
  },
  "data_requirements": { "adam": ["ADSL"], "sdtm_source": ["DM", "DS"] },
  "status": "planned",
  "status_reason": null,
  "priority": "supportive",
  "produced_by": "regulatory-scaffolding-planner",
  "final_id": null,
  "notes": ["Defines analysis-set denominators (ITT/Safety/Efficacy/Completers) for all other tables."]
}
```
