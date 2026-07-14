---
name: tlf-generator
description: "Generate the actual Tables, Listings, and Figures (TLFs) from an ARS-aligned analysis spec + ADaM data, ARD-first: compute every statistic into Analysis Results Data (ARD) with {cards}/{cardx}/emmeans, then render the ARD to the CSR's shape with {gtsummary} (tables) and {ggsurvfit} (Kaplan-Meier figures), applying SAS rounding at display time. Use this skill when the user has an analysis-spec.json (from tlf-analysis-spec) plus ADaM datasets and wants to produce the numbers and the displays. Also trigger on: 'generate TLFs/tables/figures', 'produce ARD', 'analysis results data', 'cards/cardx tables', 'gtsummary tables from ADaM', 'ANCOVA LS-means table', 'Kaplan-Meier figure', 'ADaM to tables', 'compute the CSR numbers', or 'validate tables against the CSR'. This is Stage-3 of the Protocol->TLF pipeline and REPLACES/UPGRADES the older adam-to-tlg skill with an ARD-native numbers-then-format approach; prefer this skill over adam-to-tlg when an analysis spec exists."
---

# TLF Generator

## Purpose

Turn a **human-reviewed analysis spec** (from `tlf-analysis-spec`) plus **ADaM datasets** (from
`sdtm-to-adam`) into the two artifacts that matter: the **numbers** (ARD) and the **display**
(rendered TLF). Accuracy against the reference CSR is the top metric — every displayed value is
**computed from ADaM, never copied from a CSR**.

This is **Step 3** of the automated TLF workflow:

```
USDM ─▶ [tlf-planner]+[tlf-plan-critic] ─▶ tlf-plan ─▶ [tlf-analysis-spec] ─▶ analysis-spec.json + adam-spec
                                                                                    │
                                                        [sdtm-to-adam] ─▶ ADaM datasets
                                                                                    │
                                              analysis-spec.json + ADaM ─▶ [tlf-generator] ─▶ ARD ─▶ rendered TLF ─▶ VALIDATE
```

## Relationship to `adam-to-tlg` (what this replaces)

`adam-to-tlg` reads mock shells and computes-and-formats in one `gtsummary`/`gt` pass — the classic
mistake that makes a wrong cell impossible to trace. `tlf-generator` supersedes it with the
**three-artifact discipline** (§1 of `adam-to-tlf-design.md`): the recipe (analysis spec), the
**numbers** (ARD, persisted), and the **display** (rendered from the ARD). Prefer `tlf-generator`
whenever an `analysis-spec.json` exists. `adam-to-tlg` is **not deleted** — it remains the fallback
for the older mock-shell-driven path, but new work should go through this skill.

## The core rule: numbers → ARD → display, in that order

Keep the two phases strictly separate (from `references/generation-idioms.md` "Golden rules"):

1. **Compute** every statistic into a tidy **ARD** and persist it (`ard.csv` / `ard.json`).
2. **Render** the ARD to the CSR's row/column shape.
3. **Never compute inside the renderer; never copy a CSR value.**
4. Apply **SAS rounding at display time only** — R's `round()` is banker's (half-to-even); the CSR
   is half-away-from-zero. Round in the formatting layer, not in the stats.

## Inputs

- **Required:** `outputs/{study}/tlf-plan/analysis-spec.json` — the ARS-aligned analysis spec, one
  entry per TLF (or an array keyed by `table_id`). Schema:
  `../tlf-analysis-spec/references/analysis-spec-schema.md`.
- **Required:** the ADaM data directory — `outputs/{study}/adam/data/` (CSV/JSON; also `.xpt`/
  `.sas7bdat`). For **CDISCPILOT01** the concrete study folder is `cdiscpilot01-outputs`, so ADaM
  lives at `outputs/cdiscpilot01-outputs/adam/data/` (e.g. `adqsadas.csv`, `adsl.csv`, `adtte.csv`).
- **Ground truth (for validation only):** `csr-outputs-md/cdiscpilot01-tlf-<id>.md`. Used for
  *shape and scoring only* — never as a source of numbers.

## Outputs

Write to `outputs/{study}/tlf/`:

```
outputs/{study}/tlf/
├── code/
│   ├── 00_setup.R                 # sas_round/fmt, read_adam, arm levels, shared helpers
│   ├── <id>.R                     # one script per TLF (e.g. T-14-3.01.R, F-14-1.R)
│   └── run_all.R                  # runs every script, collects status
├── <id>/
│   ├── ard.csv                    # tidy ARD (long: one row per statistic)  ← the NUMBERS
│   ├── ard.json                   # same, jsonlite auto_unbox
│   ├── <id>.generated.md          # rendered display (CSR row/column shape)  ← the DISPLAY
│   ├── <id>.html                  # optional gt/gtsummary HTML render
│   ├── <id>.png                   # figures only (KM curve, 300 dpi)
│   └── diff-report.txt            # per-cell validation vs the CSR
├── tlf-index.md                   # id → outputs + match rate
└── issues.md                      # failures, data-provenance flags, sparse-strata fallbacks
```

Naming: `T-` tables, `L-` listings, `F-` figures, matching the analysis spec `table_id`.

## Workflow

### Step 0 — Environment

Ensure packages (versions validated on this machine, from `references/generation-idioms.md`):
`cards` 0.7.1.9008, `cardx` 0.3.2.9001, `gtsummary` 2.5.0.9003, `emmeans` 2.0.3, plus `dplyr`,
`tidyr`, `survival`, `ggsurvfit`, `mmrm`, `jsonlite`. Read each TLF's analysis-spec entry and its
target CSR file (for the exact row labels and column shape) before generating its script.

### Step 1 — Setup script (`00_setup.R`)

Emit the shared helpers exactly as in the idioms bible:

```r
# SAS-style rounding (round half away from zero) — DISPLAY ONLY
sas_round <- function(x, d = 0) { z <- abs(x) * 10^d; z <- floor(z + 0.5); sign(x) * z / 10^d }
fmt <- function(x, d) formatC(sas_round(x, d), format = "f", digits = d)
read_adam <- function(name) read.csv(file.path(ADAM_DIR, paste0(name, ".csv")), stringsAsFactors = FALSE)
```

**Population N always comes from ADSL** (one row per `USUBJID`), never from a BDS dataset (ADQS,
ADAE, …) which has many rows per subject and inflates N. Compute per-population N by arm once here.

---

### Phase A — ARD (the numbers)

For each TLF, one script that:

1. **Filter the analysis population.** Apply `analysisSet.condition` (e.g. `EFFFL == "Y"`) and
   `dataSubset.condition` (e.g. `PARAMCD == "ACTOT11" & AVISITN == 24 & ANL01FL == "Y"`). Set the
   treatment factor levels **and reference** from `groupingFactor.levels` (order + `isReference`).
2. **Assert N** against the population flag before computing — a data-quality gate:
   `stopifnot(!anyNA(ANL$TRTP), n_distinct(ANL$USUBJID) == nrow(ANL))`, then print `table(ANL$TRTP)`.
3. **Compute per method** using the right engine (catalog below). Descriptives via
   `cards::ard_continuous`; ANCOVA LS-means/contrasts via **`emmeans` directly** (not
   `cardx::ard_emmeans_contrast` — see warning); CMH via `cardx::ard_stats_mantelhaen_test`; KM via
   `cardx::ard_survival_survfit`; MMRM via **custom ARD**.
4. **Assemble a tidy ARD** — long format, one row per statistic:
   `group1, variable_level, context, stat_name, stat`. Flatten `ard_continuous` (its `group1_level`
   and `stat` are **list-columns holding factors** — coerce with `as.character()`/`as.numeric()`),
   bind the model rows, then `write.csv` + `jsonlite::write_json(..., auto_unbox = TRUE)`.

**Engine map** (from `adam-to-tlf-design.md` §5 and the schema catalog; ⚠️ = assemble, ❌ = custom):

| Method (spec) | Engine | Note |
|---|---|---|
| `Descriptive` | `cards::ard_continuous` / `ard_categorical` | ✅ wrap stats in `cards::continuous_summary_fns(...)` — bare string shortcut is broken in this cards build |
| `Incidence` (AE) | `cards::ard_hierarchical` / `cardx::ard_tabulate` | ✅ |
| `ShiftTable` (labs) | `cardx::ard_tabulate_shift` / `_abnormal` | ✅ |
| `Fisher` / `ChiSquare` | `cardx::ard_stats_fisher_test` / `ard_stats_chisq_test` | ✅ |
| `CMH` (CIBIC+) | `cardx::ard_stats_mantelhaen_test` | ✅ watch sparse strata — plan a `MASS::ginv` fallback |
| `ANCOVA` + LS-means | `lm(...)` + **`emmeans::emmeans` + `emmeans::contrast`** | ⚠️ assemble; explicit coef signs |
| `DoseResponse` | `lm(CHG ~ DOSE + …)`, read `summary(fit)$coefficients["DOSE","Pr(>|t|)"]` | ⚠️ dose as continuous |
| `KaplanMeier` | `cardx::ard_survival_survfit` (+ `_survfit_diff`) | ✅ figure → render with ggsurvfit |
| `LogRank` | `cardx::ard_survival_survdiff` | ✅ |
| `Cox` | `cardx::ard_regression` on `survival::coxph` | ⚠️ assemble |
| `MMRM` | `mmrm::mmrm()` + `emmeans` → **custom ARD** (`tidy_as_ard`/manual bind) | ❌ no cardx fn |

