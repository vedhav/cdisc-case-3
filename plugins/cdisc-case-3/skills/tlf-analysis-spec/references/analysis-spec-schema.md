# Analysis-Spec Schema (`analysis-spec.json`, per TLF)

The ARS-*aligned* (not full CDISC ARS JSON) analysis recipe for one TLF. Produced by
**tlf-analysis-spec**, consumed by **tlf-generator**. Generalized from the validated
`T-14-3.01` spike (`testing-tlf-planner/spike-T-14-3.01/analysis-spec.json`), which reproduced the
CSR at 100%. One file per TLF (or an array keyed by `table_id`).

```jsonc
{
  "id": "AN-14-3.01",
  "table_id": "14-3.01",              // matches the tlf-plan.json final_id (minus T-/F-/L- prefix)
  "title": "…",
  "protocol": "CDISCPILOT01",
  "reason": "SPECIFIED IN SAP | GAP-FILL | CONVENTION",
  "purpose": "…",                     // free text

  "analysisSet": {                     // the population (ARS AnalysisSet)
    "id": "AnalysisSet.Efficacy",
    "label": "Efficacy Population",
    "condition": "EFFFL = 'Y'",        // filter expression against the ADaM
    "source": "ADSL.EFFFL"
  },

  "groupingFactor": {                  // the column/treatment split (ARS GroupingFactor)
    "id": "Grouping.TRTP",
    "variable": "TRTP",
    "dataType": "character",
    "levels": [                        // explicit order + reference level (drives column order & contrasts)
      {"value": "Placebo", "order": 1, "isReference": true},
      {"value": "Xanomeline Low Dose", "order": 2, "dose": 54},
      {"value": "Xanomeline High Dose", "order": 3, "dose": 81}
    ],
    "doseVariable": "TRT01PN"          // numeric dose for trend tests, when applicable
  },

  "subgroup": null,                    // optional: {"variable":"SEX","level":"M"} for by-sex tables etc.

  "dataSubset": {                      // record-level filter (ARS DataSubset)
    "id": "DataSubset.…",
    "dataset": "ADQSADAS",
    "condition": "PARAMCD = 'ACTOT11' AND AVISITN = 24 AND ANL01FL = 'Y'"
  },

  "analysisVariables": {               // named roles → ADaM variables
    "baseline": {"variable": "BASE", "label": "…"},
    "response": {"variable": "CHG",  "label": "…"},
    "value":    {"variable": "AVAL", "label": "…"}
  },

  "methods": [ /* one or more — see method catalog below */ ],

  "rounding": {
    "rule": "SAS ROUND (half away from zero) at each statistic's display precision"
  },

  "output": {
    "ard": "ard.json",
    "display": "<table_id>.generated.md",
    "validation": "evals/tlf_numeric/diff.py vs csr-outputs-md/<file>.md"
  }
}
```

## Method object + catalog

Each entry in `methods[]` has: `id`, `label`, `appliesTo`/`responseVariable`, `operations[]`,
`display` (per-stat precision), and an `engine` naming the cards/cardx/emmeans call. Choose the
method type from this catalog (from `adam-to-tlf-design.md` §5; ⚠️ = assemble from parts,
❌ = custom ARD):

| Method type | Fields | Engine | Notes |
|---|---|---|---|
| `Descriptive` | `appliesTo`, `operations:[N,mean,sd,median,min,max,…]` | `cards::ard_continuous` / `ard_categorical` | ✅ |
| `Incidence` | counts/% by SOC/PT | `cards::ard_hierarchical` / `cardx::ard_tabulate` | ✅ AE tables |
| `ShiftTable` | from/to categories | `cardx::ard_tabulate_shift`/`_abnormal` | ✅ labs; CMH for p |
| `ANOVA` | `model`, `operations` | `cardx::ard_stats_anova`/`ard_stats_aov` | ✅ |
| `ANCOVA` | `model`, `fixedEffects`, `lsmeans`, `contrasts` | `lm` + **`emmeans` directly** (see idioms) | ⚠️ |
| `CMH` | strata, `operations:[p.value]` | `cardx::ard_stats_mantelhaen_test` | ✅ watch sparse strata |
| `Fisher`/`ChiSquare` | — | `cardx::ard_stats_fisher_test`/`ard_stats_chisq_test` | ✅ |
| `KaplanMeier` | time/event vars | `cardx::ard_survival_survfit`; render `ggsurvfit` | ✅ figure |
| `LogRank` | — | `cardx::ard_survival_survdiff` | ✅ |
| `Cox` | `model` | `cardx::ard_regression` on `survival::coxph` | ⚠️ |
| `MMRM` | `model`, covariance, DoF | `mmrm::mmrm` + `emmeans` → **custom ARD** | ❌ no cardx fn |
| `DoseResponse` | `doseVariable`, `operations:[p.value]` | `lm` with continuous dose term | ⚠️ |

### ANCOVA sub-objects (the validated pattern)
```jsonc
"model": "CHG ~ TRTP + SITEGR1 + BASE",
"lsmeans": { "engine": "emmeans::emmeans(fit, ~ TRTP)", "referenceGridWeighting": "equal",
             "operations": ["lsmean","lsmean_se"] },
"contrasts": { "engine": "emmeans::contrast (explicit coef lists)", "conf.level": 0.95, "adjust": "none",
  "comparisons": [ {"id":"low_vs_pbo","label":"…","coef":[-1,1,0]}, … ],
  "operations": ["diff","diff_se","conf.low","conf.high","p.value"] }
```

## Rules
- Every displayed statistic must be COMPUTED from ADaM — never copied from a CSR.
- `groupingFactor.levels` order + `isReference` drive column order AND contrast sign (dose − reference).
- Prefer `emmeans` directly for LS-means/contrasts; `cardx::ard_emmeans_contrast` was broken in the
  tested dev build (see `../../tlf-generator/references/generation-idioms.md`).
- Keep field names ARS-aligned so this can later feed CDISC ARS tooling without a rewrite.
