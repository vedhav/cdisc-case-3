# Audit Checklist — Traceability & Completeness Critic

The complete rule sets the [`tlf-traceability-critic`](../SKILL.md) applies when auditing a
consolidated `tlf-plan.json` against `study-model.json`. Every TLF object referenced here follows
the [tlf-candidate-schema](../../tlf-planner/references/tlf-candidate-schema.md); every objective /
endpoint follows the [study-model-schema](../../tlf-planner/references/study-model-schema.md).

Three audits run in order: **FORWARD** (coverage), **BACKWARD** (provenance), **COMPLETENESS**
(conventions). Then a **VERDICT** and, on gaps, a bounded **re-run plan**.

---

## 1. FORWARD audit — coverage (is anything missing?)

**Rule F1 — endpoint coverage.** For every endpoint in `study-model.json.endpoints`:

- If `resolved: true` → it MUST be referenced by `traces_to.endpoint_ids` on ≥1 TLF whose
  `status` is `planned`. If not → **GAP**.
- If `resolved: false` (equivalently, listed in `unresolved_endpoints`) → it MUST NOT be expected to
  have a TLF. Record it as a **clarification ACTION ITEM**. It is **never a gap** and **never a
  silent drop**.

**Rule F2 — objective coverage.** For every objective in `study-model.json.objectives`:

- An objective is **covered** if at least one of its `endpoint_ids` is a resolved endpoint that is
  covered (F1), or if a TLF traces to the objective directly via `traces_to.objective_ids`.
- An objective whose endpoints are **all unresolved** is a **clarification item**, not a gap
  (e.g. OBJ4/5/6 in CDISCPILOT01, each with a single TBD endpoint).
- An objective with ≥1 resolved endpoint where **none** is covered → **GAP**.

**Rule F3 — status counts.** A TLF with `status: blocked` or `status: needs-clarification` does
NOT satisfy coverage on its own — note it, but a resolved endpoint covered only by a `blocked` TLF
is a **soft gap** (data feasibility, not planning): report it, route to `tlf-planner` phase 5 (feasibility)
context rather than a planner, and do not fabricate a re-run of a planner for it.

### Coverage classification (per endpoint)

| Condition | Status | Treatment |
|---|---|---|
| `resolved: true`, ≥1 `planned` TLF traces to it | `covered` | none |
| `resolved: true`, 0 TLFs trace to it | `gap` | route to owning specialist (§4) |
| `resolved: true`, only `blocked` TLFs | `gap (blocked)` | note as feasibility issue, do not planner-loop |
| `resolved: false` | `clarification` | ACTION ITEM — protocol/SAP clarification |

---

## 2. BACKWARD audit — provenance (is anything orphaned?)

**Rule B1 — every TLF must be justified.** A TLF is **valid** iff `traces_to` has at least one of:

- non-empty `objective_ids`, OR
- non-empty `endpoint_ids`, OR
- non-null `regulatory_rule`.

A TLF with empty `objective_ids` **and** empty `endpoint_ids` **and** null `regulatory_rule` is an
**ORPHAN error**.

**Rule B2 — scaffolding is valid.** A TLF with empty objective/endpoint ids but a non-null
`regulatory_rule` (e.g. `"ICH E3 14.1"`, `"ICH E3 14.2"`) is **VALID scaffolding — NOT an orphan**.
An empty `traces_to.objective_ids` alone is never sufficient to call something an orphan; check
`regulatory_rule` before flagging.

**Rule B3 — referential integrity.** Every id appearing in a TLF's `objective_ids` /
`endpoint_ids` MUST exist in `study-model.json`. A reference to a non-existent id (or to an
`unresolved` endpoint — a TBD endpoint should not have a table tracing to it) is a **traceability
error**, reported separately from orphans.

### Orphan classification (per TLF)

| `objective_ids` | `endpoint_ids` | `regulatory_rule` | Verdict |
|---|---|---|---|
| non-empty | any | any | valid (objective-driven) |
| any | non-empty | any | valid (endpoint-driven) |
| empty | empty | non-null | valid (scaffolding — Rule B2) |
| empty | empty | null | **ORPHAN error** |
| cites id not in study-model | — | — | **integrity error** (B3) |

---

## 3. COMPLETENESS audit — conventions (is anything expected-but-absent?)

Heuristics comparing the plan against standard-report expectations for the study's features (use
`study-model.json` + `study-profile.json` when available). Each finding is a **recommendation**
(non-blocking) unless it also manifests as a forward gap. Tag each with the owning specialist.

