"""Deterministically assemble the traceability graph model.

Runs as the `assemble-trace-graph` script step — the correctness-critical half of
the traceability layer, split out of the `traceability-builder` agent so the
objective -> endpoint -> SDTM -> ADaM -> TLF join, the two-way coverage audit, and
the issues feed are computed by code, not guessed by an LLM. The downstream
`build-traceability` agent then only *renders* this JSON into the HTML explorer.

Reads (from /workspace, written by the earlier pipeline steps):
  study-model.json     objectives[], endpoints[], unresolved_endpoints[], study_*
  tlf-plan.json        array of TLF candidates (tlf-candidate-schema.md)
  analysis-spec.json   per-TLF ARS-aligned recipe (array | {table_id: spec} | one)
  adam-spec.json       { protocol, datasets[], populations[] }
  sdtm/                staged SDTM inventory (from stage_inputs.py) — for `absent`
  ard/<id>.json        per-TLF ARD (embedded into TLF meta when present)
  tfl/<id>.*           per-TLF rendered display (generated.md) — embedded when present
  code/<id>.R          per-TLF generation code — embedded when present
  issues.md            optional free-text data-quality notes (folded into issues[])

Writes:
  /workspace/trace_graph.json  the model in graph-data-schema.md (authoritative)
  /workspace/manifest.json     per-TLF inventory + counts
  /output/trace_graph.json     copy for the run's Output Files
  /output/manifest.json        copy
  /output/result.json          { ok, counts, status, issues } summary

Paths are overridable via WORKSPACE_DIR / OUTPUT_DIR for local testing. Every leaf
field is optional: a missing artifact yields a clearly-marked node, never a drop.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

WORKSPACE = Path(os.environ.get("WORKSPACE_DIR", "/workspace"))
OUTPUT = Path(os.environ.get("OUTPUT_DIR", "/output"))

TLF_ID_PREFIXES = ("T-", "F-", "L-")

# graph-data-schema.md — tier per node type (layout column).
TIER_BY_TYPE = {"Objective": 0, "Endpoint": 1, "Regulatory": 1, "TLF": 2, "ADaM": 3, "SDTM": 4}


def load_json(path: Path) -> Any:
    """Parse a JSON file, or return None when absent/unparseable (leaf-optional)."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def table_id_from_final(final_id: str | None) -> str | None:
    """`T-14-3.01` -> `14-3.01`; matches analysis-spec.json `table_id`."""
    if not final_id:
        return None
    for prefix in TLF_ID_PREFIXES:
        if final_id.startswith(prefix):
            return final_id[len(prefix):]
    return final_id


def normalize_analysis_specs(raw: Any) -> dict[str, dict]:
    """Accept an array of specs, a {table_id: spec} map, or one spec; index by table_id."""
    specs: dict[str, dict] = {}
    if isinstance(raw, list):
        entries = raw
    elif isinstance(raw, dict) and "table_id" in raw:
        entries = [raw]
    elif isinstance(raw, dict):
        entries = list(raw.values())
    else:
        entries = []
    for entry in entries:
        if isinstance(entry, dict):
            tid = entry.get("table_id") or table_id_from_final(entry.get("id"))
            if tid:
                specs[str(tid)] = entry
    return specs


def sdtm_inventory(workspace: Path) -> set[str]:
    """Domain codes present in the staged SDTM directory (filename stem, upper-cased)."""
    sdtm_dir = workspace / "sdtm"
    present: set[str] = set()
    if not sdtm_dir.is_dir():
        return present
    for child in sdtm_dir.iterdir():
        # Any staged dataset file (.csv/.xpt/.sas7bdat/Dataset-JSON) names a domain by
        # its stem; skip manifests / hidden files (leading underscore or dot).
        if child.is_file() and not child.name.startswith(("_", ".")):
            present.add(child.stem.upper())
    return present


def first_existing(workspace: Path, subdir: str, ids: list[str | None], suffixes: list[str]) -> tuple[str | None, str | None]:
    """Return (relative_path, contents) of the first artifact found for a TLF."""
    base = workspace / subdir
    for ident in ids:
        if not ident:
            continue
        for suffix in suffixes:
            candidate = base / f"{ident}{suffix}"
            if candidate.is_file():
                return f"{subdir}/{candidate.name}", read_text(candidate)
    return None, None


