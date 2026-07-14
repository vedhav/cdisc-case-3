# Variant Expansion Rules

The rulebook for **agent 7, `analysis-variant-expander`**. It defines which candidates get
fanned out, along which dimensions, how far, and how the resulting candidate objects are
filled in. Every emitted variant is a full TLF candidate object per
[`tlf-candidate-schema.md`](tlf-candidate-schema.md).

The governing idea (from `objective-endpoint-tlf-mapping.md` §4): **the USDM gives you one
endpoint; the SAP multiplies it into many tables.** This agent is that multiplier. It reads
the merged planner candidates and, for each one, decides whether it is a *seed* that fans out
or a *leaf* that passes through unchanged.

---

## 1. Two modes

### Mode A — SAP present (extract)
A SAP (or SAP-derived variant list) is available at the path the caller supplies. **Extract the
actually pre-specified variants** — the imputation rules, the named subgroups, the sensitivity
analyses, the per-timepoint splits the SAP lists. Do not invent variants the SAP does not name,
and do not drop ones it does. Each extracted variant is grounded, so it carries **no "assumed"
note**; instead add a note citing the SAP (`"variant per SAP §<section>"`).

### Mode B — SAP absent (infer by convention)
No SAP is available (the common case for CDISCPILOT01). Apply the **convention-driven defaults**
in §3, gated by the study profile. Every convention-driven variant MUST carry the note:

```
"variant assumed — no SAP provided"
```

so the traceability critic can see which tables rest on convention rather than a pre-specified
plan. This is a required marker, not optional.

Pick the mode once, up front, from whether a SAP path was supplied and readable. Record the
chosen mode in the run summary.

---

## 2. Seed vs. leaf: what fans out

| Candidate class | Fans out? | Along which dimensions |
|---|---|---|
| **Primary continuous efficacy** (method ANCOVA/MMRM/ANOVA, `priority: primary`, `measure_type` continuous) | **Yes — fully** | imputation, subgroup (sex/region gated), population, timepoint |
| **Secondary continuous efficacy** | Partial | timepoint split only (per-timepoint); imputation/subgroup NOT applied (secondary endpoints get single analyses) |
| **Categorical / global-impression efficacy** (CMH, responder) | Partial | imputation (LOCF vs OC) only if primary; no sex subgroup by default |
| **Descriptive companions** (method `Descriptive`, mean-over-time) | **No — leaf** | pass through unchanged |
| **MMRM sensitivity model** | **No — leaf** | already a distinct sensitivity analysis; pass through unchanged (do NOT also add LOCF/OC to it) |
| **Regulatory scaffolding** (`traces_to.regulatory_rule` set, category `disposition`/`demographics`/`exposure`/`conmeds`) | **No — leaf** | never gets imputation/subgroup variants |
| **Safety table families** (`safety-ae`/`safety-lab`/`safety-vs`) | **No — leaf** (already expanded into families by agent 5) | pass through; the safety planner already produced the family |

**Guardrail — do not over-expand.** Scaffolding and descriptive tables have no imputation or
subgroup dimension. Fanning them out produces phantom tables the critic will reject. When in
doubt, treat a candidate as a leaf.

Every leaf is still **carried through** into `candidates-expanded.json` unchanged (same
`candidate_id`, same fields) — the output is the *complete* merged + expanded stream, not just
the new variants.

---

## 3. The expansion dimensions (convention defaults)

Applied in Mode B; in Mode A the SAP overrides these.

### 3.1 Imputation — `analysis.imputation`
For **primary continuous efficacy** endpoints, emit both:
- **LOCF** — the **primary** analysis (`imputation: "LOCF"`, keep `priority: primary`).
- **OC** — observed-cases / completers / windowed **sensitivity** analysis
  (`imputation: "OC"`, set `priority: supportive`, `population: "Completers"`).
  Title convention: `… - Completers, Observed Cases, Windowed`.

Do NOT emit an MI variant unless the SAP names one. Categorical primary endpoints may get an
LOCF/OC pair only when the endpoint is analyzed on an imputed dataset.

### 3.2 Subgroup — `analysis.subgroup`  (GATED on profile flags)
Applied **only to primary** endpoints, and **only on the primary (LOCF) analysis**, not on every
sensitivity variant.

