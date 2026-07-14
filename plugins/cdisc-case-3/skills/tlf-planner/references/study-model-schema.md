# Study Model Schema (`study-model.json`)

The canonical, normalized representation of a study's USDM metadata. Produced by the
**usdm-normalizer** skill and consumed by every downstream planner. This is the single
source of truth for "what the study is trying to measure."

All downstream skills MUST reference objectives/endpoints by these `id` values (which are
the original USDM ids, e.g. `Objective_1`, `Endpoint_1`) so provenance is traceable end-to-end.

```jsonc
{
  "study_id": "CDISCPILOT01",            // from study.versions[].studyIdentifiers or study.name
  "study_name": "…",
  "title": "…",
  "phase": "Phase II",                  // decoded from studyDesigns[].studyPhase, else null
  "usdm_version": "…",
  "source_file": "test-docs/cdiscpilot01/CDISC_Pilot_Study.json",

  "objectives": [
    {
      "id": "Objective_1",               // USDM id — PRESERVE VERBATIM
      "name": "OBJ1",
      "level": "Primary",                // decoded from level.decode: Primary | Secondary | Exploratory
      "description": "Main objective",
      "text": "To determine if there is a statistically significant relationship …",
      "endpoint_ids": ["Endpoint_1", "Endpoint_2"]
    }
  ],

  "endpoints": [
    {
      "id": "Endpoint_1",                // USDM id — PRESERVE VERBATIM
      "name": "END1",
      "objective_id": "Objective_1",     // back-reference
      "level": "Primary",                // Primary | Secondary | Exploratory
      "text": "Alzheimer's Disease Assessment Scale - Cognitive Subscale … ADAS-Cog (11) at Week 24",
      "parsed": {                        // best-effort structured parse of the free-text endpoint
        "measure": "ADAS-Cog (11)",      // the instrument/parameter being measured
        "measure_type": "continuous",    // continuous | categorical | ordinal | event | count | global-impression
        "timepoints": ["Week 24"],       // list; [] if none stated
        "domain_hint": "efficacy-cognition"  // efficacy-* | safety-ae | safety-lab | safety-vs | pk | other
      },
      "resolved": true                   // FALSE when text is a placeholder ("*** To be determined ***"), empty, or unparseable
    }
  ],

  "estimands": [
    {
      "id": "Estimand_1",
      "name": "EST1",
      "population_summary": "Group mean changes from baseline in the primary efficacy parameters",
      "analysis_population_id": "AnalysisPopulation_1",
      "variable_of_interest_endpoint_id": "Endpoint_1",
      "intercurrent_events": [
        { "name": "DISTRUPTION", "text": "Temporary Treatment Interruption",
          "strategy": "Treatment Policy" }   // Treatment Policy | Hypothetical | Composite | While-on-Treatment | Principal Stratum
      ]
    }
  ],

  "analysis_populations": [
    { "id": "AnalysisPopulation_1", "name": "Efficacy", "text": "…", "role": "efficacy" }
    // role: itt | mitt | safety | efficacy | pp | completers | other  (inferred from name/text)
  ],

  "treatment_arms": [
    { "id": "…", "name": "Placebo", "type": "Placebo", "dose": null },
    { "id": "…", "name": "Xanomeline Low Dose", "type": "Active", "dose": "54 mg" },
    { "id": "…", "name": "Xanomeline High Dose", "type": "Active", "dose": "81 mg" }
  ],

  "visit_schedule": [
    { "name": "Week 24", "study_day": null, "epoch": "Treatment" }
  ],

  "unresolved_endpoints": ["Endpoint_9", "Endpoint_10", "Endpoint_11"],  // convenience list of endpoints where resolved=false

  "normalizer_notes": [
    "Endpoint_9/10/11 carry placeholder text '*** To be determined ***' — flagged unresolved."
  ]
}
```

## Parsing guidance

- **`level`**: decode from the USDM `level.decode` (e.g. "Primary Objective" → `Primary`). CDISC C-codes: C85826=Primary Objective, C85827=Secondary Objective, C94496=Primary Endpoint, C139173=Secondary Endpoint.
- **`parsed.measure`**: extract the instrument/parameter name — ADAS-Cog (11), ADAS-Cog (14), CIBIC+, NPI-X, DAD, "Adverse events", "Vital signs", "Laboratory evaluations".
- **`parsed.measure_type`**: infer from the measure — cognitive/lab/vital scores → `continuous`; CIBIC+ global impression → `global-impression`; adverse events → `event`.
- **`parsed.timepoints`**: pull explicit weeks/visits from the text ("at Week 24", "at Weeks 8 and 16" → `["Week 8","Week 16"]`).
- **`resolved`**: set `false` for any endpoint whose text is a placeholder, empty, or otherwise non-substantive. Do NOT drop these — downstream the critic converts them into clarification action items.
- **Fidelity over completeness**: never invent a measure or timepoint. If unsure, leave the field `null` and add a `normalizer_notes` entry.
