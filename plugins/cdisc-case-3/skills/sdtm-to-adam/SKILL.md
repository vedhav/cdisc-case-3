---
name: sdtm-to-adam
description: "Generate ADaM datasets from SDTM data using {admiral} R code, DRIVEN BY the ADaM spec (adam-spec.json) produced upstream by tlf-analysis-spec. The derived ADaM MUST satisfy the spec's datasets/parameters/variables/populations and its MANDATORY derivation rules: (1) day-based analysis-visit windowing that never drops unscheduled/early-termination visits, (2) LOCF records (DTYPE='LOCF', ANL01FL='Y') at the endpoint visit, (3) SITEGR1 pooling on RANDOMIZED (ITTFL='Y') counts. Enforces a data-quality gate on analysis-set N and checks conformance with metacore/metatools. Use this skill whenever the user has an adam-spec.json (or reviewed ADaM spec) plus SDTM datasets and wants ADaM datasets. Also trigger on 'ADaM derivation', 'ADaM generation', 'SDTM to ADaM', 'admiral code', 'derive analysis datasets', 'spec-driven ADaM'. Third step in the Protocol->SAP->TLF-plan->analysis/ADaM-spec->ADaM->TLF pipeline."
---

# SDTM-to-ADaM Generator (spec-driven)

## Purpose

This skill derives complete ADaM datasets from SDTM data using `{admiral}` R code, **driven by the
ADaM specification (`adam-spec.json`)** produced upstream by the `tlf-analysis-spec` skill. The spec
is the contract: it lists every ADaM dataset, its parameters, the exact variables/flags each
consuming table needs, the populations, and the `derivation_requirements`. **The ADaM this skill
builds MUST satisfy every demand in that spec** — a missing variable or a wrong flag is caught at
review or by the data-quality gate, not after it has silently corrupted a downstream number.

It produces:

1. **Derivation plan markdown** — how each spec-required dataset maps onto available SDTM (source
   domains, variable mapping, gaps).
2. **Individual R scripts** — one per ADaM dataset, following `{admiral}` conventions, implementing
   the three mandatory derivation rules.
3. **Executed ADaM datasets** — exported as Dataset-JSON (`.json` via `{datasetjson}`; `.xpt` on
   request).
4. **Data-quality gate report + conformance report** — analysis-set N asserted against population
   flags; derived datasets checked against the spec via metacore/metatools.
5. **Spec-coverage report** — confirms every dataset/parameter/variable the spec demands exists.
6. **Issue summary** — SDTM data-quality issues, gaps, assumptions.

## Input contract

**Primary (driving) input — the ADaM spec:**

```
outputs/{study}/tlf-plan/adam-spec.json
```

Its schema and the authoritative rules are documented in
`../tlf-analysis-spec/references/adam-spec-schema.md`. The spec contains:

- `datasets[]` — each with `name`, `class` (ADSL | BDS | OCCDS | TTE), `sdtm_source[]`,
  `used_by_tables[]`, `parameters[]` (`paramcd`/`param`), `variables[]` (name + role + optional
  `source`), and `derivation_requirements[]`.
- `populations[]` — each analysis-population flag, label, and definition (and expected N where
  known — used by the data-quality gate).

If `adam-spec.json` is absent, this skill can still fall back to reading mock TLG shells to
reconstruct requirements, but the spec-driven path is strongly preferred and is the default.

**Data input — SDTM:** a directory of SDTM datasets (`.xpt`, Dataset-`.json`, or `.sas7bdat`), plus
optional `define.xml`.

**Output location:** `outputs/{study}/adam/` (`code/`, `data/`, and the reports below), mirroring
the existing `outputs/cdiscpilot01-outputs/adam/` layout.

## When to use

- User has an `adam-spec.json` (or a reviewed ADaM spec) and SDTM data, and wants ADaM datasets.
- User asks to "derive ADaM", "generate analysis datasets", "run admiral code", "spec-driven ADaM".
- The `tlf-analysis-spec` review gate has been passed and the pipeline should proceed to derivation.

## Workflow

### Step 0: Check and install required R packages

Before any R code generation or execution, verify required packages are installed. Install only what
is missing and report which were installed.

```r
required_pkgs <- c(
  "admiral", "admiralonco", "admiralpeds", "admiralneuro",
  "admiralmetabolic", "admiralvaccine", "admiralophtha",
  "dplyr", "tidyr", "lubridate", "stringr", "rlang",
  "haven", "xportr", "datasetjson", "metacore", "metatools",
  "jsonlite", "pharmaversesdtm"
)
missing <- required_pkgs[!sapply(required_pkgs, requireNamespace, quietly = TRUE)]
if (length(missing) > 0) install.packages(missing, repos = "https://cloud.r-project.org")
```

