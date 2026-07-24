# ARS ReportingEvent — the `reporting-event.json` contract

`tlf-analysis-spec` emits an ARS (Analysis Results Standard) **ReportingEvent** re-expressing the
authored analyses in the CDISC ARS Low-level Data Model. The `validate-ars` gate validates it
against the ARS LDM JSON Schema (`container/schemas/ars_ldm.schema.json`, `$id`
`https://www.cdisc.org/ars/1-0`) plus reference-integrity checks, and routes the run back on any
error. Build it to conform — the fields below are what the gate enforces.

## Required by the schema (minimum to pass)

| Class | Required fields |
|---|---|
| Root `ReportingEvent` | `id`, `name`, `mainListOfContents` |
| `analyses[]` | `id`, `name`, `reason`, `purpose`, `methodId` |
| `methods[]` | `id`, `name`, `operations[]` |
| `operations[]` (in a method) | `id`, `order`, `name` |
| `analysisSets[]` | `id`, `name`, `level`, `order` |
| `analysisGroupings[]` | `id`, `name`, `dataDriven` |
| `outputs[]` | `id`, `name`, `displays[]` |
| `displays[]` (OrderedDisplay) | `order`, `display` → OutputDisplay needs `id`, `name` |
| `mainListOfContents` (ListOfContents) | `name`, `contentsList` (NestedList) |
| list items (OrderedListItem) | `level`, `order`, `name` (+ `analysisId` or `outputId`) |

`reason.controlledTerm` ∈ {`SPECIFIED IN PROTOCOL`, `SPECIFIED IN SAP`, `DATA DRIVEN`,
`REQUESTED BY REGULATORY AGENCY`}. `purpose.controlledTerm` ∈ {`PRIMARY OUTCOME MEASURE`,
`SECONDARY OUTCOME MEASURE`, `EXPLORATORY OUTCOME MEASURE`}. For non-outcome (safety/disposition/
demography) analyses, use a sponsor purpose `{"sponsorTermId":"SPT.SAFETY"}` and declare it once
under `terminologyExtensions` (see the skeleton).

## Reference integrity (also enforced by the gate)

Every `analyses[].methodId` → a `methods[].id`; every `analysisSetId` → an `analysisSets[].id`;
every `dataSubsetId` → a `dataSubsets[].id`; every `orderedGroupings[].groupingId` → an
`analysisGroupings[].id`; every `mainListOfContents` `analysisId`/`outputId` → a defined
analysis/output. Keep ids derived from `table_id` (`AN.<id>`, `OUT.<id>`, `D.<id>`) so the
traceability graph can bridge ARS ↔ TLF.

## Minimal valid skeleton (one efficacy + one safety analysis)

```json
{
  "id": "RE.<STUDYID>",
  "name": "<STUDYID> reporting event",
  "version": 1,
  "analysisSets": [
    { "id": "AS.EFF", "name": "Efficacy", "level": 1, "order": 1,
      "condition": { "dataset": "ADSL", "variable": "EFFFL", "comparator": "EQ", "value": ["Y"] } },
    { "id": "AS.SAF", "name": "Safety", "level": 1, "order": 2,
      "condition": { "dataset": "ADSL", "variable": "SAFFL", "comparator": "EQ", "value": ["Y"] } }
  ],
  "analysisGroupings": [
    { "id": "GRP.TRT", "name": "Treatment", "dataDriven": false, "groupingDataset": "ADSL",
      "groupingVariable": "TRTP",
      "groups": [
        { "id": "G.PBO", "name": "Placebo", "level": 1, "order": 1 },
        { "id": "G.LOW", "name": "Xanomeline Low", "level": 1, "order": 2 },
        { "id": "G.HIGH", "name": "Xanomeline High", "level": 1, "order": 3 }
      ] }
  ],
  "methods": [
    { "id": "MTH.ANCOVA", "name": "ANCOVA of change from baseline",
      "operations": [ { "id": "OP.LSM", "order": 1, "name": "LS mean" },
                      { "id": "OP.DIFF", "order": 2, "name": "LS mean difference vs placebo" },
                      { "id": "OP.PVAL", "order": 3, "name": "p-value" } ] },
    { "id": "MTH.INCID", "name": "Incidence n (%) by SOC/PT",
      "operations": [ { "id": "OP.N", "order": 1, "name": "Subjects with event" },
                      { "id": "OP.PCT", "order": 2, "name": "Percent" } ] }
  ],
  "terminologyExtensions": [
    { "id": "TE.PURPOSE", "enumeration": "AnalysisPurposeEnum",
      "sponsorTerms": [ { "id": "SPT.SAFETY", "submissionValue": "SAFETY" } ] }
  ],
  "analyses": [
    { "id": "AN.14-3.01", "name": "ADAS-Cog(11) change at Week 24 (ANCOVA)",
      "reason": { "controlledTerm": "SPECIFIED IN SAP" },
      "purpose": { "controlledTerm": "PRIMARY OUTCOME MEASURE" },
      "methodId": "MTH.ANCOVA", "analysisSetId": "AS.EFF", "dataset": "ADQSADAS",
      "orderedGroupings": [ { "order": 1, "groupingId": "GRP.TRT", "resultsByGroup": true } ] },
    { "id": "AN.14-5.01", "name": "Incidence of TEAEs by treatment",
      "reason": { "controlledTerm": "SPECIFIED IN SAP" },
      "purpose": { "sponsorTermId": "SPT.SAFETY" },
      "methodId": "MTH.INCID", "analysisSetId": "AS.SAF", "dataset": "ADAE",
      "orderedGroupings": [ { "order": 1, "groupingId": "GRP.TRT", "resultsByGroup": true } ] }
  ],
  "outputs": [
    { "id": "OUT.14-3.01", "name": "Table 14-3.01",
      "displays": [ { "order": 1, "display": { "id": "D.14-3.01",
        "name": "ADAS-Cog(11) change at Week 24" } } ] },
    { "id": "OUT.14-5.01", "name": "Table 14-5.01",
      "displays": [ { "order": 1, "display": { "id": "D.14-5.01",
        "name": "Incidence of TEAEs by treatment" } } ] }
  ],
  "mainListOfContents": {
    "name": "Main list of contents",
    "contentsList": {
      "listItems": [
        { "level": 1, "order": 1, "name": "Efficacy — ADAS-Cog(11)", "outputId": "OUT.14-3.01" },
        { "level": 1, "order": 2, "name": "Safety — TEAEs", "outputId": "OUT.14-5.01" }
      ]
    }
  }
}
```

Scale this to every producible TLF: one `analyses[]` + `outputs[]` + `mainListOfContents` item per
table, reusing shared `analysisSets`/`analysisGroupings`/`methods`. The gate's report
(`/workspace/ars-validation.md`) names the exact `path` of any failure on a re-entry.
