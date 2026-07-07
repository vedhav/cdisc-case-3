#!/usr/bin/env python3
"""Step 4 (classify-outputs): decide standard vs custom, and RESOLVE the plan.

DETERMINISTIC. No LLM. Two jobs, both from a fixed rules table:

  1. Classify every ARS Output as `standard` (a validated recipe covers every
     analysis it needs) or `custom` (it needs a fitted model / bespoke display:
     ANCOVA, Kaplan-Meier, ...). The decision is driven by the METHOD family of
     the analyses under the output in the List of Planned Analyses (LOPA), never
     by the output's name.

  2. For every standard output, emit a fully-resolved recipe plan: which recipe,
     over which dataset, with which population filter, subset filters, grouping
     variable, analysis variable(s), the real ARS analysis id, and the
     stat -> operationId map. run_standard.R is then a dumb executor of this
     plan -- all the judgement lives here, in deterministic Python.

Anything the rules cannot map (e.g. inferential comparison analyses, which the
descriptive recipe library does not compute) is recorded as `not_computed` with
a reason -- surfaced in coverage.json and the traceability graph, never silently
dropped.

Writes (into --out, default /workspace):
  coverage.json       per-output mode + recipe/program + analysisIds + status
  standard_plan.json  the resolved recipe plan for the standard outputs

Usage:
  python3 classify_outputs.py --ars /workspace/reporting_event.json \
      --bindings /workspace/bindings.json --out /workspace
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

CUSTOM_KEYWORDS = ("ancova", "kaplan", "cox", "logistic", "mmrm", "mixed model",
                   "time-to-event", "time to event", "survival", "proportional hazards")
COMPARISON_KEYWORDS = ("chi-square", "chi square", "fisher", "anova", "comparison", "p-value")


def index_by_id(coll):
    return {x["id"]: x for x in (coll or [])}


def method_family(method: dict) -> str:
    """Fixed rules table: which computational family a method belongs to."""
    mid = method.get("id", "")
    text = (method.get("name", "") + " " + method.get("description", "") + " " + method.get("label", "")).lower()
    if mid.startswith("MthEff") or any(k in text for k in CUSTOM_KEYWORDS):
        return "custom"
    if mid == "Mth02_ContVar_Summ_ByGrp" or ("continuous" in text and "summ" in text):
        return "continuous_summary"
    if mid in ("Mth01_CatVar_Summ_ByGrp", "Mth01_CatVar_Count_ByGrp") or ("categorical" in text and ("summ" in text or "count" in text)):
        return "categorical_summary"
    if mid.endswith(("_Comp_PChiSq", "_Comp_Anova", "_Comp_FishEx")) or any(k in text for k in COMPARISON_KEYWORDS):
        return "comparison"
    return "unknown"


def walk_lopa(items, output_analyses, current_output=None):
    """Associate every outputId with the analysisIds beneath it in the LOPA tree."""
    for it in items or []:
        oid = it.get("outputId", current_output)
        if it.get("outputId"):
            output_analyses.setdefault(it["outputId"], [])
        if it.get("analysisId") and oid:
            output_analyses.setdefault(oid, [])
            if it["analysisId"] not in output_analyses[oid]:
                output_analyses[oid].append(it["analysisId"])
        sub = it.get("sublist")
        if sub:
            walk_lopa(sub.get("listItems", []), output_analyses, oid)


def operation_map(method: dict, family: str) -> dict:
    """stat_name (as cards emits it) -> ARS operationId, from the method's ops."""
    ops = {o["id"]: o for o in method.get("operations", [])}
    ids = list(ops.keys())

    def find(*suffixes):
        for suf in suffixes:
            for oid in ids:
                if oid.endswith(suf):
                    return oid
        return None

    if family == "continuous_summary":
        return {k: v for k, v in {
            "N": find("_1_n"), "mean": find("_2_Mean"), "sd": find("_3_SD"),
            "median": find("_4_Median"), "p25": find("_5_Q1"), "p75": find("_6_Q3"),
            "min": find("_7_Min"), "max": find("_8_Max"),
        }.items() if v}
    # categorical / count
    n_id = find("_1_n")
    p_id = find("_2_pct")
    m = {}
    if n_id:
        m["n"] = n_id
        m["N"] = n_id
    if p_id:
        m["p"] = p_id
    return m