**ANCOVA / LS-means — use `emmeans` directly** (validated pattern; full code in the idioms bible):

```r
fit <- lm(CHG ~ TRTP + SITEGR1 + BASE, data = ANL)       # site group factor, baseline covariate
emm <- emmeans(fit, ~ TRTP)                              # equal ref-grid weighting = SAS LSMEANS default
ct  <- contrast(emm, method = list(                      # EXPLICIT coefs → sign = dose − reference
  "Xanomeline Low Dose - Placebo"   = c(-1, 1, 0),
  "Xanomeline High Dose - Placebo"  = c(-1, 0, 1),
  "Xanomeline High Dose - Low Dose" = c( 0,-1, 1)), infer = c(TRUE, TRUE))
```

> ⚠️ **`cardx::ard_emmeans_contrast` returned all-NULL stats in the tested build — do NOT use it.**
> Call `emmeans::emmeans` + `emmeans::contrast` and assemble the ARD yourself. Pass **explicit
> coefficient lists** (don't trust `pairwise`/`trt.vs.ctrl` default signs). Read the coef vectors
> and reference level from `groupingFactor.levels`.

> ❌ **MMRM needs custom ARD** — there is no cardx function and `mmrm` isn't a cardx dependency. Fit
> `mmrm::mmrm()`, pull LS-means/contrasts with `emmeans`, and hand-build the tidy ARD rows. Pin the
> covariance structure and DoF method (Kenward-Roger vs Satterthwaite) to the SAP or the numbers drift.

---

### Phase B — Display (the format)

Render the persisted ARD to the CSR's row/column shape. **Read the target CSR file first** for exact
row labels (including footnote markers like `p-value(Dose Response) [1][2]`, kept verbatim) and
column order.

- **Tables:** `gtsummary` (ARD-backed) for the standard shape, or emit markdown directly for
  exact-match control (as the spike does). Either way, pull values from the ARD and apply `fmt()`
  (SAS rounding) at each statistic's **display precision** from the method's `display` block
  (e.g. mean to 1 dp, SD to 2 dp, median to 1 dp, range as integers, p-values to 3 dp).
- **Column order and reference** come from `groupingFactor.levels`; **N in headers** from ADSL.
- **Figures (KM):** `ggsurvfit` — see below.
- `tfrmt` is the fallback if a specific mock shell must be pixel-matched; `rtables`/`rlistings` for
  awkward nested safety tables/listings. Numbers matter more than pixel fidelity on the first build.

---

### Validate

Score each generated table against the CSR with the harness:

```bash
python evals/tlf_numeric/diff.py outputs/{study}/tlf/<id>/<id>.generated.md \
       csr-outputs-md/cdiscpilot01-tlf-<id>.md --round-decimals 1
```

Or programmatically: `from diff import compare, format_summary` (see `evals/tlf_numeric/README.md`).
Use `--round-decimals` per the statistic's display precision so a SAS-vs-R last-digit half-rounding
difference lands in the **rounding** bucket, not **mismatch**. Write `diff-report.txt` per table and
the per-table match rate into `tlf-index.md`.

## Accuracy watch-list (from `adam-to-tlf-design.md` §6)

Ordered by how often they bite. When numbers are wrong, check these first:

1. **Populations/flags are upstream in ADaM.** LOCF/OC/windowed/completers are `ANLxxFL`;
   populations are `SAFFL/EFFFL/COMPLFL/ITTFL`. A wrong flag corrupts every N, %, and LS-mean even
   with a perfect model. If N per arm disagrees with the CSR, the fault is in ADaM, not the stats —
   flag it in `issues.md` (this exact denominator mismatch, `79/81/74` vs `76/75/65`, sank the first
   spike run). **Review the population/subset conditions hardest.**
2. **SAS rounding** — replicate half-away-from-zero via `sas_round()` in the formatter.
3. **LS-means/contrast setup** — exact model (`CHG ~ TRTP + SITEGR1 + BASE`, Type III), exact
   contrast, equal reference-grid weighting; factor vs continuous dose flips the p-value.
4. **MMRM** — covariance structure + DoF method pinned to the SAP.
5. **Factor level ordering** — set treatment order/reference explicitly or columns/contrasts invert.
6. **Sparse-stratum CMH** — R may refuse a p-value; fall back to `MASS::ginv`.
7. **Dataset provenance** — validate denominators explicitly; PHUSE Test-Data-Factory flags can
   differ from the original CDISC Pilot analysis data.

## Worked example — generating & validating T-14-3.01

`T-14-3.01` (ADAS-Cog(11) CFB→Wk24, LOCF, ANCOVA) is the proven end-to-end template; the reference
implementation is `testing-tlf-planner/spike-T-14-3.01/generate.R` and its idioms are distilled in
`references/generation-idioms.md`. The generated script:

1. **Population/subset:** filter `ADQSADAS` to `PARAMCD == "ACTOT11" & AVISITN == 24 & ANL01FL == "Y"
   & EFFFL == "Y"` (note: `ACTOT11` is the total, not `ACTOT` the subscore), factor `TRTP` with
   Placebo as reference, `SITEGR1` as factor; assert one row per subject.
2. **Phase A / ARD:** `cards::ard_continuous(by = TRTP, variables = c(BASE, AVAL, CHG), statistic =
   everything() ~ cards::continuous_summary_fns(c("N","mean","sd","median","min","max")))` for the
   descriptives; `lm` + `emmeans` + explicit-coef `contrast` for LS-means/diffs/CIs/p-values; a
   second `lm(CHG ~ DOSE + SITEGR1 + BASE)` with `DOSE = TRT01PN` for the continuous dose-response
   p. Bind all into one tidy ARD; write `ard.csv`/`ard.json`.
3. **Phase B / display:** render the CSR's rows (Baseline / Week 24 / Change from Baseline blocks
   with n, Mean (SD), Median (Range); then Dose-Response p, pairwise p, Diff of LS Means (SE), 95%
   CI), applying `fmt()` — mean 1 dp, SD 2 dp, median 1 dp, range integers, p-values 3 dp.