### Step 1: Read and parse the ADaM spec (the driving input)

Read `outputs/{study}/tlf-plan/adam-spec.json` with `jsonlite::read_json()`. This — not the mock
shells — drives everything. For each `datasets[]` entry, extract:

- `name`, `class`, `sdtm_source[]`, `used_by_tables[]`.
- `parameters[]` — the exact `paramcd`/`param` to derive. **Honor the spec's codes literally.**
  (CDISCPILOT01 gotcha: ADAS-Cog(11) total is `ACTOT11`, NOT `ACTOT`; treatment factor is `TRTP`;
  numeric dose is `TRT01PN`; site is `SITEGR1`.)
- `variables[]` — the columns each consuming table needs. Every one MUST exist in the derived
  dataset (checked in Step 7). Note any `source: "ADSL"` variables that cascade from ADSL.
- `derivation_requirements[]` — which of the mandatory rules apply and their parameters (endpoint
  visit, target days, LOCF endpoint, etc.).

Also read `populations[]` for the flag definitions and expected Ns (feed the data-quality gate).

Build a master table: `{ADaM dataset} -> {class, SDTM sources, parameters, required variables,
population flags, applicable mandatory rules, expected N}`.

### Step 2: Inventory available SDTM data

Read the SDTM directory. Detect format per domain:

- **`.xpt`** → `haven::read_xpt()`
- **`.json`** (Dataset-JSON) → `datasetjson::read_dataset_json()`
- **`.sas7bdat`** → `haven::read_sas()`

For each domain note record count and key variables; check for supplemental qualifiers (`SUPP--`);
read `define.xml` if present for labels/CT/derivation metadata. Create
`{SDTM domain} -> {available variables, record count}`.

### Step 3: Reconcile spec demands against SDTM (plan)

Cross-reference the spec's demands (Step 1) with available SDTM (Step 2). Read
`references/adam-dataset-guide.md` for standard structures. For each spec dataset:

1. Confirm each `sdtm_source` domain is present.
2. Map each required `variables[]` entry to an SDTM source or a derivation.
3. Note which mandatory rules apply (from `derivation_requirements`) and their parameters.
4. Determine population flags (from ADSL).

Flag gaps: a spec variable that cannot be derived from available SDTM; a missing source domain; a
derivation needing an assumption (document it). Gaps are reported, not silently skipped.

### Step 4: Write the derivation plan markdown

Because the ADaM spec is now the *input*, this step documents the **derivation plan** (spec → SDTM
mapping), not the spec itself. For each dataset:

```markdown
## {ADAM_NAME} — {class} — supports tables {used_by_tables}
- **Spec parameters**: {paramcd list}
- **Source SDTM**: {domains}  (present? Y/N)
- **Variable mapping**:
  | Spec variable | Role | SDTM source / derivation |
  |---|---|---|
- **Mandatory rules that apply**: {windowing? LOCF endpoint=? SITEGR1?}
- **Population flags & expected N**: {flag = N}
- **Gaps / assumptions**: {…}
```

Save to `outputs/{study}/adam/derivation-plan.md`.

### Step 5: Generate {admiral} R scripts (implement the mandatory rules)

Read `references/admiral-coding-conventions.md` and — critically —
`references/mandatory-derivation-rules.md`, which carries the reference-code patterns for the three
rules and the data-quality gate.

Generate one R script per ADaM dataset, header commenting the spec datasets/tables it satisfies.
General script structure:

```r
# Name: {nn}_{adam_name}.R
# Description: Generate {ADAM_NAME} — satisfies adam-spec.json dataset {NAME}
# Supports tables: {used_by_tables}
# ---- Setup ----   library(admiral); library(dplyr); library(lubridate); library(stringr)
# ---- Read source data ----   (direct reader call, see rule below)
# ---- Derivations ----   (admiral calls; MANDATORY rules where the spec requires)
# ---- Data-quality gate ----   (assert N vs population flag)
# ---- Conformance ----   (metatools checks vs spec)
# ---- Export ----   (Dataset-JSON)
```

**Script generation rules:**

1. **ADSL first** — all other datasets merge population flags and subject-level variables (incl.
   `SITEGR1`) from it.
