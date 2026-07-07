#!/usr/bin/env python3
"""Curate the demo ARS ReportingEvent for cdisc-case-3.

Base = the official CDISC ARS v1 "Common Safety Displays" (CDISCPILOT01):
5 standard safety outputs (the recipe / deterministic path). We:
  1. strip every analysis's `results` (the INPUT is a spec, not results;
     the pipeline computes them and writes reporting_event_with_results.json),
  2. add 2 efficacy outputs (ADAS-Cog ANCOVA, ADTTE Kaplan-Meier) as the
     CUSTOM / AI-drafted path — spec-complete (method + operations + dataset +
     variable + analysisSet + grouping + dataSubset) but result-free,
  3. validate against the pinned ars_ldm.schema.json.

Result: 7 outputs, 5 standard + 2 custom — the split the demo script narrates.
"""
import json, sys, copy
from pathlib import Path

SCRATCH = Path("/private/tmp/claude-501/-Users-vedha-Repo-mediforce/983d23cf-d17c-4352-82c4-d4d038dcc4e2/scratchpad")
SRC = SCRATCH / "ars" / "Common_Safety_Displays.json"
SCHEMA = SCRATCH / "ars" / "ars_ldm.schema.json"
OUT = Path("/Users/vedha/Repo/cdisc-case-3/fixtures/reporting_event.json")

re = json.load(open(SRC))

# 1) Strip results — the input is a spec. Record how many we dropped.
stripped = 0
for a in re["analyses"]:
    if "results" in a:
        stripped += len(a["results"])
        del a["results"]

# 2a) New methods (efficacy). Mirror the official operation shape.
def op(id_, order, name, label, pattern):
    return {"id": id_, "order": order, "name": name, "label": label, "resultPattern": pattern}

ancova = {
    "id": "MthEff01_ANCOVA_ChgBl",
    "name": "ANCOVA of change from baseline",
    "label": "ANCOVA change from baseline vs placebo",
    "description": "Analysis of covariance of change from baseline with treatment and baseline value as covariates; LS means and treatment differences vs placebo.",
    "operations": [
        op("MthEff01_ANCOVA_ChgBl_1_n", 1, "Count of non-missing values", "n", "XX"),
        op("MthEff01_ANCOVA_ChgBl_2_LSMean", 2, "LS mean of change from baseline", "LS Mean", "XX.X"),
        op("MthEff01_ANCOVA_ChgBl_3_LSMeanSE", 3, "Standard error of LS mean", "SE", "(XX.XX)"),
        op("MthEff01_ANCOVA_ChgBl_4_Diff", 4, "LS mean difference vs placebo", "Diff vs PBO", "XX.X"),
        op("MthEff01_ANCOVA_ChgBl_5_DiffCILower", 5, "Lower 95% CI of difference", "95% CI Lower", "XX.X"),
        op("MthEff01_ANCOVA_ChgBl_6_DiffCIUpper", 6, "Upper 95% CI of difference", "95% CI Upper", "XX.X"),
        op("MthEff01_ANCOVA_ChgBl_7_pval", 7, "p-value for treatment difference", "p-value", "X.XXX"),
    ],
}
km = {
    "id": "MthEff02_KM_TTE",
    "name": "Kaplan-Meier time-to-event analysis",
    "label": "Kaplan-Meier median + Cox hazard ratio vs placebo",
    "description": "Kaplan-Meier estimate of median time to event with a Cox proportional-hazards hazard ratio vs placebo and log-rank p-value.",
    "operations": [
        op("MthEff02_KM_TTE_1_nEvent", 1, "Number of subjects with an event", "Events", "XX"),
        op("MthEff02_KM_TTE_2_Median", 2, "Kaplan-Meier median time to event", "Median (days)", "XX.X"),
        op("MthEff02_KM_TTE_3_HR", 3, "Cox hazard ratio vs placebo", "Hazard Ratio", "XX.XX"),
        op("MthEff02_KM_TTE_4_HRCILower", 4, "Lower 95% CI of hazard ratio", "95% CI Lower", "XX.XX"),
        op("MthEff02_KM_TTE_5_HRCIUpper", 5, "Upper 95% CI of hazard ratio", "95% CI Upper", "XX.XX"),
        op("MthEff02_KM_TTE_6_pval", 6, "Log-rank p-value", "p-value", "X.XXX"),
    ],
}
re["methods"].extend([ancova, km])