4. **Validate:** `diff.py … --round-decimals 1` against `csr-outputs-md/cdiscpilot01-tlf-T-14-3.01.md`.
   The spike reproduced this table at **100%** once the ADaM denominators were correct.

## How a KM figure (F-14-1) differs — `ggsurvfit`

`F-14-1` (Time to Dermatologic Event) is a **figure**, not a table, so the display path changes:

- **Phase A / ARD** is still survival stats, not descriptives: build the survival object
  (`survival::Surv(AVAL, 1 - CNSR)` on `ADTTE`, filtered to `SAFFL == "Y"`, the derm-event
  parameter) and compute with `cardx::ard_survival_survfit` (N, events, censored, median survival +
  95% CL per arm) and `cardx::ard_survival_survdiff` for the **log-rank p**. Persist to `ard.json`.
- **Phase B / display** uses **`ggsurvfit`**, not `gtsummary`: `survfit2(Surv(...) ~ TRTP)` →
  `ggsurvfit()` + `add_censor_mark()` + `add_risktable()` (number-at-risk), distinct line types per
  arm (Placebo solid, High dotted, Low dashed per the CSR), axis 0–200 days / 0–1 survival, log-rank
  p annotation. Export **`.png` at 300 dpi** (~10×7 in).
- **Validation:** the numeric harness is **tabular only** (figures out of scope), so score the
  figure's **Summary Statistics** block (subjects, event/censored %, median survival + 95% CL) as a
  small markdown table via `diff.py`, and eyeball the curve against the CSR figure description.

## Reference files

- `references/generation-idioms.md` — the validated cards/cardx/emmeans idioms (SAS rounding,
  `ard_continuous` API note, the `ard_emmeans_contrast` breakage, ARD assembly). **Read first.**
- `../tlf-analysis-spec/references/analysis-spec-schema.md` — the input contract (method catalog,
  `groupingFactor.levels`, ANCOVA sub-objects).
- the protocol-to-tfl adam-to-tlf design note — the Steps 2–3 design (§1 three artifacts, §5 method map,
  §6 accuracy watch-list). *(repo root)*
- the numeric-diff validation harness + `diff.py` — the validation harness contract. *(repo root)*
- `../../../../testing-tlf-planner/spike-T-14-3.01/generate.R` — the proven end-to-end template. *(repo root)*
