# TLF Candidate Schema

The **single shared object** that every planner, expander, and QC skill in the TLF Planner
system emits and consumes. A "candidate" is one proposed Table, Listing, or Figure. Keeping
one schema across all agents is what makes the merge mechanical and the audit two-way.

Each planner writes an **array of candidates** to its own file (see `pipeline-contract.md`).
Downstream skills read those arrays, add/modify fields, and pass them on.

```jsonc
{
  "candidate_id": "eff-END1-ancova-wk24-locf",  // stable, human-readable slug, unique within a run.
                                                 // Convention: {category-prefix}-{endpointOrRule}-{method}-{variant}
  "type": "Table",                    // Table | Listing | Figure
  "category": "efficacy",             // see enum below
  "title": "Primary Endpoint Analysis: ADAS-Cog (11) - Change from Baseline to Week 24 - LOCF",

  "traces_to": {                      // PROVENANCE — every candidate MUST populate this
    "objective_ids": ["Objective_1"], // USDM ids from study-model.json, or []
    "endpoint_ids": ["Endpoint_1"],   // USDM ids, or []
    "regulatory_rule": null           // e.g. "ICH E3 14.1" when scaffolding-driven; null otherwise
  },                                  // A candidate MUST have at least one of: an endpoint_id, an objective_id, or a regulatory_rule.

  "analysis": {
    "method": "ANCOVA",               // ANCOVA | ANOVA | MMRM | CMH | Fisher | KaplanMeier | LogRank |
                                      // Cox | ChiSquare | Wilcoxon | Descriptive | ShiftTable | Incidence | none
    "population": "Efficacy",         // matches an analysis_populations[].name from study-model.json
    "timepoint": "Week 24",           // or null
    "imputation": "LOCF",             // LOCF | OC | MI | none
    "subgroup": null,                 // e.g. "Sex=Male", "Sex=Female", or null
    "comparison": "dose-response"     // free text: what is being compared, or null
  },

  "data_requirements": {
    "adam": ["ADSL", "ADQSADAS"],     // ADaM datasets needed (best-effort)
    "sdtm_source": ["DM", "QS"]       // underlying SDTM domains
  },

  "status": "planned",                // planned | blocked | needs-clarification  (set by data-feasibility-checker)
  "status_reason": null,              // required when status != planned

  "priority": "primary",             // primary | secondary | supportive
  "produced_by": "efficacy-statistics-planner",  // which skill emitted this candidate (for debugging)

  "final_id": null,                   // ICH E3 §14 id, assigned ONLY by tlf-consolidator (e.g. "T-14-3.01", "F-14-1")
  "notes": []                         // free-text caveats, assumptions ("LOCF assumed — no SAP provided"), etc.
}
```

## `category` enum

| value | §14 section | meaning |
|---|---|---|
| `disposition` | 14-1 | subject accounting, populations, disposition, by-site |
| `demographics` | 14-2 | demographics & baseline characteristics |
| `efficacy` | 14-3 | efficacy analyses |
| `pk` | 14-4a | pharmacokinetics / pharmacodynamics |
| `exposure` | 14-4 | study drug exposure/dosing |
| `safety-ae` | 14-5 | adverse events |
| `safety-lab` | 14-6 | laboratory data |
| `safety-vs` | 14-7 | vital signs, weight |
| `conmeds` | 14-7 | concomitant medications |
| `pro` | 14-6/7 | patient-reported outcomes / HRQoL |
| `other` | 14-x | anything else (special domains) |

## Rules every emitter must follow

1. **Never leave `traces_to` empty.** If a candidate exists, it is justified by an endpoint, an objective, or a regulatory rule. This is what the traceability critic audits.
2. **Do not assign `final_id`.** Only `tlf-consolidator` numbers outputs. Planners leave it `null`.
3. **Set `produced_by`** to your skill name so conflicts can be traced.
4. **Over-produce, don't self-censor.** Planners should emit every plausible candidate in their lane; dedup happens at consolidation, feasibility filtering happens at the feasibility checker. It is better to emit a candidate the critic later prunes than to silently omit one.
5. **`candidate_id` must be unique and deterministic** within your output — derive it from the traced endpoint/rule + method + variant so re-runs are stable.