def endpoint_sublabel(parsed: dict | None, text: str | None, level: str | None) -> str:
    """Endpoint face: measure + short timepoint(s); fall back to text/level."""
    if isinstance(parsed, dict):
        measure = parsed.get("measure")
        timepoints = parsed.get("timepoints") or []
        short_tps = [str(tp).replace("Week ", "Wk") for tp in timepoints]
        if measure and short_tps:
            return f"{measure} · {'/'.join(short_tps)}"
        if measure:
            return str(measure)
    if text:
        return text[:60] + ("…" if len(text) > 60 else "")
    return level or "Endpoint"


def objective_sublabel(text: str | None, level: str | None) -> str:
    if text:
        clause = text.split(",")[0].split(".")[0].strip()
        return clause[:70] + ("…" if len(clause) > 70 else "")
    return level or "Objective"


def variable_source_domains(role: str, source: str | None, dataset_domains: list[str]) -> list[str]:
    """Subset of the dataset's SDTM sources this variable draws from (best-effort)."""
    role_upper = (role or "").upper()
    matched = [d for d in dataset_domains if d.upper() in role_upper]
    if matched:
        return matched
    if source and source.upper() in {d.upper() for d in dataset_domains}:
        return [source.upper()]
    return []


def build_graph() -> dict:
    study_model = load_json(WORKSPACE / "study-model.json") or {}
    tlf_plan = load_json(WORKSPACE / "tlf-plan.json") or []
    analysis_specs = normalize_analysis_specs(load_json(WORKSPACE / "analysis-spec.json"))
    adam_spec = load_json(WORKSPACE / "adam-spec.json") or {}
    present_domains = sdtm_inventory(WORKSPACE)

    if isinstance(tlf_plan, dict):  # tolerate {"tlfs": [...]} / {"candidates": [...]}
        tlf_plan = tlf_plan.get("tlfs") or tlf_plan.get("candidates") or []

    objectives = study_model.get("objectives") or []
    endpoints = study_model.get("endpoints") or []
    unresolved = set(study_model.get("unresolved_endpoints") or [])
    adam_datasets = adam_spec.get("datasets") or []

    nodes: list[dict] = []
    edges: list[dict] = []
    issues: list[dict] = []

    # --- Objective + Endpoint nodes and obj-end edges ---
    endpoint_by_id = {e.get("id"): e for e in endpoints if isinstance(e, dict)}
    for obj in objectives:
        oid = obj.get("id")
        if not oid:
            continue
        nodes.append({
            "id": f"obj:{oid}", "type": "Objective", "tier": TIER_BY_TYPE["Objective"],
            "label": obj.get("name") or oid, "sublabel": objective_sublabel(obj.get("text"), obj.get("level")),
            "title": obj.get("text") or obj.get("description") or oid,
            "meta": {"level": obj.get("level"), "description": obj.get("description"),
                     "text": obj.get("text"), "endpoints": [f"end:{eid}" for eid in obj.get("endpoint_ids") or []]},
        })
        for eid in obj.get("endpoint_ids") or []:
            edges.append({"source": f"obj:{oid}", "target": f"end:{eid}", "kind": "obj-end", "dashed": False, "rule": None})

    for ep in endpoints:
        eid = ep.get("id")
        if not eid:
            continue
        parsed = ep.get("parsed") if isinstance(ep.get("parsed"), dict) else {}
        resolved = ep.get("resolved", True) and eid not in unresolved
        nodes.append({
            "id": f"end:{eid}", "type": "Endpoint", "tier": TIER_BY_TYPE["Endpoint"],
            "label": ep.get("name") or eid,
            "sublabel": endpoint_sublabel(parsed, ep.get("text"), ep.get("level")),
            "title": ep.get("text") or eid, "unresolved": not resolved,
            "meta": {"level": ep.get("level"), "text": ep.get("text"), "objective": f"obj:{ep.get('objective_id')}" if ep.get("objective_id") else None,
                     "resolved": resolved, "measure": parsed.get("measure"), "measure_type": parsed.get("measure_type"),
                     "timepoints": parsed.get("timepoints") or [], "domain_hint": parsed.get("domain_hint")},
        })
        if not resolved:
            issues.append({"severity": "clarification",
                           "message": f"Endpoint {ep.get('name') or eid} is unresolved (placeholder / non-substantive text) — no analysis can be planned until it is clarified.",
                           "nodeId": f"end:{eid}", "relatedNodeIds": []})

    # --- ADaM datasets index (name -> spec) for TLF joins ---
    adam_by_name = {d.get("name"): d for d in adam_datasets if isinstance(d, dict) and d.get("name")}

    # --- Regulatory shared node (only if any candidate is scaffolding-driven) ---
    reg_node_id = "reg:ich-e3"
    reg_used = any(isinstance(c, dict) and (c.get("traces_to") or {}).get("regulatory_rule") for c in tlf_plan)
    if reg_used:
        nodes.append({"id": reg_node_id, "type": "Regulatory", "tier": TIER_BY_TYPE["Regulatory"],
                      "label": "ICH E3", "sublabel": "ICH E3", "title": "ICH E3 §14 regulatory scaffolding",
                      "meta": {"standard": "ICH E3", "note": "Population/disposition/exposure tables no objective points to."}})

    # --- TLF nodes + their edges to endpoints, regulatory, ADaM, SDTM ---
    referenced_domains: set[str] = set()
    endpoints_with_tlf: set[str] = set()
    objectives_with_tlf: set[str] = set()

    for cand in tlf_plan:
        if not isinstance(cand, dict):
            continue
        cid = cand.get("candidate_id")
        if not cid:
            continue
        traces = cand.get("traces_to") or {}
        analysis = cand.get("analysis") or {}
        data_req = cand.get("data_requirements") or {}
        final_id = cand.get("final_id")
        tid = table_id_from_final(final_id)
        spec = analysis_specs.get(tid or "", {})

        rendered_path, rendered = first_existing(WORKSPACE, "tfl", [final_id, tid, cid], [".generated.md", ".md"])
        ard_path, ard = first_existing(WORKSPACE, "ard", [final_id, tid, cid], [".json", ".ard.json"])
        code_path, code = first_existing(WORKSPACE, "code", [final_id, tid, cid], [".R", ".r"])

        plan_status = cand.get("status") or "planned"
        if plan_status == "blocked":
            status = "blocked"
        elif plan_status == "needs-clarification":
            status = "needs-clarification"
        elif rendered is not None or ard is not None:
            status = "generated"
        else:
            status = "needs-clarification"

        is_figure = str(cand.get("type") or "").lower() == "figure"
        # ADaM datasets: adam-spec used_by_tables is authoritative; fall back to plan data_requirements.
        adam_from_spec = [d.get("name") for d in adam_datasets
                          if isinstance(d, dict) and tid and tid in (d.get("used_by_tables") or [])]
        adam_names = adam_from_spec or [a for a in (data_req.get("adam") or []) if a]
        sdtm_declared = [s for s in (data_req.get("sdtm_source") or []) if s]
        referenced_domains.update(s.upper() for s in sdtm_declared)

        node_id = f"tlf:{cid}"
        nodes.append({
            "id": node_id, "type": "TLF", "tier": TIER_BY_TYPE["TLF"],
            "label": final_id or cid, "sublabel": cand.get("title") or cand.get("type") or cid,
            "title": cand.get("title") or cid, "status": status, "isFigure": is_figure,
            "unresolved": status == "needs-clarification",
            "meta": {
                "candidate_id": cid, "final_id": final_id, "type": cand.get("type"), "category": cand.get("category"),
                "title": cand.get("title"), "status": status, "status_reason": cand.get("status_reason"),
                "priority": cand.get("priority"), "produced_by": cand.get("produced_by"), "notes": cand.get("notes") or [],
                "method": analysis.get("method"), "population": analysis.get("population"), "timepoint": analysis.get("timepoint"),
                "imputation": analysis.get("imputation"), "subgroup": analysis.get("subgroup"), "comparison": analysis.get("comparison"),
                "objectives": [f"obj:{o}" for o in traces.get("objective_ids") or []],
                "endpoints": [f"end:{e}" for e in traces.get("endpoint_ids") or []],
                "regulatory_rule": traces.get("regulatory_rule"),
                "adam": [f"adam:{a}" for a in adam_names], "sdtm": [f"sdtm:{s.upper()}" for s in sdtm_declared],
                "analysisSet": (spec.get("analysisSet") or {}).get("label"),
                "analysisSetCond": (spec.get("analysisSet") or {}).get("condition"),
                "dataSubset": (spec.get("dataSubset") or {}).get("condition"), "purpose": spec.get("purpose"),
                "generatedMd": rendered, "ardJson": ard, "generateR": code, "generateRPath": code_path, "isFigure": is_figure,
            },
        })

        for eid in traces.get("endpoint_ids") or []:
            edges.append({"source": f"end:{eid}", "target": node_id, "kind": "end-tlf", "dashed": False, "rule": None})
            endpoints_with_tlf.add(eid)
        for oid in traces.get("objective_ids") or []:
            objectives_with_tlf.add(oid)
        if traces.get("regulatory_rule") and reg_used:
            edges.append({"source": reg_node_id, "target": node_id, "kind": "reg-tlf", "dashed": False, "rule": traces.get("regulatory_rule")})
        for aname in adam_names:
            edges.append({"source": node_id, "target": f"adam:{aname}", "kind": "tlf-adam", "dashed": False, "rule": None})
        # tlf-sdtm dashed: a declared domain with no ADaM bridge (blocked/clarify tables).
        bridged = {s.upper() for aname in adam_names for s in (adam_by_name.get(aname, {}).get("sdtm_source") or [])}
        for s in sdtm_declared:
            if s.upper() not in bridged:
                edges.append({"source": node_id, "target": f"sdtm:{s.upper()}", "kind": "tlf-sdtm", "dashed": True, "rule": None})

        if status == "blocked":
            related = [f"sdtm:{s.upper()}" for s in sdtm_declared if s.upper() not in present_domains] if present_domains else []
            issues.append({"severity": "blocked", "message": cand.get("status_reason") or f"{final_id or cid} is blocked.",
                           "nodeId": node_id, "relatedNodeIds": related})
        elif status == "needs-clarification":
            issues.append({"severity": "clarification", "message": cand.get("status_reason") or f"{final_id or cid} needs clarification.",
                           "nodeId": node_id, "relatedNodeIds": []})

    # --- ADaM nodes + adam-sdtm edges ---
    for ds in adam_datasets:
        if not isinstance(ds, dict):
            continue
        name = ds.get("name")
        if not name:
            continue
        domains = [d for d in (ds.get("sdtm_source") or []) if d]
        referenced_domains.update(d.upper() for d in domains)
        variables = []
        for var in ds.get("variables") or []:
            if isinstance(var, dict) and var.get("name"):
                variables.append({"name": var.get("name"), "role": var.get("role"),
                                  "source_domains": variable_source_domains(var.get("role") or "", var.get("source"), domains)})
        nodes.append({"id": f"adam:{name}", "type": "ADaM", "tier": TIER_BY_TYPE["ADaM"],
                      "label": name, "sublabel": ds.get("class") or name, "title": f"{name} ({ds.get('class') or 'ADaM'})",
                      "meta": {"klass": ds.get("class"), "sdtm_source": domains, "used_by_tables": ds.get("used_by_tables") or [],
                               "derivation_requirements": ds.get("derivation_requirements") or [],
                               "parameters": ds.get("parameters") or [], "variables": variables}})
        for d in domains:
            edges.append({"source": f"adam:{name}", "target": f"sdtm:{d.upper()}", "kind": "adam-sdtm", "dashed": False, "rule": None})

    # --- SDTM nodes (referenced ∪ present); flag `absent` when referenced but not in inventory ---
    all_domains = referenced_domains | present_domains
    for domain in sorted(all_domains):
        absent = bool(present_domains) and domain not in present_domains and domain in referenced_domains
        nodes.append({"id": f"sdtm:{domain}", "type": "SDTM", "tier": TIER_BY_TYPE["SDTM"],
                      "label": domain, "sublabel": domain, "title": f"SDTM domain {domain}", "absent": absent,
                      "meta": {"domain": domain, "label": domain, "absent": absent}})
        if absent:
            blocked_tables = [c.get("final_id") or c.get("candidate_id") for c in tlf_plan
                              if isinstance(c, dict) and domain in {s.upper() for s in (c.get("data_requirements") or {}).get("sdtm_source") or []}]
            issues.append({"severity": "blocked",
                           "message": f"SDTM domain {domain} is required but absent from the staged inventory; it blocks: {', '.join(t for t in blocked_tables if t) or 'unknown tables'}.",
                           "nodeId": f"sdtm:{domain}", "relatedNodeIds": []})

    # --- Coverage gaps: objectives / resolved endpoints with no downstream TLF ---
    for obj in objectives:
        oid = obj.get("id")
        if oid and oid not in objectives_with_tlf:
            child_eps = set(obj.get("endpoint_ids") or [])
            if not (child_eps & endpoints_with_tlf):
                issues.append({"severity": "gap",
                               "message": f"Objective {obj.get('name') or oid} has no downstream TLF.",
                               "nodeId": f"obj:{oid}", "relatedNodeIds": []})
    for ep in endpoints:
        eid = ep.get("id")
        resolved = ep.get("resolved", True) and eid not in unresolved
        if eid and resolved and eid not in endpoints_with_tlf:
            issues.append({"severity": "gap", "message": f"Endpoint {ep.get('name') or eid} is resolved but has no TLF.",
                           "nodeId": f"end:{eid}", "relatedNodeIds": []})

    # --- Optional free-text issues.md ---
    issues_md = read_text(WORKSPACE / "issues.md")
    if issues_md:
        for line in issues_md.splitlines():
            stripped = line.lstrip("-* ").strip()
            if stripped and not stripped.startswith("#"):
                issues.append({"severity": "info", "message": stripped, "nodeId": None, "relatedNodeIds": []})

    tlf_nodes = [n for n in nodes if n["type"] == "TLF"]
    status_tally = {"generated": 0, "blocked": 0, "needs-clarification": 0}
    for n in tlf_nodes:
        status_tally[n["status"]] = status_tally.get(n["status"], 0) + 1

    counts = {
        "objectives": len(objectives), "endpoints": len(endpoints), "endpoints_unresolved": len(unresolved),
        "sdtm": sum(1 for n in nodes if n["type"] == "SDTM"),
        "sdtm_absent": sum(1 for n in nodes if n["type"] == "SDTM" and n.get("absent")),
        "adam": sum(1 for n in nodes if n["type"] == "ADaM"),
        "tlf": len(tlf_nodes), "tlf_producible": status_tally["generated"],
    }

    return {
        "study": {"id": study_model.get("study_id"), "name": study_model.get("study_name"),
                  "title": study_model.get("title"), "phase": study_model.get("phase")},
        "counts": counts, "status": status_tally, "issues": issues, "nodes": nodes, "edges": edges,
    }