| # | Heuristic (fires when …) | Recommendation | Owning tlf-planner phase |
|---|---|---|---|
| C1 | A safety objective exists but no **deaths / mortality** table is planned | add deaths summary | `tlf-planner` phase 3c (safety) |
| C2 | A safety objective exists but no **AEs-leading-to-discontinuation** table | add discontinuation-AE table | `tlf-planner` phase 3c (safety) |
| C3 | A **primary `continuous`** endpoint has an ANCOVA but no **sensitivity** (OC/completers) companion | add sensitivity analysis | `tlf-planner` phase 4 (variants) |
| C4 | A **primary `continuous`** endpoint has no **MMRM** repeated-measures companion | add MMRM | `tlf-planner` phase 3b (efficacy) |
| C5 | A **primary** endpoint has no **subgroup** (sex/age) split | add subgroup variants | `tlf-planner` phase 4 (variants) |
| C6 | Study is **multi-site** but no **by-site** enrollment/disposition table | add by-site table | `tlf-planner` phase 3a (scaffolding) |
| C7 | A **lab** endpoint exists but no **shift / Hy's-Law** table | add shift/Hy's-Law tables | `tlf-planner` phase 3c (safety) |
| C8 | Any CSR but no **disposition** or **demographics** scaffolding table | add §14-1 / §14-2 scaffolding | `tlf-planner` phase 3a (scaffolding) |
| C9 | A **time-to-event safety signal** flagged in profile but no KM figure | add KM figure | `tlf-planner` phase 3c (safety) |
| C10 | An **exposure** table absent though a safety objective is present | add exposure table | `tlf-planner` phase 3a (scaffolding) |

A recommendation escalates to a **gap** only when the missing output is the *sole* coverage of a
resolved endpoint (then Rule F1 already flags it).

---

## 4. Specialist-routing table (which gap → which skill)

When the FORWARD audit finds an uncovered resolved endpoint, route by the endpoint's
`parsed.domain_hint` / `measure_type`:

| Gap type | Signal | Re-run (tlf-planner phase) |
|---|---|---|
| Uncovered **efficacy** endpoint | `domain_hint` = `efficacy-*` (ADAS-Cog, CIBIC+, NPI-X, DAD) | `tlf-planner` phase 3b (efficacy) |
| Uncovered **safety** endpoint | `domain_hint` = `safety-ae` / `safety-lab` / `safety-vs` (AEs, labs, vitals) | `tlf-planner` phase 3c (safety) |
| Missing **scaffolding** table (disposition/demographics/exposure/conmeds) | orphan-of-convention / C6/C8/C10 | `tlf-planner` phase 3a (scaffolding) |
| Missing **variant** (imputation/subgroup/population/timepoint) | C3/C5 | `tlf-planner` phase 4 (variants) |
| Missing **special-domain** output (PK/onc/immunogenicity/PRO) | `domain_hint` = `pk` / `other` + profile flag | `tlf-planner` phase 3d (special domains) |
| Coverage only by a **blocked** TLF | `status: blocked` | not a planner loop — feasibility/data issue; escalate |

**Bounded loop.** The re-run plan may name multiple specialists but is capped at **~2 rounds**. On
each round, re-run only the named specialists, then re-consolidate and re-audit. If gaps remain
after round 2, STOP and escalate to a human — do not loop indefinitely.

---

## 5. Unresolved vs. gap vs. orphan — the decision core

The three failure-adjacent conditions this agent must never confuse:

```
Endpoint with no TLF?
  ├─ resolved == false  →  ACTION ITEM (clarification). Not a gap. Not an error.
  └─ resolved == true   →  GAP. Route to the owning specialist (§4).

TLF with empty objective_ids + empty endpoint_ids?
  ├─ regulatory_rule != null  →  VALID scaffolding. Not an orphan.
  └─ regulatory_rule == null   →  ORPHAN error.
```

- **Clarification (unresolved endpoint):** expected, benign, must be surfaced as an explicit action
  item so a human resolves the protocol/SAP. Silent omission is itself a defect.
- **Gap (uncovered resolved endpoint):** a real planning miss → loop back to a specialist.
- **Orphan (unjustified TLF):** a real provenance miss → the plan invented an output; flag it (the
  critic does not delete it, but the consolidator/planner owning it should).

---

## 6. Worked CDISCPILOT01 expected report