2. **Prefer admiral functions** over manual derivations: `derive_vars_dt/dtm()`, `derive_vars_dy()`,
   `derive_var_age_years()`, `derive_vars_merged_*()`, `derive_var_extreme_flag()`,
   `derive_var_base()`/`derive_var_chg()`, `derive_var_shift()`, `derive_param_*()`,
   `derive_extreme_records()`; oncology via `{admiralonco}`. Manual dplyr is acceptable where it more
   clearly implements a mandatory rule (as in the reference scripts).
3. **Direct data reader** — each script MUST contain a direct call to a recognized reader
   (`haven::read_xpt()`, `datasetjson::read_dataset_json()`, `haven::read_sas()`, or
   `jsonlite::fromJSON()`), not only a sourced helper, so validation tools can detect data reading.
4. **THE THREE MANDATORY RULES — implement exactly as specified** (full code in
   `references/mandatory-derivation-rules.md`; reference implementations in
   `outputs/cdiscpilot01-outputs/adam/code/06_adqsadas.R` and `01_adsl.R`, read-only):

   - **Rule 1 — Day-based analysis-visit windowing; do NOT drop off-schedule visits.** Assign
     `AVISIT`/`AVISITN` by study day (`ADY`/`xxDY`) with window boundaries at midpoints between
     adjacent target days; within a subject × window pick the record nearest the target day (latest
     `ADY` breaks ties). **Never** assign visits from a hard-coded `VISITNUM %in% c(...)` list — that
     drops unscheduled / early-termination visits and loses early terminators from the analysis.

   - **Rule 2 — LOCF at the endpoint visit.** For each subject in the analysis population with a
     baseline and ≥1 post-baseline value but no observed record at the endpoint visit, carry the
     last observed post-baseline value forward to the endpoint `AVISITN` as `DTYPE='LOCF'`,
     `ANL01FL='Y'`. Exactly one primary-analysis record per subject per endpoint.

   - **Rule 3 — `SITEGR1` pooling on RANDOMIZED counts.** In ADSL, pool a site into group `"900"`
     when any planned arm at that site has `< 3` randomized subjects (`ITTFL == 'Y'`) — NOT a flat
     count over all enrolled (screen failures excluded). `SITEGR1` cascades to every BDS dataset via
     the ADSL merge.

   Take the rules' parameters (endpoint visit, target days, parameter codes, arm levels) from the
   spec's `derivation_requirements`; do not hard-code study constants when the spec supplies them.
5. **Export** — `datasetjson::write_dataset_json()` by default; on request, `xportr_type/label/
   format/write()` with the metacore spec for `.xpt`.
6. **Labels & CT** — assign variable labels (`attr()` or admiral utilities) and use standard CDISC
   controlled terms; flag variables are `"Y"`/`"N"`.

Save scripts to `outputs/{study}/adam/code/{nn}_{adam_name}.R`.

### Step 6: Execute the R scripts

Run via `Rscript` in dependency order: **ADSL first**, then BDS/OCCDS datasets (depend only on ADSL
+ their SDTM), then derived/composite datasets (ADTTE, ADCM, anything depending on other ADaM).
For each: capture stdout/stderr; on failure, read the error, fix the R (name mismatches, missing
SDTM vars, types), re-run, document any data assumptions; verify the output file is non-empty.

### Step 7: Data-quality gate + conformance

**Data-quality gate (required — see `references/mandatory-derivation-rules.md`).** After derivation,
assert each analysis set's N against its population flag and **warn loudly / fail on any shortfall**:

- N(analysis records carrying the population flag) == N(that flag `='Y'` in ADSL). For CDISCPILOT01
  the Week-24 efficacy N must equal `EFFFL='Y'` (79/81/74 by arm) — take expected Ns from the spec's
  `populations[]`.
- Exactly one `ANL01FL='Y'` primary record per subject per endpoint (observed OR LOCF); no
  duplicates.
- No subject with baseline + post-baseline missing from the endpoint analysis (would mean the
  windowing/LOCF rules dropped them — the exact bug the gate guards against).
- Site-group count/per-group N reconcile with the randomized-only `SITEGR1` rule.

Emit a `data-quality.md` report and exit non-zero on a shortfall so the pipeline does not proceed on
corrupted denominators.

**Conformance (metacore / metatools).** Build a `metacore` object from the spec's `variables[]`
(name, type, label, codelist) and check each derived dataset:

```r
metatools::check_variables(ds, metacore_spec)   # required vars present
metatools::check_ct_data(ds, metacore_spec)     # CT values valid
```

Report any spec variable absent or mistyped as a conformance failure.

### Step 8: Spec-coverage report

