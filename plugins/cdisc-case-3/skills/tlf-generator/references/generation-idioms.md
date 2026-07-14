# Generation Idioms — cards / cardx / emmeans (validated)

Reusable R patterns distilled from the `T-14-3.01` spike that reproduced the CSR at **100%**
(`testing-tlf-planner/spike-T-14-3.01/generate.R`). These are the battle-tested idioms the
**tlf-generator** skill should emit. Package versions on this machine: cards 0.7.1.9008,
cardx 0.3.2.9001, gtsummary 2.5.0.9003, emmeans 2.0.3, R 4.4.2.

## Golden rules
1. **Numbers → ARD → display, in that order.** Compute every statistic into a tidy ARD, persist it
   (`ard.csv`/`ard.json`), then render. Never compute inside the renderer; never copy CSR values.
2. **SAS rounding at display time.** R's `round()` is banker's (half-to-even); the CSR is
   half-away-from-zero. Apply `sas_round()` when formatting, not in the stats.
3. **Assert the population N** against the population flag before rendering (data-quality gate).

## SAS rounding (required)
```r
sas_round <- function(x, d = 0) { z <- abs(x) * 10^d; z <- floor(z + 0.5); sign(x) * z / 10^d }
fmt <- function(x, d) formatC(sas_round(x, d), format = "f", digits = d)
```

## Descriptive ARD — `cards::ard_continuous`
```r
cards::ard_continuous(
  data = ANL, by = TRTP, variables = c(BASE, AVAL, CHG),
  statistic = everything() ~ cards::continuous_summary_fns(c("N","mean","sd","median","min","max")))
```
- **API note (cards 0.7.1):** the string shortcut `~ c("mean","sd")` no longer works — you MUST
  wrap with `cards::continuous_summary_fns(...)`.
- `group1_level` and `stat` come back as **list-columns holding factors** — coerce with
  `as.character()` / `as.numeric()` before matching or writing out.

## ANCOVA + LS-means + contrasts — use `emmeans` DIRECTLY
```r
fit <- lm(CHG ~ TRTP + SITEGR1 + BASE, data = ANL)          # site group as factor, baseline covariate
emm <- emmeans(fit, ~ TRTP)                                  # equal ref-grid weighting = SAS LSMEANS default
ct  <- contrast(emm, method = list(                          # EXPLICIT coef lists → sign = dose - reference
  "Low - Placebo"  = c(-1, 1, 0),
  "High - Placebo" = c(-1, 0, 1),
  "High - Low"     = c( 0,-1, 1)), infer = c(TRUE, TRUE))    # infer=TRUE → CIs + p-values
```
- ⚠️ **`cardx::ard_emmeans_contrast` returned all-NULL stats in the tested dev build — do NOT use
  it.** Call `emmeans::emmeans` + `emmeans::contrast` and assemble the ARD yourself.
- **Contrast sign:** don't rely on `pairwise`/`trt.vs.ctrl` defaults; pass explicit coefficient
  lists so the display reads dose − comparator.
- **Dose-response test:** refit with the numeric dose as a continuous covariate and read its
  coefficient p-value: `summary(lm(CHG ~ DOSE + SITEGR1 + BASE))$coefficients["DOSE","Pr(>|t|)"]`.

## Assemble a tidy ARD
Long format, one row per statistic: `group1, variable_level, context, stat_name, stat`. Bind the
descriptive rows (flattened from `ard_continuous`) with the emmeans/contrast rows, then
`write.csv` + `jsonlite::write_json(..., auto_unbox = TRUE)`.

## Render & validate
- Render to the CSR's row/column shape (gtsummary, or direct markdown for exact-match control).
  Column order and reference level come from `groupingFactor.levels`.
- Score with the harness: `evals/tlf_numeric/diff.py` `compare(...)` (or its markdown CLI) vs
  `csr-outputs-md/<file>.md`, using SAS-rounding-aware compare at each stat's display precision.

## Method coverage reminders (from `adam-to-tlf-design.md` §5)
Turnkey: `cards::ard_continuous`/`ard_categorical`, `cardx::ard_stats_fisher_test`,
`ard_stats_mantelhaen_test` (CMH), `ard_survival_survfit`/`_survdiff` (KM/log-rank),
`ard_tabulate_*` (shift/abnormal). Assemble: ANCOVA (above), Cox (`ard_regression` on `coxph`).
**Custom ARD: MMRM** — `mmrm::mmrm()` + `emmeans` → `tidy_as_ard`/manual bind; pin covariance
structure + DoF method (KR vs Satterthwaite) to match the SAP.