def pop_filter(bindings, analysis_set_id):
    s = bindings.get("analysisSets", {}).get(analysis_set_id)
    if not s or not s.get("variable"):
        return None
    return {"variable": s["variable"], "comparator": s.get("comparator", "EQ"), "value": s.get("value")}


def subset_filters(bindings, subset_id):
    """Equality/IN/NE conditions of a dataSubset, skipping any malformed clause
    (recorded via the returned `skipped` count)."""
    if not subset_id:
        return [], 0
    ds = bindings.get("dataSubsets", {}).get(subset_id)
    if not ds:
        return [], 0
    filters, skipped = [], 0
    for c in ds.get("conditions", []):
        if c.get("variable") and c.get("value"):
            filters.append({"dataset": c.get("dataset"), "variable": c["variable"],
                            "comparator": c.get("comparator", "EQ"), "value": c["value"]})
        else:
            skipped += 1
    return filters, skipped


def grouping_var(bindings, grouping_id):
    g = bindings.get("groupings", {}).get(grouping_id)
    return g.get("variable") if g else None


def plan_standard_analysis(an, family, method, bindings):
    """Turn one summary analysis into an executable block, or (None, reason)."""
    groupings = an.get("groupingIds", []) or []
    if not groupings:
        return None, "no treatment grouping"
    group_var = grouping_var(bindings, groupings[0])
    other_group_vars = [grouping_var(bindings, g) for g in groupings[1:]]
    other_group_vars = [v for v in other_group_vars if v]
    dataset = an.get("dataset")
    pop = pop_filter(bindings, an.get("analysisSetId"))
    subs, _ = subset_filters(bindings, an.get("dataSubsetId"))
    opmap = operation_map(method, family)

    base = {
        "analysis_id": an["id"], "dataset": dataset, "group_var": group_var,
        "pop_filter": pop, "subset_filters": subs, "operation_map": opmap,
    }

    if family == "continuous_summary":
        return {**base, "recipe": "summary_continuous", "variable": an.get("variable")}, None

    if family == "categorical_summary":
        # AE hierarchical (SOC / SOC+PT)
        if any(v in ("AESOC",) for v in other_group_vars):
            level = "socpt" if any(v in ("AEDECOD", "AEPTCD", "AEHLT") for v in other_group_vars) else "soc"
            return {**base, "recipe": "ae_soc_pt", "level": level,
                    "soc_var": "AESOC", "pt_var": "AEDECOD", "teae_filters": subs}, None
        # AE event-flag count (overall TEAE, related, serious, ...): ADAE, only trt grouping
        if dataset == "ADAE" and not other_group_vars:
            return {**base, "recipe": "ae_overall"}, None
        # Demographic categorical: the categorical variable is the non-treatment grouping
        if other_group_vars:
            return {**base, "recipe": "summary_categorical", "variable": other_group_vars[0]}, None
        # Plain subject count per arm (An01_05-style header)
        return {**base, "recipe": "count_subjects"}, None

    return None, f"method family '{family}' not covered by the recipe library"


