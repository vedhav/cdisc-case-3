# Numbering & Deduplication Rules

Operating rules for `tlf-consolidator` (agent #9). This is the **only** stage that assigns final
ICH E3 §14 numbers. Input is `candidates-feasible.json` (one already-merged array); see the shared
schema at `tlf-candidate-schema.md` and the pipeline contract at
`pipeline-contract.md`.

---

## 1. Deduplication heuristics

The merge is already done upstream — the input is a single array — but multiple planners
over-produce in overlapping lanes (e.g. the regulatory-scaffolding-planner and a safety planner may
both propose an exposure table). Collapse candidates that describe the **same physical output**.

### 1.1 Duplicate key

Two candidates are duplicates when **all three** match after normalization:

1. **Same §14 section** — after category→section resolution (§2).
2. **Same subject/measure** — normalize the `title`: lowercase, strip the study id, punctuation,
   population parentheticals, and imputation/subgroup qualifiers, then compare the core measure
   (e.g. "adas-cog change from baseline week 24", "summary of demographic and baseline
   characteristics").
3. **Same analysis fingerprint** — identical tuple of
   `analysis.method` + `analysis.population` + `analysis.timepoint` + `analysis.imputation` +
   `analysis.subgroup`.

Candidates that share a section and measure but differ on the analysis fingerprint are **variants,
not duplicates** (e.g. LOCF vs OC vs Male vs Female of the ADAS-Cog Week 24 table) — keep all of them.

### 1.2 Choosing the survivor

Prefer the **more specific / more complete** candidate:

1. Richer `data_requirements` (more precisely names the ADaM/SDTM sources).
2. More specific `analysis` (named method over `Descriptive`/`none`; explicit population/timepoint).
3. Fuller `traces_to` (an endpoint-driven candidate outranks a purely scaffolding one for the same
   output, because it carries objective/endpoint provenance).
4. Tie-break by `produced_by` precedence: a specialist planner (efficacy/safety/special-domain)
   outranks the generic regulatory-scaffolding-planner for overlapping safety-context tables;
   otherwise keep the first by `candidate_id` for determinism.

### 1.3 Recording the merge

Merge the loser into the survivor, don't just delete it:

- Union `traces_to.objective_ids`, `traces_to.endpoint_ids`; keep a non-null `regulatory_rule`.
- Union `data_requirements.adam` and `.sdtm_source`.
- Union `notes`, and append `"merged duplicate: {loser candidate_id} (from {loser produced_by})"`.

Merged losers are **dropped** from `tlf-plan.json` (they survive only as the survivor's note).

---

## 2. §14 section assignment

Resolve every surviving candidate to exactly one section using its `category`:

| `category` | Section | Type prefix |
|---|---|---|
| `disposition` | 14-1 | T (L for subject-level accounting listings) |
| `demographics` | 14-2 | T |
| `efficacy` | 14-3 | T (F for efficacy figures) |
| `pro` (cognitive/behavioral) | 14-3 | T |
| `exposure` | 14-4 | T |
| `pk` | 14-4 | T |
| `safety-ae` | 14-5 | T (F for AE figures, e.g. KM) |
| `safety-lab` | 14-6 | T |
| `safety-vs` | 14-7 | T |
| `conmeds` | 14-7 | T |
| `other` | 14-x | resolve by nearest neighbor; record in `notes` |

Conflict resolution:

- If `category` disagrees with the `title`/`analysis` (e.g. a candidate tagged `safety-vs` whose
  title is "Concomitant Medications"), trust the semantic content, reassign the section, and note it.
- `pro` splits by content: cognitive/behavioral scales that answer an **efficacy** objective (ADAS-Cog,
  CIBIC+, NPI-X) go to **14-3**; HRQoL/PRO instruments reported as safety context go to 14-6/7.
  In CDISCPILOT01 the cognitive/behavioral scales are efficacy endpoints → 14-3.
- A candidate can be assigned to **only one** section. No output appears twice.

---

## 3. Numbering & ordering

### 3.1 Format

```
Tables:   T-14-{section}.{seq}    seq zero-padded to 2 digits   e.g. T-14-3.01
Figures:  F-14-{seq}              single global figure sequence  e.g. F-14-1
Listings: L-14-{section}.{seq}    seq zero-padded to 2 digits    e.g. L-14-5.01
```

- `{section}` is the §14 subsection number (1–7).
- Tables and listings are numbered **per section**; the `seq` counter restarts at `.01` in each
  section and each type (a section can hold both T- and L- ids with independent counters).
- **Figures use one global sequence** across the whole plan (`F-14-1`, `F-14-2`, …), not per section.

### 3.2 Ordering within a section

Only `status == "planned"` candidates are numbered. Within each section, sort by:

1. `priority` — primary → secondary → supportive.
2. `timepoint` — earlier visit first (Baseline < Week 4 < Week 8 < Week 16 < Week 24); nulls last.
3. **variant order** — primary analysis first, then sensitivity (OC/completers/windowed), then
   subgroups (Male, Female, …), then descriptive companions, then model-based confirmations (MMRM),
   then categorical/responder analyses.

Assign `seq` in that sorted order.

### 3.3 SAP-fixed numbering overrides

When a SAP (or the study's authoritative CSR shell list) fixes explicit table numbers, **those win**
over the naive priority sort. The naive sort would place all primary-endpoint variants (sensitivity,
subgroup, MMRM) ahead of every secondary-endpoint table; real CSRs frequently interleave — grouping
the primary and secondary timepoints of the same measure together (Week 8/16 tables directly after
the Week 24 headline) before the primary-endpoint sensitivity/subgroup block. The CDISCPILOT01 worked
output in §5 reflects that CSR ground-truth ordering. Record any deviation from the naive sort in the
candidate's `notes` so the traceability critic can see the numbering is intentional.

---

## 4. Flagged / not-currently-producible convention

Candidates with `status == "blocked"` or `status == "needs-clarification"` are **kept in the plan**
but must never receive a number that implies they can be produced.

Convention used by this skill:

- Leave `final_id = null` for every non-planned candidate.
- Do **not** interleave them with the numbered outputs.
- List them in a dedicated **"Flagged / not currently producible"** section at the end of
  `tlf-index.md`, showing their `status` and `status_reason`.
- They remain full objects in `tlf-plan.json` (with `final_id: null`) so the traceability critic can
  audit them — an unresolved endpoint is a signal to act on, not a silent drop.

---

## 5. Worked CDISCPILOT01 numbered output

Reproduces the authoritative set in `objective-endpoint-tlf-mapping.md`: **30 tables + 1 figure**,
with END9/END10/END11 flagged. `{study-folder}` = `cdiscpilot01-outputs`.

### 5.1 tlf-index.md layout

```markdown
# TLF Plan — CDISCPILOT01

Total producible: 31 (30 tables, 1 figure, 0 listings). Flagged: 3.

## 14-1 — Subject Disposition / Populations
| ID | Type | Title | Population / Method | Traces-to | Status |
|----|------|-------|---------------------|-----------|--------|
...

## Flagged / not currently producible
| ID | Type | Title | Population / Method | Traces-to | Status |
|----|------|-------|---------------------|-----------|--------|
| — | Table | Activities of Daily Living (DAD) | — | OBJ4 / END9 | needs-clarification: endpoint text unresolved ("*** To be determined ***"); no DAD data |
...
```

### 5.2 Full numbered set

**14-1 — Subject Disposition / Populations** (scaffolding, ICH E3 §14.1)

| ID | Type | Title | Population / Method | Traces-to | Status |
|---|---|---|---|---|---|
| T-14-1.01 | Table | Summary of Populations | All / accounting | ICH E3 §14.1 | planned |
| T-14-1.02 | Table | Summary of End of Study Data | All / disposition | ICH E3 §14.1 | planned |
| T-14-1.03 | Table | Summary of Number of Subjects by Site | All / by-site counts | ICH E3 §14.1 | planned |

**14-2 — Demographics & Baseline Characteristics** (scaffolding, ICH E3 §14.1)

| ID | Type | Title | Population / Method | Traces-to | Status |
|---|---|---|---|---|---|
| T-14-2.01 | Table | Summary of Demographic and Baseline Characteristics | ITT / Descriptive | ICH E3 §14.1 | planned |

**14-3 — Efficacy Analyses** (OBJ1, OBJ3)

| ID | Type | Title | Population / Method | Traces-to | Status |
|---|---|---|---|---|---|
| T-14-3.01 | Table | Primary Endpoint Analysis: ADAS-Cog (11) — CFB to Week 24 (LOCF) | Efficacy / ANCOVA, LOCF | OBJ1 / END1 (primary) | planned |
| T-14-3.02 | Table | Primary Endpoint Analysis: CIBIC+ — Summary at Week 24 (LOCF) | Efficacy / Descriptive·ANOVA, LOCF | OBJ1 / END2 (primary) | planned |
| T-14-3.03 | Table | ADAS-Cog (11) — CFB to Week 8 (LOCF) | Efficacy / ANCOVA, LOCF | OBJ3 / END6 (secondary) | planned |
| T-14-3.04 | Table | CIBIC+ — Summary at Week 8 (LOCF) | Efficacy / Descriptive·ANOVA, LOCF | OBJ3 / END7 (secondary) | planned |
| T-14-3.05 | Table | ADAS-Cog (11) — CFB to Week 16 (LOCF) | Efficacy / ANCOVA, LOCF | OBJ3 / END6 (secondary) | planned |
| T-14-3.06 | Table | CIBIC+ — Summary at Week 16 (LOCF) | Efficacy / Descriptive·ANOVA, LOCF | OBJ3 / END7 (secondary) | planned |
| T-14-3.07 | Table | ADAS-Cog (11) — CFB to Week 24 — Completers/Observed Cases/Windowed | Efficacy / ANCOVA, OC (sensitivity) | OBJ1 / END1 (primary) | planned |
| T-14-3.08 | Table | ADAS-Cog (11) — CFB to Week 24 — Male subjects (LOCF) | Efficacy / ANCOVA, subgroup Sex=Male | OBJ1 / END1 (primary) | planned |
| T-14-3.09 | Table | ADAS-Cog (11) — CFB to Week 24 — Female subjects (LOCF) | Efficacy / ANCOVA, subgroup Sex=Female | OBJ1 / END1 (primary) | planned |
| T-14-3.10 | Table | ADAS-Cog (11) — Mean & Mean Change Over Time | Efficacy / Descriptive | OBJ1 / END1 (primary) | planned |
| T-14-3.11 | Table | Repeated Measures Analysis of CFB to Week 24 | Efficacy / MMRM (sensitivity) | OBJ1 / END1 (primary) | planned |
| T-14-3.12 | Table | Mean NPI-X Total Score, Week 4 → Week 24 (Windowed) | Efficacy / Descriptive | OBJ3 / END8 (secondary) | planned |
| T-14-3.13 | Table | CIBIC+ — Categorical Analysis (LOCF) | Efficacy / CMH row-mean-score | OBJ1 / END2 (primary) | planned |

**14-4 — Drug Exposure** (scaffolding; supports OBJ2)

| ID | Type | Title | Population / Method | Traces-to | Status |
|---|---|---|---|---|---|
| T-14-4.01 | Table | Summary of Planned Exposure to Study Drug | Safety / Descriptive | ICH E3 §14.1 (supports OBJ2) | planned |

**14-5 — Adverse Events** (OBJ2 / END3)

| ID | Type | Title | Population / Method | Traces-to | Status |
|---|---|---|---|---|---|
| T-14-5.01 | Table | Incidence of Treatment-Emergent AEs by Treatment Group | Safety / counts·% by SOC & PT | OBJ2 / END3 (primary) | planned |
| T-14-5.02 | Table | Incidence of Treatment-Emergent Serious AEs | Safety / counts·% by SOC & PT | OBJ2 / END3 (primary) | planned |

**14-6 — Laboratory Data** (OBJ2 / END5)

| ID | Type | Title | Population / Method | Traces-to | Status |
|---|---|---|---|---|---|
| T-14-6.01 | Table | Summary Statistics for Continuous Lab Values | Safety / Descriptive | OBJ2 / END5 (primary) | planned |
| T-14-6.02 | Table | Frequency of Normal/Abnormal (Beyond Normal Range) | Safety / shift counts | OBJ2 / END5 (primary) | planned |
| T-14-6.03 | Table | Frequency of Normal/Abnormal (Clinically Significant Change) | Safety / shift counts | OBJ2 / END5 (primary) | planned |
| T-14-6.04 | Table | Shifts vs. Threshold Ranges, by Visit | Safety / shift table | OBJ2 / END5 (primary) | planned |
| T-14-6.05 | Table | Shifts vs. Threshold Ranges (Overall) | Safety / shift table | OBJ2 / END5 (primary) | planned |
| T-14-6.06 | Table | Shifts of Hy's Law Values | Safety / shift table | OBJ2 / END5 (primary) | planned |

**14-7 — Vital Signs, Weight, Concomitant Medications** (OBJ2 / END4)

| ID | Type | Title | Population / Method | Traces-to | Status |
|---|---|---|---|---|---|
| T-14-7.01 | Table | Vital Signs at Baseline & End of Treatment | Safety / Descriptive | OBJ2 / END4 (primary) | planned |
| T-14-7.02 | Table | Vital Signs — Change from Baseline at EOT | Safety / Descriptive | OBJ2 / END4 (primary) | planned |
| T-14-7.03 | Table | Weight — Change from Baseline at EOT | Safety / Descriptive | OBJ2 / END4 (primary) | planned |
| T-14-7.04 | Table | Summary of Concomitant Medications | Safety / counts·% | ICH E3 §14.1 (supports OBJ2) | planned |

**Figures** (global F-14-{seq})

| ID | Type | Title | Population / Method | Traces-to | Status |
|---|---|---|---|---|---|
| F-14-1 | Figure | Time to Dermatologic Event by Treatment Group | Safety / Kaplan-Meier | OBJ2 / END3 (primary) | planned |

### 5.3 Flagged / not currently producible

| ID | Type | Title | Population / Method | Traces-to | Status |
|---|---|---|---|---|---|
| — | Table | Activities of Daily Living (DAD) | — | OBJ4 / END9 | needs-clarification: endpoint text "*** To be determined ***"; no DAD data/analysis |
| — | Table | Extended Cognition — ADAS-Cog (14) | — | OBJ5 / END10 | needs-clarification: endpoint unresolved; ADAS-Cog(14) not produced |
| — | Table | Treatment Response by Apo E Genotype | — | OBJ6 / END11 | needs-clarification: endpoint unresolved; no genotype analysis |

### 5.4 Count reconciliation

| Section | Tables | Figures |
|---|---|---|
| 14-1 | 3 | — |
| 14-2 | 1 | — |
| 14-3 | 13 | — |
| 14-4 | 1 | — |
| 14-5 | 2 | — |
| 14-6 | 6 | — |
| 14-7 | 4 | — |
| Figures | — | 1 |
| **Producible total** | **30** | **1** |
| Flagged (needs-clarification) | 3 (END9/10/11) | — |

Matches `objective-endpoint-tlf-mapping.md`: 25 objective/endpoint-driven + 6 scaffolding
(T-14-1.01/.02/.03, T-14-2.01, T-14-4.01, T-14-7.04) = 31 producible outputs; END9/10/11 flagged.
