# ADaM-Spec Schema (`adam-spec.json`)

The variable-level ADaM requirements derived from the reviewed TLF plan. Produced by
**tlf-analysis-spec** (alongside the analysis specs), consumed by **sdtm-to-adam** to drive/verify
derivation. Generalized from the validated `T-14-3.01` spike.

The purpose is to make the ADaM demand-driven and reviewable: for every TLF, exactly which
datasets, parameters, variables, flags, and derivation rules must exist — so a wrong flag is
caught at review, not after it has silently corrupted every downstream number.

```jsonc
{
  "protocol": "CDISCPILOT01",
  "datasets": [
    {
      "name": "ADQSADAS",
      "class": "BDS",                       // ADSL | BDS | OCCDS | TTE
      "sdtm_source": ["QS"],
      "used_by_tables": ["14-3.01","14-3.03","14-3.05","14-3.07","14-3.08","14-3.09","14-3.10","14-3.11"],
      "parameters": [
        {"paramcd": "ACTOT11", "param": "ADAS-Cog(11) Total", "note": "NOT 'ACTOT' (subscore)"}
      ],
      "variables": [                          // the columns each consuming table needs
        {"name":"AVAL","role":"analysis value"},
        {"name":"BASE","role":"baseline (ABLFL-derived)"},
        {"name":"CHG","role":"change from baseline = AVAL - BASE"},
        {"name":"AVISIT","role":"analysis visit (windowed)"},
        {"name":"AVISITN","role":"analysis visit num"},
        {"name":"ABLFL","role":"baseline record flag"},
        {"name":"ANL01FL","role":"primary analysis record flag (incl. LOCF)"},
        {"name":"DTYPE","role":"'' or 'LOCF'"},
        {"name":"TRTP","role":"planned treatment (grouping)"},
        {"name":"TRT01PN","role":"numeric dose 0/54/81"},
        {"name":"SITEGR1","role":"pooled site group (ANCOVA covariate)","source":"ADSL"},
        {"name":"EFFFL","role":"efficacy population","source":"ADSL"},
        {"name":"ITTFL","role":"ITT population","source":"ADSL"}
      ],
      "derivation_requirements": [ /* see MANDATORY rules below */ ]
    }
  ],
  "populations": [
    {"flag":"EFFFL","label":"Efficacy","definition":"…"},
    {"flag":"SAFFL","label":"Safety","definition":"…"},
    {"flag":"ITTFL","label":"ITT","definition":"…"},
    {"flag":"COMPLFL","label":"Completers","definition":"…"}
  ]
}
```

## MANDATORY derivation rules (learned the hard way — both were real bugs in this repo)

These caused numeric mismatches in the `T-14-3.01` spike until fixed. `sdtm-to-adam` MUST implement
them and assert them.

1. **Analysis-visit windowing must NOT drop unscheduled / early-termination visits.** A hard-coded
   nominal-`VISITNUM` map silently deleted records at unscheduled/ET visits (AMBUL ECG REMOVAL,
   RETRIEVAL, …), losing early terminators from the analysis. **Use day-based (`ADY`/`xxDY`)
   windowing** with midpoint boundaries between scheduled targets; within a subject×window pick the
   record nearest the target day. This is the CDISC-pilot convention.

2. **LOCF records must be created for the endpoint visit.** For every subject in the analysis
   population with a baseline and ≥1 post-baseline value but no observed record at the endpoint
   visit, carry the last observed post-baseline value forward as a `DTYPE='LOCF'`, `ANL01FL='Y'`
   record at the endpoint `AVISITN`. Exactly one primary analysis record per subject per endpoint.

3. **`SITEGR1` pooling counts RANDOMIZED/TREATED subjects, not all-enrolled.** Pool a site into the
   pooled group (`900`) when any planned arm at that site has **< 3 randomized (`ITTFL='Y'`)**
   subjects — NOT a flat count over all enrolled (which includes screen failures). For CDISCPILOT01
   this yields 11 site groups and is required to reproduce the ANCOVA. `SITEGR1` lives in ADSL and
   cascades to every table using site as covariate/stratifier.

## Data-quality gate (required)
After derivation, assert each analysis set's N against its population flag (e.g. Week-24 efficacy N
== `EFFFL='Y'` count = 79/81/74 for CDISCPILOT01) and **warn loudly on a shortfall** — the visit-
window bug above would otherwise pass silently and tank the numeric match.

## Gotchas (CDISCPILOT01)
ADAS-Cog(11) total is `ACTOT11` (not `ACTOT`); treatment factor `TRTP` (character); numeric dose
`TRT01PN` (no `TRTPN`); site `SITEGR1`. ADaM data lives at `outputs/cdiscpilot01-outputs/adam/data/`
as CSV+JSON.