# 2b) New dataSubsets (the row filters the efficacy analyses need).
n_dss = len(re["dataSubsets"])
re["dataSubsets"].append({
    "id": "DssEff01_ADAS_Wk24", "name": "ADAS-Cog(11) total at Week 24",
    "level": 1, "order": n_dss + 1,
    "compoundExpression": {
        "logicalOperator": "AND",
        "whereClauses": [
            {"level": 2, "order": 1, "condition": {"dataset": "ADQSADAS", "variable": "PARAMCD", "comparator": "EQ", "value": ["ACTOT"]}},
            {"level": 2, "order": 2, "condition": {"dataset": "ADQSADAS", "variable": "AVISITN", "comparator": "EQ", "value": ["24"]}},
            {"level": 2, "order": 3, "condition": {"dataset": "ADQSADAS", "variable": "ANL01FL", "comparator": "EQ", "value": ["Y"]}},
        ],
    },
})
re["dataSubsets"].append({
    "id": "DssEff02_TTE_Primary", "name": "Primary time-to-event parameter",
    "level": 1, "order": n_dss + 2,
    "condition": {"dataset": "ADTTE", "variable": "PARAMCD", "comparator": "EQ", "value": ["TTDERM"]},
})

# 2c) New analyses (ITT, treatment grouping — both already defined in the base).
re["analyses"].append({
    "id": "AnEff01_ADAS_Wk24_ANCOVA",
    "name": "ADAS-Cog (11) Change from Baseline to Week 24 - ANCOVA",
    "reason": {"controlledTerm": "SPECIFIED IN SAP"},
    "purpose": {"controlledTerm": "PRIMARY OUTCOME MEASURE"},
    "methodId": "MthEff01_ANCOVA_ChgBl",
    "dataset": "ADQSADAS", "variable": "CHG",
    "analysisSetId": "AnalysisSet_01_ITT",
    "dataSubsetId": "DssEff01_ADAS_Wk24",
    "orderedGroupings": [{"order": 1, "groupingId": "AnlsGrouping_01_Trt", "resultsByGroup": True}],
})
re["analyses"].append({
    "id": "AnEff02_TTE_KM",
    "name": "Time to First Dermatologic Event - Kaplan-Meier",
    "reason": {"controlledTerm": "SPECIFIED IN SAP"},
    "purpose": {"controlledTerm": "SECONDARY OUTCOME MEASURE"},
    "methodId": "MthEff02_KM_TTE",
    "dataset": "ADTTE", "variable": "AVAL",
    "analysisSetId": "AnalysisSet_01_ITT",
    "dataSubsetId": "DssEff02_TTE_Primary",
    "orderedGroupings": [{"order": 1, "groupingId": "AnlsGrouping_01_Trt", "resultsByGroup": True}],
})

# 2d) New outputs. Mirror the official display/section shape so the renderer
#     has titles + footers + file specs to work from.
def display_sections(disp_id, table_no, title, source_ds):
    return [
        {"sectionType": "Title", "orderedSubSections": [
            {"order": 1, "subSection": {"id": f"{disp_id}_Title_1", "text": table_no}},
            {"order": 2, "subSection": {"id": f"{disp_id}_Title_2", "text": title}},
        ]},
        {"sectionType": "Footer", "orderedSubSections": [
            {"order": 1, "subSection": {"id": f"{disp_id}_Footer_1",
                                        "text": f"Source dataset: {source_ds}, Generated on: DDMONYYYY:HH:MM"}},
        ]},
    ]