For the reference study (6 objectives, 11 endpoints, 31 TLFs = 30 tables + 1 figure), a correct
plan produces this report. Expected verdict: **`clean-with-caveats`** — full forward coverage of
all resolved endpoints, zero orphans, with END9/10/11 as open clarification action items.

### Counts

| Metric | Value |
|---|---|
| Objectives | 6 (2 primary, 4 secondary) |
| Endpoints | 11 (8 resolved, 3 unresolved) |
| Total TLFs | 31 (30 tables + 1 figure) |
| Objective/endpoint-driven TLFs | 25 |
| Scaffolding TLFs (regulatory_rule) | 6 |
| Orphans | 0 |
| Coverage gaps | 0 |
| Clarification action items | 3 (END9, END10, END11) |

### Coverage matrix (expected)

| Objective | Level | Endpoint | Resolved | TLFs | Status |
|---|---|---|---|---|---|
| OBJ1 | Primary | END1 ADAS-Cog(11) Wk24 | yes | T-14-3.01, .07, .08, .09, .10, .11 | covered |
| OBJ1 | Primary | END2 CIBIC+ Wk24 | yes | T-14-3.02, .13 | covered |
| OBJ2 | Primary | END3 Adverse events | yes | T-14-5.01, .02, F-14-1 | covered |
| OBJ2 | Primary | END4 Vital signs | yes | T-14-7.01, .02, .03 | covered |
| OBJ2 | Primary | END5 Lab evaluations | yes | T-14-6.01–.06 | covered |
| OBJ3 | Secondary | END6 ADAS-Cog(11) Wk8&16 | yes | T-14-3.03, .05 | covered |
| OBJ3 | Secondary | END7 CIBIC+ Wk8&16 | yes | T-14-3.04, .06 | covered |
| OBJ3 | Secondary | END8 NPI-X Wk4-24 | yes | T-14-3.12 | covered |
| OBJ4 | Secondary | END9 (DAD) | **no** | — | **clarification** |
| OBJ5 | Secondary | END10 ADAS-Cog(14) | **no** | — | **clarification** |
| OBJ6 | Secondary | END11 Apo E genotype | **no** | — | **clarification** |

### Scaffolding (valid via regulatory_rule — NOT orphans)

| TLF | Title | regulatory_rule |
|---|---|---|
| T-14-1.01 | Summary of Populations | ICH E3 14.1 |
| T-14-1.02 | Summary of End of Study Data | ICH E3 14.1 |
| T-14-1.03 | Number of Subjects by Site | ICH E3 14.1 |
| T-14-2.01 | Demographic & Baseline Characteristics | ICH E3 14.2 |
| T-14-4.01 | Planned Exposure to Study Drug | ICH E3 14.4 |
| T-14-7.04 | Concomitant Medications | ICH E3 14.7 |

### Orphan list

Empty — all 25 objective/endpoint-driven TLFs trace to a resolved endpoint, and all 6 scaffolding
TLFs trace to a `regulatory_rule`.

### Completeness recommendations (expected)

Minimal for this plan. Notable satisfied checks: C4 (END1 has MMRM T-14-3.11), C3 (END1 has OC
sensitivity T-14-3.07), C5 (END1 has Male/Female T-14-3.08/.09), C6 (by-site T-14-1.03 present),
C7 (lab shift + Hy's-Law T-14-6.02–.06), C9 (KM figure F-14-1 present), C10 (exposure T-14-4.01
present). If the plan omits any of these, raise the corresponding recommendation and tag the
specialist from §3. No deaths table (C1) may be raised as a recommendation if none is present —
non-blocking, since END3's AE families cover the safety objective.

### Action items (expected)

1. **END9 (OBJ4, DAD / activities of daily living):** endpoint text `"*** To be determined ***"`;
   no DAD dataset/analysis. Clarify with protocol/SAP before planning a TLF.
2. **END10 (OBJ5, ADAS-Cog (14) extended cognition):** unresolved; ADAS-Cog(14) not produced.
   Clarify.
3. **END11 (OBJ6, treatment response by Apo E genotype):** unresolved; no genotype analysis.
   Clarify.

### Verdict

**`clean-with-caveats`** — forward coverage complete for all 8 resolved endpoints, zero orphans,
zero coverage gaps; 3 open clarification action items (END9/10/11). No re-run plan required (no
gaps). Sign-off to proceed downstream, with the 3 action items tracked for human resolution.