def build_manifest(graph: dict) -> dict:
    tables = []
    for n in graph["nodes"]:
        if n["type"] != "TLF":
            continue
        m = n["meta"]
        tables.append({"candidate_id": m.get("candidate_id"), "final_id": m.get("final_id"),
                       "title": m.get("title"), "status": n["status"], "isFigure": n.get("isFigure", False),
                       "hasRendered": m.get("generatedMd") is not None, "hasArd": m.get("ardJson") is not None,
                       "hasCode": m.get("generateR") is not None})
    return {"study": graph["study"], "counts": graph["counts"], "status": graph["status"], "tables": tables}


def main() -> None:
    graph = build_graph()
    manifest = build_manifest(graph)

    WORKSPACE.mkdir(parents=True, exist_ok=True)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for target in (WORKSPACE, OUTPUT):
        (target / "trace_graph.json").write_text(json.dumps(graph, indent=2), encoding="utf-8")
        (target / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    result = {"ok": True, "counts": graph["counts"], "status": graph["status"], "issues": len(graph["issues"])}
    (OUTPUT / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"build_trace_graph: {graph['counts']['tlf']} TLFs, {len(graph['nodes'])} nodes, "
          f"{len(graph['edges'])} edges, {len(graph['issues'])} issues", file=sys.stderr)


if __name__ == "__main__":
    main()