def display_for(output_id, blocks):
    """Pick how the output's single rendered display is built from its blocks."""
    recipes = [b["recipe"] for b in blocks]
    if "ae_soc_pt" in recipes:
        return {"type": "ae_soc_pt"}
    if "ae_overall" in recipes:
        return {"type": "ae_overall"}
    conts = [b["variable"] for b in blocks if b["recipe"] == "summary_continuous"]
    cats = [b["variable"] for b in blocks if b["recipe"] == "summary_categorical"]
    if conts or cats:
        return {"type": "summary", "cont_vars": conts, "cat_vars": cats}
    return {"type": "count_subjects"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ars", default="/workspace/reporting_event.json")
    ap.add_argument("--bindings", default="/workspace/bindings.json")
    ap.add_argument("--out", default="/workspace")
    a = ap.parse_args()

    ars = json.loads(Path(a.ars).read_text(encoding="utf-8"))
    bindings = json.loads(Path(a.bindings).read_text(encoding="utf-8"))

    # Plan from the normalized bindings view (groupingIds, dataset, variable,
    # analysisSetId, dataSubsetId already resolved); methods from the ARS.
    analyses = bindings.get("analyses", {})
    methods = index_by_id(ars.get("methods"))

    output_analyses: dict[str, list[str]] = {}
    walk_lopa(ars.get("mainListOfContents", {}).get("contentsList", {}).get("listItems", []), output_analyses)

    coverage = {"outputs": []}
    plan = {"outputs": []}

    for out in ars.get("outputs", []):
        oid = out["id"]
        aids = output_analyses.get(oid, [])
        fams = {aid: method_family(methods.get(analyses.get(aid, {}).get("methodId"), {})) for aid in aids}
        mode = "custom" if any(f == "custom" for f in fams.values()) else "standard"

        computed, not_computed, blocks = [], [], []
        if mode == "standard":
            for aid in aids:
                an = {**analyses.get(aid, {}), "id": aid}
                fam = fams[aid]
                method = methods.get(an.get("methodId"), {})
                if fam in ("continuous_summary", "categorical_summary"):
                    block, reason = plan_standard_analysis(an, fam, method, bindings)
                    if block:
                        block["output_id"] = oid
                        blocks.append(block)
                        computed.append(aid)
                    else:
                        not_computed.append({"analysisId": aid, "methodId": an.get("methodId"), "reason": reason})
                elif fam == "comparison":
                    not_computed.append({"analysisId": aid, "methodId": an.get("methodId"),
                                         "reason": "inferential comparison — outside the descriptive recipe library"})
                else:
                    not_computed.append({"analysisId": aid, "methodId": an.get("methodId"),
                                         "reason": f"unrecognised method family '{fam}'"})
            plan["outputs"].append({"output_id": oid, "display": display_for(oid, blocks), "blocks": blocks})
            recipe_names = sorted({b["recipe"] for b in blocks})
            entry = {"outputId": oid, "name": out.get("name"), "mode": "standard",
                     "recipes": recipe_names, "analysisIds": computed,
                     "analysesNotComputed": not_computed, "status": "planned", "repairs": []}
        else:
            # custom: the AI step drafts a program for the model analyses
            custom_aids = [aid for aid, f in fams.items() if f == "custom"]
            entry = {"outputId": oid, "name": out.get("name"), "mode": "custom",
                     "program": None, "analysisIds": custom_aids,
                     "analysesNotComputed": [], "status": "planned", "repairs": []}
        coverage["outputs"].append(entry)

    out_dir = Path(a.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "coverage.json").write_text(json.dumps(coverage, indent=2), encoding="utf-8")
    (out_dir / "standard_plan.json").write_text(json.dumps(plan, indent=2), encoding="utf-8")

    n_std = sum(1 for e in coverage["outputs"] if e["mode"] == "standard")
    n_cus = len(coverage["outputs"]) - n_std
    n_blocks = sum(len(o["blocks"]) for o in plan["outputs"])
    n_uncomputed = sum(len(e.get("analysesNotComputed", [])) for e in coverage["outputs"])
    print(f"Classified {len(coverage['outputs'])} outputs: {n_std} standard, {n_cus} custom.")
    print(f"Resolved {n_blocks} recipe block(s) across the standard outputs; "
          f"{n_uncomputed} analysis reference(s) recorded as not-computed (surfaced in coverage.json).")
    for e in coverage["outputs"]:
        tag = ",".join(e.get("recipes", [])) if e["mode"] == "standard" else "AI-drafted program"
        print(f"  {e['outputId']:<14} {e['mode']:<9} {tag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