Confirm the derived ADaM satisfies the spec (this replaces the old TLG cross-reference, driven now
by the spec's `datasets[]`/`used_by_tables[]`):

```markdown
## ADaM Spec Coverage
| Spec dataset | Parameters present | Required vars present | Tables supported | Status |
|---|---|---|---|---|
| ADSL     | —          | 42/42 | 14-1.01, … | OK |
| ADQSADAS | ACTOT11 ✓  | 13/13 | 14-3.01, … | OK |
```

Flag any dataset/parameter/variable in the spec that is missing from the derived data. Save to
`outputs/{study}/adam/spec-coverage.md`.

### Step 9: Issue summary

`outputs/{study}/adam/issues.md`:

```markdown
## Issue Summary
### SDTM Data Issues        — missing domains, unexpected variable names, quality issues
### Derivation Assumptions  — assumptions made during derivation
### Data-Quality Gate       — any N shortfalls (MUST be empty for a clean run)
### Conformance Failures    — metacore/metatools mismatches vs spec
### Unresolved Gaps         — spec demands that could not be satisfied
### Package Installation    — packages installed / failed
```

### Step 10: Present summary to user

Report: ADaM datasets created (names + record counts); output location; spec-coverage summary
(datasets/parameters/variables satisfied vs missing); **data-quality gate result (pass/fail with any
shortfall called out loudly)**; conformance result; critical issues; suggested next step (feed
`tlf-generator` with the analysis specs + these ADaM).

## Output directory structure

```
outputs/{study}/adam/
├── derivation-plan.md      # spec → SDTM mapping & gaps (Step 4)
├── code/
│   ├── 00_setup.R          # package loading + read_sdtm / read_adam / export_adam helpers
│   ├── 01_adsl.R           # ADSL (implements SITEGR1 randomized-count rule)
│   ├── 02_adae.R
│   ├── 06_adqsadas.R       # BDS (implements day-based windowing + LOCF endpoint)
│   └── ...
├── data/                   # Dataset-JSON (default) / .xpt on request
├── data-quality.md         # analysis-set N gate results (Step 7)
├── conformance.md          # metacore/metatools checks (Step 7)
├── spec-coverage.md        # ADaM spec coverage (Step 8)
└── issues.md               # issue summary (Step 9)
```

## Handling edge cases

**Missing SDTM domains**: if a spec dataset requires a missing source domain, flag it in the issue
summary and spec-coverage report (status = "blocked"); continue with all other datasets.

**Supplemental qualifiers (SUPP--)**: merge `SUPPAE`/`SUPPDM`/… into parents before deriving
(`admiral::combine_supp()` or manual merge by USUBJID + IDVAR + IDVARVAL). CDISCPILOT01 population
flags (ITTFL/SAFFL/EFFFL/COMPxxFL) come from `SUPPDM`.

**Non-standard SDTM variables**: map via `define.xml` if available; otherwise use heuristics
(`*DTC` for dates, `*CD` for codes) and document assumptions.

**Multiple questionnaire scales**: follow the spec — if the spec lists separate datasets
(ADQSADAS, ADQSCIBC, ADQSNPIX) create them separately; if one dataset with distinguishing `PARAMCD`,
do that.

**Oncology derivations**: use `{admiralonco}` (`derive_param_response()`, `derive_param_tte()`,
`derive_param_confirmed_resp()`); see `references/adam-dataset-guide.md`.

**Windowing / LOCF / SITEGR1**: always per the mandatory rules above — never a nominal-VISITNUM map,
never skip LOCF at the endpoint, never pool on all-enrolled counts.

## Supplementary context

If the spec alone is insufficient for a derivation detail, the skill may also read: the analysis
specs (`analysis-spec.json`, from `tlf-analysis-spec`), trial metadata JSON, protocol/SAP PDFs, and
the SDTM `define.xml`. These are looked up in the project's standard output/test-docs directories;
the user need not provide them explicitly.

## Reference files

- `references/mandatory-derivation-rules.md` — **read this before generating scripts.** The three
  mandatory rules (day-based windowing, LOCF endpoint, randomized-count SITEGR1) with reference-code
  patterns, the data-quality gate, and metacore/metatools conformance.
- `../tlf-analysis-spec/references/adam-spec-schema.md` — the `adam-spec.json` schema and the
  authoritative statement of the mandatory rules and data-quality gate (the input contract).
- `references/adam-dataset-guide.md` — standard ADaM structures and SDTM→ADaM variable mappings for
  ADSL, ADAE, ADLB, ADVS, ADEX, ADQS, ADTTE, ADCM, ADEG, ADRS, ADTR.
- `references/admiral-coding-conventions.md` — admiral best practices, function reference, code
  templates, and read/write patterns for the different data formats.