re["outputs"].append({
    "id": "Out14-3-01",
    "name": "ADAS-Cog (11) Change from Baseline to Week 24 (ANCOVA)",
    "version": 1,
    "displays": [{"order": 1, "display": {
        "id": "Disp14-3-01", "name": "ADAS-Cog Week 24 ANCOVA", "label": "ADAS Wk24", "version": 1,
        "displayTitle": "ADAS-Cog (11) Change from Baseline to Week 24 - ANCOVA",
        "displaySections": display_sections("Disp14-3-01", "Table 14-3.01",
                                            "ADAS-Cog (11) Change from Baseline to Week 24 - ANCOVA", "adqsadas"),
    }}],
    "fileSpecifications": [
        {"name": "t14-3-01-adas-ancova (RTF)", "label": "t14-3-01-adas-ancova",
         "fileType": {"controlledTerm": "rtf"}, "location": "./t14-3-01-adas-ancova.rtf"},
    ],
})
re["outputs"].append({
    "id": "Out14-KM-01",
    "name": "Time to First Dermatologic Event (Kaplan-Meier)",
    "version": 1,
    "displays": [{"order": 1, "display": {
        "id": "Disp14-KM-01", "name": "TTDE Kaplan-Meier", "label": "TTDE KM", "version": 1,
        "displayTitle": "Time to First Dermatologic Event - Kaplan-Meier",
        "displaySections": display_sections("Disp14-KM-01", "Figure 14-KM.01",
                                            "Time to First Dermatologic Event - Kaplan-Meier", "adtte"),
    }}],
    "fileSpecifications": [
        {"name": "f14-km-01-ttde (PDF)", "label": "f14-km-01-ttde",
         "fileType": {"controlledTerm": "pdf"}, "location": "./f14-km-01-ttde.pdf"},
    ],
})

# 2e) Register the efficacy outputs in the Lists of Contents so the
#     output -> analysis linkage is STRUCTURAL (the safety outputs already are).
#     Without this the only place Out14-3-01 -> AnEff01 lived was hardcoded driver
#     code; classify_outputs.py / package.R now derive it from the LOPA by walking
#     the tree, so every output is traceable to its analysis by construction.
lopa = re["mainListOfContents"]["contentsList"]["listItems"]
_other = re["otherListsOfContents"]
if isinstance(_other, dict):
    _other = [_other]
lopo = next((o for o in _other if o.get("label") == "LOPO"), _other[0])["contentsList"]["listItems"]
_eff_lop = [
    ("Out14-3-01", "ADAS-Cog (11) Change from Baseline to Week 24 (ANCOVA)",
     "ADAS-Cog (11) Change from Baseline to Week 24 - ANCOVA", "AnEff01_ADAS_Wk24_ANCOVA"),
    ("Out14-KM-01", "Time to First Dermatologic Event (Kaplan-Meier)",
     "Time to First Dermatologic Event - Kaplan-Meier", "AnEff02_TTE_KM"),
]
for _i, (_oid, _oname, _aname, _aid) in enumerate(_eff_lop):
    _order = len(lopa) + 1
    lopa.append({"name": _oname, "level": 1, "order": _order, "outputId": _oid,
                 "sublist": {"listItems": [
                     {"name": _aname, "level": 2, "order": 1, "analysisId": _aid}]}})
    lopo.append({"name": _oname, "level": 1, "order": len(lopo) + 1, "outputId": _oid})

# 3) Validate against the pinned schema.
import jsonschema
schema = json.load(open(SCHEMA))
jsonschema.validate(instance=re, schema=schema)

OUT.parent.mkdir(parents=True, exist_ok=True)
json.dump(re, open(OUT, "w"), indent=2)

print(f"OK — wrote {OUT}")
print(f"  stripped {stripped} pre-computed results (input is a spec)")
print(f"  outputs: {len(re['outputs'])}  analyses: {len(re['analyses'])}  methods: {len(re['methods'])}  dataSubsets: {len(re['dataSubsets'])}")
print("  output ids:", [o["id"] for o in re["outputs"]])
