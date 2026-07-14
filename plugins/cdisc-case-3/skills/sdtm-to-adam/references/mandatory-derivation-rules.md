# Mandatory Derivation Rules & Data-Quality Gate

These rules are **non-negotiable**. Each was a real bug in this repo's ADaM that produced a
silently-wrong CSR number until fixed. `sdtm-to-adam` MUST implement all three and MUST assert them
with the data-quality gate at the end. They are the authoritative reasons the derived ADaM either
reproduces the reference CSR or drifts.

Canonical source of the rules: `../../tlf-analysis-spec/references/adam-spec-schema.md`
(section "MANDATORY derivation rules"). Reference implementations (read-only, do not edit):
`outputs/cdiscpilot01-outputs/adam/code/06_adqsadas.R` and `.../01_adsl.R`.

Each BDS dataset's `derivation_requirements` array in `adam-spec.json` tells you *which* of these
apply and with *what* parameters (endpoint visit, target days, parameter codes). Read the spec —
do not hard-code CDISCPILOT01 constants when the spec provides them.

---

## Rule 1 — Analysis-visit windowing MUST be day-based and MUST NOT drop visits

**The bug:** assigning `AVISIT`/`AVISITN` from a hard-coded nominal `VISITNUM` map. That silently
deleted records collected at unscheduled / early-termination visits (e.g. "AMBUL ECG REMOVAL",
"RETRIEVAL"), so early terminators lost every post-baseline record and fell out of the LOCF
population — the N shrank and every downstream statistic drifted.

**The rule:** window each record onto the nearest scheduled analysis timepoint **by study day**
(`ADY` / `xxDY`), with window boundaries at the midpoints between adjacent target days. Within a
subject × analysis-visit window, keep the record nearest the target day (break ties by latest
`ADY`). **Never filter records out because their nominal visit is not in a fixed list.**

```r
# Targets come from the spec's derivation_requirements (do not hard-code):
# e.g. Baseline day 1, Week 8 day 56, Week 16 day 112, Week 24 (endpoint) day 168.
adas <- adas %>%
  mutate(
    ADY = as.numeric(QSDY),                     # study day relative to first dose
    AVISIT = case_when(
      is.na(ADY)  ~ NA_character_,
      ADY <= 1    ~ "Baseline",
      ADY <= 84   ~ "Week 8",                    # midpoint(56,112)=84
      ADY <= 140  ~ "Week 16",                   # midpoint(112,168)=140
      TRUE        ~ "Week 24"
    ),
    AVISITN = c("Baseline"=0,"Week 8"=8,"Week 16"=16,"Week 24"=24)[AVISIT],
    ATARGDY = c("Baseline"=1,"Week 8"=56,"Week 16"=112,"Week 24"=168)[AVISIT]
  ) %>%
  filter(!is.na(AVISIT), !is.na(AVAL))           # drop only missing-value/undatable records

# One observed analysis record per subject × visit: nearest target day, latest ADY breaks ties.
adas_obs <- adas %>%
  group_by(USUBJID, PARAMCD, AVISITN) %>%
  mutate(
    .rk = rank(abs(ADY - ATARGDY) - ADY * 1e-6, ties.method = "first"),
    ANL01FL = if_else(.rk == 1, "Y", NA_character_),
    DTYPE   = NA_character_
  ) %>%
  ungroup() %>% select(-.rk)
```

Do **not** use a nominal `VISITNUM %in% c(...)` filter for analysis-visit assignment. `admiral`'s
`derive_vars_joined()` / `slice_derivation()` windowing helpers are acceptable **only** if
configured on day windows and not dropping off-schedule visits.

---

## Rule 2 — Create LOCF records at the endpoint visit

**The rule:** for every subject in the analysis population that has a baseline **and** ≥1
post-baseline observed value **but no observed record at the endpoint visit**, carry the last
observed post-baseline value forward to the endpoint `AVISITN` as a record with `DTYPE='LOCF'` and
`ANL01FL='Y'`. There must be **exactly one** primary-analysis record per subject per endpoint.

```r
# endpoint AVISITN comes from the spec (here 24 = Week 24).
subj_with_endpoint <- adas_obs %>%
  filter(AVISITN == 24, ANL01FL == "Y") %>% pull(USUBJID)

adas_locf <- adas_obs %>%
  filter(ANL01FL == "Y", AVISITN > 0, !is.na(BASE),
         !(USUBJID %in% subj_with_endpoint)) %>%
  group_by(USUBJID, PARAMCD) %>%
  slice_max(AVISITN, n = 1, with_ties = FALSE) %>%     # last observed post-baseline
  ungroup() %>%
  mutate(AVISIT="Week 24", AVISITN=24, ATARGDY=168,
         DTYPE="LOCF", CHG=AVAL-BASE, ANL01FL="Y")

adqsadas <- bind_rows(adas_obs, adas_locf)
```

