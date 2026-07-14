# Data Domain Map & Feasibility Decision Rules

Reference for the **data-feasibility-checker** skill. It maps each analysis measure/category to
the SDTM domain that carries the raw data and the ADaM dataset that carries the analysis-ready
data, states the rules for deciding `planned` / `blocked` / `needs-clarification`, and records
the worked CDISCPILOT01 result.

The candidate `status` / `status_reason` fields set using this map are defined in the shared
schema: `tlf-candidate-schema.md`.

---

## 1. Measure / category → SDTM domain → ADaM dataset

Match a candidate by its `category`, its `analysis` measure, and its declared
`data_requirements`. The map below is the canonical lookup.

| Candidate category | Measure / content | SDTM domain(s) | ADaM dataset(s) |
|---|---|---|---|
| `disposition` | populations, disposition, by-site | DM, DS, (SV) | ADSL |
| `demographics` | demographics & baseline | DM, (SC, MH) | ADSL |
| `efficacy` / `pro` | ADAS-Cog (11), ADAS-Cog (14) | QS | ADQSADAS |
| `efficacy` / `pro` | CIBIC+ (global impression) | QS | ADQSCIBC |
| `efficacy` / `pro` | NPI-X (neuropsychiatric inventory) | QS | ADQSNPIX |
| `efficacy` / `pro` | DAD (activities of daily living) | QS *(if collected)* | *(none — not derived)* |
| `exposure` | study drug exposure/dosing | EX | ADEX |
| `safety-ae` | adverse events, SAEs, deaths, AE discontinuation | AE | ADAE |
| `safety-ae` | time-to-event AE figure (KM, dermatologic) | AE | ADTTE |
| `safety-lab` | lab summaries, shifts, Hy's Law | LB | ADLB |
| `safety-vs` | vital signs, weight, BP, HR | VS | ADVS |
| `conmeds` | concomitant medications | CM | ADCM |
| `other` (listing) | **protocol deviations** | **DV** | *(none — listing off SDTM)* |
| `other` | medical history | MH | *(ADSL flags / none)* |
| `pk` | PK/PD parameters | PC, PP | ADPC, ADPP |

Common measure keyword → domain shorthand (from the agent brief):
ADAS-Cog / CIBIC+ / NPI-X → **QS / ADQS\***; AE → **AE / ADAE**; labs → **LB / ADLB**;
vitals → **VS / ADVS**; exposure → **EX / ADEX**; conmeds → **CM / ADCM**;
time-to-event → **ADTTE**; protocol deviations → **DV** (no ADaM); demographics/disposition → **DM/DS / ADSL**.

---

## 2. Feasibility decision rules

Apply per candidate, **first match wins**:

1. **needs-clarification — unresolved endpoint.** Any id in `traces_to.endpoint_ids` is in
   `study-model.json` `unresolved_endpoints` → `needs-clarification`.
   Reason: *"Traces to unresolved endpoint <id> ('\*\*\* To be determined \*\*\*'); requires
   protocol/SAP clarification before an output can be planned."*

2. **needs-clarification — no plausible source.** The measure/category maps to no source
   domain in section 1 → `needs-clarification`, naming the unmapped measure.

3. **blocked — required raw source absent.** A required domain is missing from the inventory
   **and cannot be derived** from any present domain → `blocked`, naming the missing domain.

4. **planned — otherwise.** Data requirements are satisfiable → `planned`, `status_reason = null`.

### ADaM-derivable rule (critical)

ADaM datasets are **derived** from SDTM by the downstream `sdtm-to-adam` stage. Therefore a
**missing ADaM dataset does not block** a candidate as long as its underlying SDTM source
domain is present. Only a missing *raw source* (an SDTM domain that no other domain can
substitute for) blocks.

- `ADTTE` absent but `AE` present → **planned** (ADTTE derivable from AE).
- `ADQSNPIX` absent but `QS` present → **planned**.
- `DV` absent, and no domain substitutes for deviations → **blocked** (nothing to derive from).

### What blocks vs. what clarifies

- **blocked** = the *data* is simply not there (e.g. no DV domain → deviations listing).
- **needs-clarification** = the *plan* is under-specified (unresolved endpoint, or a measure
  with no mappable source). This is a human/protocol action item, not a data gap.

Never delete or reorder candidates. Only set `status` + `status_reason`; optionally append a
short caveat to `notes[]`.

---

## 3. Worked CDISCPILOT01 result

**SDTM inventory** (`test-docs/cdiscpilot01/sdtm/*.json`, base names uppercased):
`AE, CM, DM, DS, EX, LB, MH, QS, SC, SE, SV, TA, TE, TI, TS, TV, VS` — plus `SUPPAE, SUPPDM,
SUPPDS, SUPPLB, RELREC`. **DV is absent.**

**ADaM inventory** (`outputs/cdiscpilot01-outputs/adam/data/ad*.json`):
`ADSL, ADAE, ADCM, ADEX, ADLB, ADQSADAS, ADQSCIBC, ADQSNPIX, ADTTE, ADVS`.

| Candidate group | Traces to | Required data | Present? | Status |
|---|---|---|---|---|
| Populations / disposition / by-site (14-1.x) | ICH E3 | DM, DS / ADSL | yes | **planned** |
| Demographics & baseline (14-2.x) | ICH E3 | DM / ADSL | yes | **planned** |
| ADAS-Cog (11) analyses (14-3.x) | END1, END6 | QS / ADQSADAS | yes | **planned** |
| CIBIC+ analyses (14-3.x) | END2, END7 | QS / ADQSCIBC | yes | **planned** |
| NPI-X (14-3.12) | END8 | QS / ADQSNPIX | yes | **planned** |
| Exposure (14-4.01) | OBJ2 | EX / ADEX | yes | **planned** |
| Adverse events (14-5.x) | END3 | AE / ADAE | yes | **planned** |
| Time-to-dermatologic-event KM (F-14-1) | END3 | AE / ADTTE | yes | **planned** |
| Laboratory (14-6.x) | END5 | LB / ADLB | yes | **planned** |
| Vital signs / weight (14-7.01-.03) | END4 | VS / ADVS | yes | **planned** |
| Concomitant meds (14-7.04) | OBJ2 | CM / ADCM | yes | **planned** |
| DAD / ADL (OBJ4) | **END9** | *unresolved* | — | **needs-clarification** |
| ADAS-Cog (14) extended cognition (OBJ5) | **END10** | *unresolved* | — | **needs-clarification** |
| Apo E genotype response (OBJ6) | **END11** | *unresolved* | — | **needs-clarification** |
| Protocol-deviations listing *(if a planner emits one)* | ICH E3 §16 | **DV** | **no** | **blocked** |

**Summary:** every efficacy, safety, and scaffolding candidate is **planned**; the three
END9/END10/END11-derived candidates are **needs-clarification**; a protocol-deviations listing
is **blocked** because no `dv.json` exists in the inventory and deviations cannot be derived
from any present domain.
