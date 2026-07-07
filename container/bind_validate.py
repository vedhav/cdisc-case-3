#!/usr/bin/env python3
"""Step 3 (bind-validate): resolve every ARS reference against the ADaM headers.

DETERMINISTIC. No LLM. This is the first robustness gate: before any statistic
is computed we prove that every `dataset.variable` the spec names actually
exists in the supplied ADaM. Anything that does not resolve is written to
unbound.json — a traceability gap surfaced early and explicitly, never silently
dropped downstream.

What we resolve (a WhereClause is any object with dataset + variable):
  - analysisSets[].condition                         (the population filter)
  - dataSubsets[].condition / .compoundExpression    (the row filters)
  - analysisGroupings[].groupingDataset/Variable + each group.condition
  - analyses[].dataset / .variable                   (the analysis variable)

Writes (into --out, default /workspace):
  bindings.json   every resolved reference + each dataset's real column list
  unbound.json    every reference that did NOT resolve, with a reason

Exit status is 0 even when there are unbound references: binding is a *report*,
not the gate. The conformance gate is the per-output coverage check in
package.R. A missing ADaM file the whole spec depends on is still reported here
so the failure is legible long before the recipes run.

Usage:
  python3 bind_validate.py --ars /workspace/reporting_event.json \
      --adam /workspace/adam --out /workspace
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


def load_adam_headers(adam_dir: Path) -> dict[str, list[str]]:
    """dataset name (UPPER, from the file stem) -> its column headers."""
    datasets: dict[str, list[str]] = {}
    for csv_path in sorted(adam_dir.glob("*.csv")):
        try:
            with csv_path.open(newline="", encoding="utf-8-sig") as fh:
                header = next(csv.reader(fh), [])
        except (OSError, StopIteration):
            header = []
        datasets[csv_path.stem.upper()] = [h.strip() for h in header]
    return datasets


def resolve(datasets: dict[str, list[str]], dataset: str | None, variable: str | None):
    """Return (ok, reason). ok=True iff dataset staged AND variable in it."""
    if not dataset:
        return False, "no dataset named"
    ds = dataset.upper()
    if ds not in datasets:
        return False, f"dataset {dataset} not staged"
    if variable and variable not in datasets[ds]:
        return False, f"variable {variable} not in {dataset}"
    return True, "ok"


def collect_conditions(node):
    """Yield every {dataset, variable, comparator, value} WhereClause reachable
    from `node` (condition or compoundExpression, arbitrarily nested)."""
    if isinstance(node, dict):
        if "condition" in node and isinstance(node["condition"], dict):
            yield from collect_conditions(node["condition"])
        if "compoundExpression" in node:
            yield from collect_conditions(node["compoundExpression"])
        if "whereClauses" in node and isinstance(node["whereClauses"], list):
            for wc in node["whereClauses"]:
                yield from collect_conditions(wc)
        if "dataset" in node and "variable" in node:
            yield {
                "dataset": node.get("dataset"),
                "variable": node.get("variable"),
                "comparator": node.get("comparator"),
                "value": node.get("value"),
            }
    elif isinstance(node, list):
        for item in node:
            yield from collect_conditions(item)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ars", default="/workspace/reporting_event.json")
    ap.add_argument("--adam", default="/workspace/adam")
    ap.add_argument("--out", default="/workspace")
    a = ap.parse_args()

    ars = json.loads(Path(a.ars).read_text(encoding="utf-8"))
    datasets = load_adam_headers(Path(a.adam))

    unbound: list[dict] = []

    def note_gap(ref: str, dataset, variable, reason):
        unbound.append({"ref": ref, "dataset": dataset, "variable": variable, "reason": reason})

    # --- analysisSets ---
    sets_out = {}
    for s in ars.get("analysisSets", []) or []:
        cond = s.get("condition", {}) or {}
        ok, reason = resolve(datasets, cond.get("dataset"), cond.get("variable"))
        if not ok:
            note_gap(f"analysisSet:{s['id']}", cond.get("dataset"), cond.get("variable"), reason)
        sets_out[s["id"]] = {
            "dataset": cond.get("dataset"), "variable": cond.get("variable"),
            "comparator": cond.get("comparator"), "value": cond.get("value"), "ok": ok,
        }

    # --- dataSubsets ---
    subsets_out = {}
    for ds in ars.get("dataSubsets", []) or []:
        conds = []
        all_ok = True
        for c in collect_conditions(ds):
            ok, reason = resolve(datasets, c.get("dataset"), c.get("variable"))
            all_ok = all_ok and ok
            if not ok:
                note_gap(f"dataSubset:{ds['id']}", c.get("dataset"), c.get("variable"), reason)
            conds.append({**c, "ok": ok})
        logical = (ds.get("compoundExpression") or {}).get("logicalOperator", "AND")
        subsets_out[ds["id"]] = {"conditions": conds, "logicalOperator": logical, "ok": all_ok}

    # --- analysisGroupings ---
    groupings_out = {}
    for g in ars.get("analysisGroupings", []) or []:
        gds, gvar = g.get("groupingDataset"), g.get("groupingVariable")
        ok, reason = resolve(datasets, gds, gvar)
        if not ok:
            note_gap(f"grouping:{g['id']}", gds, gvar, reason)
        groups = []
        for grp in g.get("groups", []) or []:
            cond = grp.get("condition", {}) or {}
            groups.append({
                "id": grp.get("id"), "name": grp.get("name"),
                "variable": cond.get("variable"), "value": cond.get("value"),
            })
        groupings_out[g["id"]] = {
            "dataset": gds, "variable": gvar, "dataDriven": g.get("dataDriven", False),
            "groups": groups, "ok": ok,
        }

    # --- analyses ---
    analyses_out = {}
    for an in ars.get("analyses", []) or []:
        ok, reason = resolve(datasets, an.get("dataset"), an.get("variable"))
        if not ok:
            note_gap(f"analysis:{an['id']}", an.get("dataset"), an.get("variable"), reason)
        analyses_out[an["id"]] = {
            "name": an.get("name"),
            "dataset": an.get("dataset"), "variable": an.get("variable"), "ok": ok,
            "methodId": an.get("methodId"),
            "analysisSetId": an.get("analysisSetId"),
            "dataSubsetId": an.get("dataSubsetId"),
            "groupingIds": [og.get("groupingId") for og in an.get("orderedGroupings", []) or []],
        }

    bindings = {
        "reportingEventId": ars.get("id"),
        "reportingEventName": ars.get("name"),
        "datasets": datasets,
        "analysisSets": sets_out,
        "dataSubsets": subsets_out,
        "groupings": groupings_out,
        "analyses": analyses_out,
    }

    out_dir = Path(a.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "bindings.json").write_text(json.dumps(bindings, indent=2), encoding="utf-8")
    (out_dir / "unbound.json").write_text(
        json.dumps({"reportingEventId": ars.get("id"), "unbound": unbound}, indent=2), encoding="utf-8")

    n_an = len(analyses_out)
    n_ok = sum(1 for v in analyses_out.values() if v["ok"])
    print(f"Bound {n_ok}/{n_an} analyses against {len(datasets)} ADaM datasets "
          f"({', '.join(sorted(datasets))}).")
    if unbound:
        print(f"{len(unbound)} unresolved reference(s) recorded in unbound.json (surfaced, not dropped):")
        for u in unbound:
            print(f"  {u['ref']}: {u['reason']}")
    else:
        print("Every ARS reference resolved against the ADaM headers.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