`admiral::derive_extreme_records()` may be used to build the LOCF record, but the resulting record
MUST carry `DTYPE='LOCF'`, `ANL01FL='Y'`, and be placed at the endpoint `AVISITN`.

---

## Rule 3 — `SITEGR1` pooling counts RANDOMIZED/TREATED subjects

**The bug:** pooling small sites using a flat count of **all enrolled** subjects
(`SITE_N >= 3`). Enrolled includes screen failures, which over-split the site groups and shifted the
ANCOVA covariate, moving the LS-means and p-values.

**The rule:** derive `SITEGR1` in ADSL. Pool a site into the pooled group `"900"` when **any**
planned treatment arm at that site has **fewer than 3 randomized subjects** (`ITTFL == 'Y'`). Count
only randomized/treated subjects (never screen failures). For CDISCPILOT01 this yields 11 site
groups and is required to reproduce the ADAS-Cog ANCOVA. `SITEGR1` then cascades (via ADSL merge) to
every BDS dataset and every table that uses site as covariate/stratifier.

```r
adsl <- adsl %>%
  group_by(SITEID) %>%
  mutate(
    # smallest randomized (ITT) arm size at this site across the planned arms
    SITE_MINARM = min(table(factor(TRT01PN[ITTFL == "Y"], levels = c(0, 54, 81))))
  ) %>%
  ungroup() %>%
  mutate(SITEGR1 = if_else(SITE_MINARM >= 3, SITEID, "900")) %>%
  select(-SITE_MINARM)
```

The planned-arm levels (`0, 54, 81`) and threshold come from the study design in the spec; keep the
"randomized only" semantics regardless of study.

---

## Data-Quality Gate (required, run after all derivation)

The windowing bug above passes silently — nothing errors, the N is just quietly wrong. So after
derivation, **assert each analysis set's N against its population flag and warn loudly on any
shortfall.** Fail the run (non-zero exit) on a shortfall so the pipeline does not proceed on
corrupted denominators.

Expected Ns come from `adam-spec.json` `populations[]` / the reviewed spec. For CDISCPILOT01 the
Week-24 efficacy analysis N must equal the `EFFFL='Y'` count (79 / 81 / 74 by arm).

```r
dq_assert <- function(actual, expected, label) {
  if (actual != expected) {
    msg <- sprintf("DATA-QUALITY GATE FAILED: %s = %d, expected %d (shortfall %d)",
                   label, actual, expected, expected - actual)
    warning(msg, call. = FALSE); cat("\n!!! ", msg, "\n", sep = "")
    return(FALSE)
  }
  cat(sprintf("DQ OK: %s = %d\n", label, actual)); TRUE
}

# population-flag counts in ADSL
ok <- dq_assert(sum(adsl$EFFFL == "Y"), 74, "ADSL EFFFL=Y")   # expected from spec

# every analysis record must have exactly one primary record per subject per endpoint
endpoint_n <- adqsadas %>% filter(AVISITN == 24, ANL01FL == "Y") %>%
  distinct(USUBJID) %>% nrow()
ok <- dq_assert(endpoint_n, sum(adsl$EFFFL == "Y"), "ADQSADAS Wk24 ANL01FL analysis N") && ok

dup <- adqsadas %>% filter(ANL01FL == "Y", AVISITN == 24) %>%
  count(USUBJID) %>% filter(n > 1)
if (nrow(dup) > 0) { warning("Multiple primary records per subject at endpoint", call.=FALSE); ok <- FALSE }

if (!ok) quit(status = 1)   # do not let the pipeline proceed on a shortfall
```

Gate checklist per analysis set:
- N(analysis records with the population flag) == N(that flag = 'Y' in ADSL).
- Exactly one `ANL01FL='Y'` primary record per subject per endpoint (observed OR LOCF).
- No subject that has baseline + post-baseline but is missing from the endpoint analysis (would
  indicate the windowing/LOCF rules dropped them).
- Site-group count and per-group N reconcile with the randomized-only `SITEGR1` rule.

---

## Conformance (metacore / metatools)

Where a define/metacore spec is available, build a `metacore` object from `adam-spec.json` (dataset
+ variable + type + label metadata) and check the derived datasets against it:

```r
# metacore spec built from adam-spec.json variables[] (name, type, label, codelist)
metatools::check_variables(adqsadas, metacore_spec)   # required vars present
metatools::check_ct_data(adqsadas, metacore_spec)     # controlled-terminology values valid
xportr::xportr_type(adqsadas, metacore_spec)          # types match spec
```

Report any variable in the spec's `variables[]` that is absent or mistyped in the derived dataset as
a conformance failure in the issue summary.
