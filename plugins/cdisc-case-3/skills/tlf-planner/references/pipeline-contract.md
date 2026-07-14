# TLF Planner — Pipeline Contract

Defines the artifacts and conventions shared by the two TLF-planning skills — `tlf-planner`
(generation) and `tlf-plan-critic` (independent audit) — so their outputs are composable and
human-reviewable. This is **Step 1** of the larger vision:

```
Step 1  USDM JSON ──▶ tlf-planner ──▶ tlf-plan-critic ──▶ [HUMAN REVIEW] ──▶ reviewed TLF list
Step 2  reviewed TLF list ──▶ ARD datasets (CDISC Analysis Results Data)
Step 3  ARD datasets ──▶ TLFs, generated with the {cards} / {cardx} R packages
```

## Working directory

All artifacts live under a per-study plan directory:

```
outputs/{study-folder}/tlf-plan/
  study-model.json     # <- tlf-planner (phase 1): normalized USDM, human-checkable
  tlf-plan.json        # <- tlf-planner (phase 6): final numbered candidate array
  tlf-index.md         # <- tlf-planner (phase 6): human-readable numbered index (the deliverable)
  coverage-report.md   # <- tlf-plan-critic: two-way audit + verdict
```

`{study-folder}` mirrors the repo convention (e.g. `cdiscpilot01-outputs`); if unknown, derive
from `study_id` lowercased (e.g. `cdiscpilot01`).

`tlf-planner` runs its six phases in a single context (no per-phase files) so cross-endpoint
reasoning stays intact; it emits `study-model.json` as a reviewable intermediate and the
`tlf-plan.json` / `tlf-index.md` deliverables. `tlf-plan-critic` reads only `tlf-plan.json` +
`study-model.json` — deliberately NOT the planner's reasoning — so its audit is independent.

## The two contracts every candidate obeys

- **`study-model-schema.md`** — the normalized study (objectives, endpoints, estimands,
  populations, arms). Produced in phase 1; the critic audits coverage against it.
- **`tlf-candidate-schema.md`** — the object each TLF candidate conforms to. Its mandatory
  `traces_to` provenance field is what makes the critic's two-way audit possible.

## ICH E3 §14 numbering (assigned in tlf-planner phase 6)

```
Tables:   Table 14-{section}.{seq}      e.g. T-14-3.01
Figures:  Figure 14-{seq}               e.g. F-14-1
Listings: Listing 14-{section}.{seq}    e.g. L-14-5.01
```

| Section | Content | category values |
|---|---|---|
| 14-1 | Subject disposition / populations / by-site | `disposition` |
| 14-2 | Demographics & baseline characteristics | `demographics` |
| 14-3 | Efficacy analyses | `efficacy`, `pro` (cognitive/behavioral) |
| 14-4 | Exposure / PK-PD | `exposure`, `pk` |
| 14-5 | Adverse events | `safety-ae` |
| 14-6 | Laboratory data | `safety-lab` |
| 14-7 | Vital signs, weight, concomitant meds | `safety-vs`, `conmeds` |

Within a section, order by `priority` (primary → secondary → supportive), then by timepoint.

## Cross-referencing

The generation knowledge packs and both shared schemas live together in
`tlf-planner/references/`, so they reference each other by bare filename. `tlf-plan-critic`
reaches the two schemas at `../../tlf-planner/references/`.

## Ground truth for validation (CDISCPILOT01)

The real CSR outputs in `csr-outputs-md/` are the gold standard: **30 tables + 1 figure**.
`objective-endpoint-tlf-mapping.md` (repo root) is the authoritative expected mapping. A correct
run reproduces that set (25 objective/endpoint-driven + 6 scaffolding) and flags
END9/END10/END11 as `needs-clarification`.