| Subgroup | Gate (from `study-profile.json`) | Variants emitted |
|---|---|---|
| Sex | `flags.needs_subgroup_by_sex === true` | `subgroup: "Sex=Male"`, `subgroup: "Sex=Female"` |
| Region | `flags.needs_subgroup_by_region === true` | one variant per region (or `Region=<name>` if named) |
| Age | *(no profile flag)* — Mode A only, when the SAP names age bands | `subgroup: "Age=<band>"` |

If the gating flag is `false`, emit **no** subgroup variants for that dimension. Age has no
profile flag, so it is never inferred by convention — only extracted from a SAP (Mode A).
Subgroup variants inherit the imputation of the analysis they slice (LOCF for CDISCPILOT01) and
are `priority: supportive`.

### 3.3 Analysis population — `analysis.population`
Usually set by the source planner. The expander only changes it as a *consequence* of another
dimension:
- OC/completers sensitivity → `population: "Completers"`.
- A candidate may be duplicated across `Efficacy` vs `Completers` **only if the SAP specifies
  both** (Mode A). Do not manufacture population variants by convention.
Safety tables stay on their planner-assigned population (`Safety` / All-Treated); the expander
does not touch them.

### 3.4 Timepoint — `analysis.timepoint`
If a single candidate lists **multiple** timepoints (e.g. `"Week 8 & 16"` or a `timepoints`
array), split it into **one candidate per timepoint** (`timepoint: "Week 8"`,
`timepoint: "Week 16"`). This applies to both primary and secondary endpoints. A candidate that
already names one timepoint is not split.

---

## 4. Building each variant candidate

For every variant produced from a seed:

1. **Copy** the seed candidate object in full.
2. **Set the dimension field(s)** in `analysis` (`imputation`, `subgroup`, `population`,
   `timepoint`) for this variant.
3. **New `candidate_id`** — deterministic: take the seed id and append the variant token(s) in a
   fixed order `…-<imputation>-<subgroup>-<timepoint>`, lowercased, omitting tokens equal to the
   seed's. Examples below. Never reuse a seed id for a variant.
4. **Update `title`** to name the variant (`- LOCF`, `- Completers, Observed Cases, Windowed`,
   `- Male subjects`, `- Female subjects`, `- Week 8`).
5. **Keep `traces_to` identical** to the seed (same objective/endpoint ids) — the provenance does
   not change when you slice it.
6. **Keep `produced_by` = the original planner** that emitted the seed, and append a note
   `"expanded by analysis-variant-expander (<dimension>)"` to `notes`. This preserves the
   schema's `produced_by` (origin planner) while recording that the expander created the variant.
7. **Add the mode note**: `"variant assumed — no SAP provided"` (Mode B) or
   `"variant per SAP §<section>"` (Mode A).
8. Leave `final_id: null` and `status: "planned"` — numbering and feasibility are later stages.

`candidate_id` collisions are a bug: if two variants would produce the same id, the token set is
insufficient — add the distinguishing dimension token.

---

## 5. Worked example — CDISCPILOT01 END1 (the canonical fan-out)

**Seed candidates** arriving from `efficacy-statistics-planner` for END1 (ADAS-Cog (11), CFB to
Week 24, primary continuous efficacy, `traces_to.endpoint_ids: ["Endpoint_1"]`,
`objective_ids: ["Objective_1"]`):

| seed candidate_id | method | class |
|---|---|---|
| `eff-END1-ancova-wk24` | ANCOVA | primary continuous efficacy → **seed, fans out** |
| `eff-END1-mmrm-wk24` | MMRM | sensitivity model → **leaf, pass through** |
| `eff-END1-descriptive-wk24` | Descriptive | descriptive companion → **leaf, pass through** |

Study profile: `needs_subgroup_by_sex = true`, `needs_subgroup_by_region = false`.
Mode B (no SAP).

The ANCOVA seed expands into **four** candidates; MMRM and descriptive pass through unchanged:

| candidate_id | imputation | subgroup | population | priority | maps to CSR | note |
|---|---|---|---|---|---|---|
| `eff-END1-ancova-wk24-locf` | LOCF | null | Efficacy | primary | **T-14-3.01** | assumed |
| `eff-END1-ancova-wk24-oc` | OC | null | Completers | supportive | **T-14-3.07** | assumed |
| `eff-END1-ancova-wk24-locf-male` | LOCF | Sex=Male | Efficacy | supportive | **T-14-3.08** | assumed (gated on `needs_subgroup_by_sex`) |
| `eff-END1-ancova-wk24-locf-female` | LOCF | Sex=Female | Efficacy | supportive | **T-14-3.09** | assumed (gated on `needs_subgroup_by_sex`) |
| `eff-END1-mmrm-wk24` | none | null | Efficacy | supportive | **T-14-3.11** | leaf — unchanged (MMRM is already the sensitivity model) |
| `eff-END1-descriptive-wk24` | none | null | Efficacy | supportive | **T-14-3.10** | leaf — unchanged |

So the single END1 ANCOVA base produces **LOCF + OC-completers-windowed + Male-LOCF +
Female-LOCF**, exactly matching the CSR ground truth (T-14-3.01 / .07 / .08 / .09). MMRM
(T-14-3.11) and descriptive-over-time (T-14-3.10) survive as-is — they are NOT re-expanded.

Region subgroups are **not** emitted because `needs_subgroup_by_region = false`. If a SAP were
supplied naming age bands, Mode A would additionally emit `eff-END1-ancova-wk24-locf-age-*`.

### END1 T-14-3.01 candidate, fully written

```jsonc
{
  "candidate_id": "eff-END1-ancova-wk24-locf",
  "type": "Table",
  "category": "efficacy",
  "title": "Primary Endpoint Analysis: ADAS-Cog (11) - Change from Baseline to Week 24 - LOCF",
  "traces_to": { "objective_ids": ["Objective_1"], "endpoint_ids": ["Endpoint_1"], "regulatory_rule": null },
  "analysis": {
    "method": "ANCOVA", "population": "Efficacy", "timepoint": "Week 24",
    "imputation": "LOCF", "subgroup": null, "comparison": "dose-response"
  },
  "data_requirements": { "adam": ["ADSL", "ADQSADAS"], "sdtm_source": ["DM", "QS"] },
  "status": "planned", "status_reason": null,
  "priority": "primary",
  "produced_by": "efficacy-statistics-planner",
  "final_id": null,
  "notes": ["expanded by analysis-variant-expander (imputation)", "variant assumed — no SAP provided"]
}
```

The Female subgroup variant differs only in `candidate_id`
(`eff-END1-ancova-wk24-locf-female`), `title` (`… - Female subjects`),
`analysis.subgroup` (`"Sex=Female"`), `priority` (`supportive`), and the note
(`expanded by analysis-variant-expander (subgroup by sex)`).

---

## 6. Other CDISCPILOT01 endpoints (for reference)

- **END2** (CIBIC+, primary, global-impression): descriptive/ANOVA summary passes through
  (T-14-3.02); the CMH categorical analysis (T-14-3.13) is a leaf from the efficacy planner —
  no sex fan-out (categorical primary, and no imputation pair unless SAP names one).
- **END6/END7** (secondary, ADAS-Cog / CIBIC+ at **Weeks 8 & 16**): timepoint split only →
  Week 8 + Week 16 candidates (T-14-3.03/.05 and .04/.06). No imputation/subgroup fan-out
  (secondary → single analyses).
- **END8** (secondary, NPI-X windowed): descriptive leaf (T-14-3.12), unchanged.
- **Safety (END3/4/5)** and **scaffolding** (T-14-1.x, T-14-2.01, T-14-4.01, T-14-7.04): all
  leaves — pass through untouched.

---

## 7. Reference files

- [`tlf-candidate-schema.md`](tlf-candidate-schema.md)
  — the candidate object read and written here (field meanings, `category` enum, emitter rules).
- [`pipeline-contract.md`](pipeline-contract.md)
  — input `candidates/*.json`, output `candidates-expanded.json`, execution order.
- [`characterization-rules.md`](characterization-rules.md) — defines the phase-2 feature flags
  (`needs_subgroup_by_sex`, `needs_subgroup_by_region`, …) that this phase gates variant fan-out on.
