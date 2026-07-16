"""Deterministic traceability explorer for the cdisc-case-3 pipeline.

Runs as the `build-traceability` script step (formerly the agentic
`traceability-builder` skill). This step **never recomputes a statistic** — it is
a pure reporting/visualisation layer that reads the artifacts a run has already
produced and assembles them into one self-contained, interactive HTML explorer.
Making it deterministic removes the per-run LLM cost/nondeterminism: the graph
model is assembled from the JSON contracts and injected into a fixed vanilla
JS + SVG application (zero external requests, theme-aware, offline-openable).

Inputs (read from /workspace, with /output as a fallback):
  study-model.json    objectives (+ level) + endpoints, obj->endpoint links,
                      endpoint `resolved` flag, `unresolved_endpoints`
  tlf-plan.json       TLF candidates: traces_to{objective_ids,endpoint_ids,
                      regulatory_rule}, category, type, final_id, candidate_id,
                      status, status_reason, data_requirements{adam[],sdtm[]}
  analysis-spec.json  per-TLF method / analysisSet / dataSubset / purpose
  adam-spec.json      datasets[]: sdtm_source[], used_by_tables[], variables[],
                      parameters[], derivation_requirements[]
  per-table outputs   /workspace/{tfl,ard,code}/<id>.* (cdisc-case-3 layout),
                      with the protocol-to-tfl layout (<id>.generated.md /
                      ard.json / generate.R) accepted as a fallback
  issues.md           optional free-text data-quality notes (folded into issues)

Outputs (written to /output, and mirrored to /workspace):
  traceability.html   the self-contained interactive explorer
  trace_graph.json    the assembled graph model (nodes + edges + issues + counts)
  manifest.json       run manifest (study, files, counts, status tallies)
  result.json         step summary { status, counts, status, issues, outputs }

Contract reference: plugins/cdisc-case-3/skills/traceability-builder/references/
graph-data-schema.md — this script implements that model field-for-field. Parsing
is deliberately tolerant (missing optional fields never drop a node; a node with
only a code label still renders, clearly marked).
"""

from __future__ import annotations

import csv
import io
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

WORKSPACE = Path(os.environ.get("WORKSPACE_DIR", "/workspace"))
OUTPUT = Path(os.environ.get("OUTPUT_DIR", "/output"))

# Cap embedded per-table payloads so one huge table cannot bloat the page past
# what a browser opens comfortably; the panel notes when content was truncated.
MAX_EMBED_CHARS = 400_000

TYPE_PREFIX = {
    "Objective": "obj",
    "Endpoint": "end",
    "Regulatory": "reg",
    "TLF": "tlf",
    "ADaM": "adam",
    "SDTM": "sdtm",
}
TIER = {"Objective": 0, "Endpoint": 1, "Regulatory": 1, "TLF": 2, "ADaM": 3, "SDTM": 4}


# --------------------------------------------------------------------------- #
# IO helpers
# --------------------------------------------------------------------------- #
def load_json(name: str):
    """Load a JSON artifact from /workspace, falling back to /output. None if absent."""
    for base in (WORKSPACE, OUTPUT):
        p = base / name
        if p.is_file():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as exc:  # pragma: no cover - defensive
                sys.stderr.write(f"[build_traceability] failed to parse {p}: {exc}\n")
    return None


def read_text_capped(path: Path):
    try:
        txt = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None, False
    if len(txt) > MAX_EMBED_CHARS:
        return txt[:MAX_EMBED_CHARS], True
    return txt, False


def find_output_file(output_id: str, kind: str):
    """Locate a per-table artifact by output id across the known layouts.

    kind: 'tfl' (rendered display), 'ard' (numbers), 'code' (program).
    Returns (Path, embed_as) where embed_as is 'html'|'png'|'csv'|'md'|'json'|'r'.
    """
    ids = _candidate_ids(output_id)
    if kind == "tfl":
        for i in ids:
            for ext, tag in (("html", "html"), ("png", "png"), ("md", "md")):
                p = WORKSPACE / "tfl" / f"{i}.{ext}"
                if p.is_file():
                    return p, tag
            # protocol-to-tfl nested layout
            for name, tag in ((f"{i}.generated.md", "md"), ("generated.md", "md")):
                p = WORKSPACE / "tfl" / i / name
                if p.is_file():
                    return p, tag
    elif kind == "ard":
        for i in ids:
            for ext, tag in (("csv", "csv"), ("json", "json")):
                p = WORKSPACE / "ard" / f"{i}.{ext}"
                if p.is_file():
                    return p, tag
            p = WORKSPACE / "tfl" / i / "ard.json"
            if p.is_file():
                return p, "json"
    elif kind == "code":
        for i in ids:
            p = WORKSPACE / "code" / f"{i}.R"
            if p.is_file():
                return p, "r"
            p = WORKSPACE / "tfl" / i / "generate.R"
            if p.is_file():
                return p, "r"
    return None, None


def _candidate_ids(output_id: str):
    """A small ordered candidate list of on-disk ids for one logical output."""
    seen, out = set(), []
    for cand in (output_id, _sanitize(output_id), output_id.replace(".", "-"),
                 output_id.replace("_", "-")):
        if cand and cand not in seen:
            seen.add(cand)
            out.append(cand)
    return out


def _sanitize(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "-", str(s or ""))


# --------------------------------------------------------------------------- #
# small field-access helpers (tolerant to key aliases the LLM steps may emit)
# --------------------------------------------------------------------------- #
def first(d: dict, *keys, default=None):
    for k in keys:
        if isinstance(d, dict) and d.get(k) not in (None, "", [], {}):
            return d[k]
    return default


def as_list(v):
    if v is None:
        return []
    if isinstance(v, list):
        return v
    return [v]


def truncate(s, n=48):
    s = " ".join(str(s or "").split())
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


# --------------------------------------------------------------------------- #
# artifact normalisation
# --------------------------------------------------------------------------- #
def norm_study_model(sm: dict):
    """-> (study{}, objectives[{id,level,text,description,endpoint_ids}],
            endpoints{ id: {id,level,text,objective,resolved,measure,
                            measure_type,timepoints,domain_hint} },
            unresolved_ids set)."""
    sm = sm or {}
    study = first(sm, "study", default={}) or {}
    if not isinstance(study, dict):
        study = {"name": str(study)}
    study = {
        "id": first(study, "id", "studyId", default=first(sm, "study_id", "id", default="")),
        "name": first(study, "name", default=first(sm, "study", "name", default="")),
        "title": first(study, "title", default=first(sm, "title", default="")),
        "phase": first(study, "phase", default=first(sm, "phase", default="")),
    }
    if not study["name"] and isinstance(sm.get("study"), str):
        study["name"] = sm["study"]

    endpoints: dict[str, dict] = {}
    objectives: list[dict] = []

    def add_endpoint(ep: dict, objective_id):
        eid = str(first(ep, "id", "endpoint_id", "endpointId", default=""))
        if not eid:
            eid = f"Endpoint_{len(endpoints) + 1}"
        resolved = ep.get("resolved")
        rec = endpoints.setdefault(eid, {})
        rec.update({
            "id": eid,
            "level": first(ep, "level", default=rec.get("level", "")),
            "text": first(ep, "text", "description", "label", default=rec.get("text", "")),
            "objective": objective_id or rec.get("objective"),
            "resolved": rec.get("resolved") if resolved is None else bool(resolved),
            "measure": first(ep, "measure", default=rec.get("measure", "")),
            "measure_type": first(ep, "measure_type", "measureType", default=rec.get("measure_type", "")),
            "timepoints": as_list(first(ep, "timepoints", "timepoint", default=rec.get("timepoints", []))),
            "domain_hint": first(ep, "domain_hint", "domainHint", default=rec.get("domain_hint", "")),
            "parsed": first(ep, "parsed", default=rec.get("parsed", {})),
        })
        if rec["resolved"] is None:
            rec["resolved"] = True
        return eid

    raw_objs = as_list(first(sm, "objectives", default=[]))
    for obj in raw_objs:
        if not isinstance(obj, dict):
            continue
        oid = str(first(obj, "id", "objective_id", "objectiveId", default=f"Objective_{len(objectives) + 1}"))
        ep_ids = []
        for ep in as_list(first(obj, "endpoints", default=[])):
            if isinstance(ep, dict):
                ep_ids.append(add_endpoint(ep, oid))
            elif isinstance(ep, str):
                ep_ids.append(ep)
        for ref in as_list(first(obj, "endpoint_ids", "endpointIds", default=[])):
            if ref not in ep_ids:
                ep_ids.append(str(ref))
        objectives.append({
            "id": oid,
            "level": first(obj, "level", default=""),
            "text": first(obj, "text", "description", "label", default=""),
            "description": first(obj, "description", "text", default=""),
            "endpoint_ids": ep_ids,
        })

    # top-level endpoints[] (not nested under objectives)
    for ep in as_list(first(sm, "endpoints", default=[])):
        if isinstance(ep, dict):
            oid = first(ep, "objective", "objective_id", "objectiveId")
            add_endpoint(ep, oid)

    # unresolved endpoints (ids or objects)
    unresolved = set()
    for u in as_list(first(sm, "unresolved_endpoints", "unresolvedEndpoints", default=[])):
        uid = str(first(u, "id", default=u) if isinstance(u, dict) else u)
        unresolved.add(uid)
        if uid in endpoints:
            endpoints[uid]["resolved"] = False
    for eid, ep in endpoints.items():
        if ep.get("resolved") is False:
            unresolved.add(eid)

    # link endpoints back to objectives when only the objective declared them
    for obj in objectives:
        for eid in obj["endpoint_ids"]:
            endpoints.setdefault(eid, {"id": eid, "resolved": True, "text": "", "level": "",
                                       "objective": obj["id"], "timepoints": []})
            if not endpoints[eid].get("objective"):
                endpoints[eid]["objective"] = obj["id"]

    return study, objectives, endpoints, unresolved


def norm_tlf_plan(plan):
    """-> list of TLF dicts with a stable candidate id + traces_to + status."""
    if isinstance(plan, dict):
        items = None
        for k in ("tlfs", "candidates", "outputs", "plan", "tables", "items"):
            if isinstance(plan.get(k), list):
                items = plan[k]
                break
        if items is None:
            items = [v for v in plan.values() if isinstance(v, dict)]
    elif isinstance(plan, list):
        items = plan
    else:
        items = []

    tlfs = []
    for i, t in enumerate(items):
        if not isinstance(t, dict):
            continue
        candidate_id = str(first(t, "candidate_id", "candidateId", "id", "final_id", "finalId",
                                 default=f"tlf-{i + 1}"))
        traces = first(t, "traces_to", "tracesTo", default={}) or {}
        dr = first(t, "data_requirements", "dataRequirements", default={}) or {}
        tlfs.append({
            "candidate_id": candidate_id,
            "final_id": first(t, "final_id", "finalId", "number", default=""),
            "title": first(t, "title", "name", "label", default=""),
            "type": first(t, "type", default=""),
            "category": first(t, "category", default=""),
            "cat_label": first(t, "cat_label", "categoryLabel", "category", default=""),
            "status": (first(t, "status", default="generated") or "generated").lower(),
            "status_reason": first(t, "status_reason", "statusReason", default=""),
            "priority": first(t, "priority", default=""),
            "objective_ids": [str(x) for x in as_list(first(traces, "objective_ids", "objectiveIds", default=[]))],
            "endpoint_ids": [str(x) for x in as_list(first(traces, "endpoint_ids", "endpointIds", default=[]))],
            "regulatory_rule": first(traces, "regulatory_rule", "regulatoryRule",
                                     default=first(t, "regulatory_rule", default="")),
            "req_adam": [str(x) for x in as_list(first(dr, "adam", "adam_datasets", "datasets", default=[]))],
            "req_sdtm": [str(x) for x in as_list(first(dr, "sdtm", "sdtm_domains", "domains", default=[]))],
        })
    return tlfs


def norm_analysis_spec(spec):
    """-> dict keyed by output id -> {method, analysisSet, analysisSetCond,
       dataSubset, purpose}."""
    out = {}
    if isinstance(spec, dict):
        items = None
        for k in ("analyses", "specs", "tlfs", "outputs", "items"):
            if isinstance(spec.get(k), list):
                items = spec[k]
                break
        if items is None:
            items = [v for v in spec.values() if isinstance(v, dict)]
    elif isinstance(spec, list):
        items = spec
    else:
        items = []
    for a in items:
        if not isinstance(a, dict):
            continue
        key = str(first(a, "final_id", "finalId", "candidate_id", "candidateId", "id",
                        "output_id", "outputId", default=""))
        if not key:
            continue
        ds = first(a, "dataSubset", "data_subset", "dataset", default="")
        if isinstance(ds, dict):
            ds = first(ds, "dataset", "id", "name", default="")
        aset = first(a, "analysisSet", "analysis_set", "population", default="")
        aset_cond = ""
        if isinstance(aset, dict):
            aset_cond = first(aset, "condition", "where", default="")
            aset = first(aset, "id", "name", "label", default="")
        out[key] = {
            "method": _method_label(first(a, "method", default="")),
            "analysisSet": aset,
            "analysisSetCond": aset_cond,
            "dataSubset": ds,
            "purpose": first(a, "purpose", "description", default=""),
        }
    return out


def _method_label(m):
    if isinstance(m, dict):
        return first(m, "label", "name", "id", "type", default="")
    return str(m or "")


def norm_adam_spec(spec):
    """-> list of dataset dicts {name, klass, sdtm_source[], used_by_tables[],
       derivation_requirements[], parameters[], variables[]}."""
    if isinstance(spec, dict):
        datasets = spec.get("datasets")
        if not isinstance(datasets, list):
            datasets = [v for v in spec.values() if isinstance(v, dict) and
                        (v.get("name") or v.get("dataset"))]
    elif isinstance(spec, list):
        datasets = spec
    else:
        datasets = []

    out = []
    for d in datasets or []:
        if not isinstance(d, dict):
            continue
        name = str(first(d, "name", "dataset", "id", default="")).upper()
        if not name:
            continue
        sdtm_source = [str(x).upper() for x in as_list(first(d, "sdtm_source", "sdtmSource",
                                                             "sdtm", "sources", default=[]))]
        variables = []
        for v in as_list(first(d, "variables", default=[])):
            if isinstance(v, dict):
                role = first(v, "role", "derivation", "label", "origin", default="")
                srcs = [str(x).upper() for x in as_list(first(v, "source_domains", "sourceDomains", default=[]))]
                if not srcs:
                    srcs = _infer_domains(role, sdtm_source)
                variables.append({"name": first(v, "name", "variable", default=""),
                                  "role": role, "source_domains": srcs})
            elif isinstance(v, str):
                variables.append({"name": v, "role": "", "source_domains": sdtm_source[:1] or ["*"]})
        parameters = []
        for p in as_list(first(d, "parameters", "params", default=[])):
            if isinstance(p, dict):
                parameters.append({"paramcd": first(p, "paramcd", "PARAMCD", "code", default=""),
                                   "param": first(p, "param", "PARAM", "label", default=""),
                                   "note": first(p, "note", "comment", default="")})
            elif isinstance(p, str):
                parameters.append({"paramcd": p, "param": "", "note": ""})
        out.append({
            "name": name,
            "klass": first(d, "klass", "class", "structure", default=""),
            "sdtm_source": sdtm_source,
            "used_by_tables": [str(x) for x in as_list(first(d, "used_by_tables", "usedByTables",
                                                            "used_by", default=[]))],
            "derivation_requirements": [str(x) for x in as_list(
                first(d, "derivation_requirements", "derivationRequirements",
                      "derivations", default=[]))],
            "parameters": parameters,
            "variables": variables,
        })
    return out


def _infer_domains(role_text, sdtm_source):
    """Best-effort: which of the dataset's SDTM sources this variable draws from."""
    hits = [dom for dom in sdtm_source if dom and re.search(rf"\b{re.escape(dom)}\b", role_text or "", re.I)]
    return hits or (sdtm_source[:] if sdtm_source else ["*"])


# --------------------------------------------------------------------------- #
# graph assembly
# --------------------------------------------------------------------------- #
def endpoint_sublabel(ep):
    measure = ep.get("measure") or (ep.get("parsed") or {}).get("measure")
    tps = ep.get("timepoints") or (ep.get("parsed") or {}).get("timepoints") or []
    tps_short = "/".join(_short_tp(t) for t in tps if t)
    if measure:
        return f"{measure} · {tps_short}" if tps_short else str(measure)
    if ep.get("text"):
        return truncate(ep["text"], 44)
    return ep.get("level") or "Endpoint"


def _short_tp(t):
    s = str(t)
    m = re.search(r"(\d+)", s)
    if "week" in s.lower() or re.match(r"\s*wk", s.lower()):
        return f"Wk{m.group(1)}" if m else s
    return truncate(s, 12)


def objective_sublabel(obj, endpoints):
    if obj.get("text"):
        clause = re.split(r"[.;:]", obj["text"])[0]
        return truncate(clause, 52)
    measures = []
    for eid in obj.get("endpoint_ids", []):
        m = (endpoints.get(eid) or {}).get("measure")
        if m and m not in measures:
            measures.append(m)
    if measures:
        return truncate(" & ".join(measures), 52)
    return obj.get("level") or "Objective"


def assemble(study, objectives, endpoints, unresolved, tlfs, analysis, adam):
    nodes, edges = [], []
    node_ids = set()

    def add_node(node):
        if node["id"] not in node_ids:
            node_ids.add(node["id"])
            nodes.append(node)

    def add_edge(src, tgt, kind, dashed=False, rule=None):
        if src in node_ids and tgt in node_ids:
            edges.append({"source": src, "target": tgt, "kind": kind,
                          "dashed": dashed, "rule": rule})

    # --- Objectives (tier 0)
    for obj in objectives:
        add_node({
            "id": f"obj:{obj['id']}", "type": "Objective", "tier": 0,
            "label": _code(obj["id"], "OBJ"), "sublabel": objective_sublabel(obj, endpoints),
            "title": obj.get("text") or obj.get("description") or obj["id"],
            "meta": {"level": obj.get("level", ""), "description": obj.get("description", ""),
                     "text": obj.get("text", ""), "endpoints": [f"end:{e}" for e in obj["endpoint_ids"]]},
        })

    # --- Endpoints (tier 1)
    for eid, ep in endpoints.items():
        resolved = ep.get("resolved", True)
        add_node({
            "id": f"end:{eid}", "type": "Endpoint", "tier": 1,
            "label": _code(eid, "END"), "sublabel": endpoint_sublabel(ep),
            "title": ep.get("text") or eid, "unresolved": (not resolved) or (eid in unresolved),
            "meta": {"level": ep.get("level", ""), "text": ep.get("text", ""),
                     "objective": f"obj:{ep['objective']}" if ep.get("objective") else None,
                     "resolved": bool(resolved), "measure": ep.get("measure", ""),
                     "measure_type": ep.get("measure_type", ""), "timepoints": ep.get("timepoints", []),
                     "domain_hint": ep.get("domain_hint", "")},
        })
    for obj in objectives:
        for eid in obj["endpoint_ids"]:
            add_edge(f"obj:{obj['id']}", f"end:{eid}", "obj-end")

    # --- Regulatory (single shared node, tier 1) if any TLF cites a rule
    has_reg = any(t["regulatory_rule"] for t in tlfs)
    if has_reg:
        add_node({
            "id": "reg:ICH-E3", "type": "Regulatory", "tier": 1,
            "label": "ICH E3", "sublabel": "ICH E3",
            "title": "ICH E3 regulatory scaffolding",
            "meta": {"standard": "ICH E3", "note": "Regulatory scaffolding outputs (structure of the CSR)."},
        })

    # --- ADaM (tier 3) + SDTM (tier 4)
    sdtm_seen = {}

    def ensure_sdtm(domain, absent=False):
        domain = str(domain).upper()
        nid = f"sdtm:{domain}"
        if nid not in node_ids:
            add_node({"id": nid, "type": "SDTM", "tier": 4, "label": domain,
                      "sublabel": SDTM_LABELS.get(domain, domain), "title": SDTM_LABELS.get(domain, domain),
                      "absent": absent, "meta": {"domain": domain, "label": SDTM_LABELS.get(domain, domain),
                                                 "absent": absent}})
            sdtm_seen[domain] = absent
        elif not absent:
            # a real derivation source clears any earlier 'absent' provisional mark
            for n in nodes:
                if n["id"] == nid:
                    n["absent"] = False
                    n["meta"]["absent"] = False
            sdtm_seen[domain] = False
        return nid

    adam_by_name = {}
    for d in adam:
        nid = f"adam:{d['name']}"
        adam_by_name[d["name"]] = d
        add_node({
            "id": nid, "type": "ADaM", "tier": 3, "label": d["name"],
            "sublabel": d.get("klass") or d["name"], "title": f"{d['name']} ({d.get('klass') or 'ADaM'})",
            "meta": {"klass": d.get("klass", ""), "sdtm_source": d["sdtm_source"],
                     "used_by_tables": d["used_by_tables"],
                     "derivation_requirements": d["derivation_requirements"],
                     "parameters": d["parameters"], "variables": d["variables"]},
        })
        for dom in d["sdtm_source"]:
            ensure_sdtm(dom)
            add_edge(nid, f"sdtm:{dom}", "adam-sdtm")

    # --- TLFs (tier 2)
    counts_status = {"generated": 0, "blocked": 0, "needs-clarification": 0}
    for t in tlfs:
        cid = t["candidate_id"]
        nid = f"tlf:{cid}"
        status = t["status"] if t["status"] in counts_status else "generated"
        counts_status[status] += 1
        spec = analysis.get(str(t["final_id"])) or analysis.get(cid) or {}
        is_figure = "figure" in (t["type"] or "").lower() or "fig" in (t["category"] or "").lower()

        tfl_path, tfl_kind = find_output_file(t["final_id"] or cid, "tfl")
        ard_path, ard_kind = find_output_file(t["final_id"] or cid, "ard")
        code_path, _ = find_output_file(t["final_id"] or cid, "code")
        tfl_html, tfl_trunc = (read_text_capped(tfl_path) if (tfl_path and tfl_kind in ("html", "md")) else (None, False))
        tfl_png = _data_uri(tfl_path) if (tfl_path and tfl_kind == "png") else None
        ard_text, ard_trunc = (read_text_capped(ard_path) if ard_path else (None, False))
        code_text, code_trunc = (read_text_capped(code_path) if code_path else (None, False))
        if tfl_path is not None and status == "generated":
            pass  # rendered exists, keep generated
        add_node({
            "id": nid, "type": "TLF", "tier": 2,
            "label": _code(t["final_id"] or cid, "T"),
            "sublabel": truncate(t["title"] or t["cat_label"] or t["type"] or cid, 50),
            "title": t["title"] or cid, "status": status,
            "isFigure": is_figure,
            "meta": {
                "candidate_id": cid, "final_id": t["final_id"], "type": t["type"],
                "category": t["category"], "cat_label": t["cat_label"], "title": t["title"],
                "status": status, "status_reason": t["status_reason"], "priority": t["priority"],
                "objectives": [f"obj:{o}" for o in t["objective_ids"]],
                "endpoints": [f"end:{e}" for e in t["endpoint_ids"]],
                "regulatory_rule": t["regulatory_rule"],
                "method": spec.get("method", ""), "population": spec.get("analysisSet", ""),
                "analysisSet": spec.get("analysisSet", ""), "analysisSetCond": spec.get("analysisSetCond", ""),
                "dataSubset": spec.get("dataSubset", ""), "purpose": spec.get("purpose", ""),
                "rendered": tfl_path is not None,
                "tflHtml": tfl_html, "tflPng": tfl_png, "tflKind": tfl_kind,
                "ardText": ard_text, "ardKind": ard_kind, "generateR": code_text,
                "truncated": bool(tfl_trunc or ard_trunc or code_trunc),
            },
        })
        # endpoint / objective / regulatory -> TLF. Prefer the endpoint bridge;
        # only wire objective -> TLF directly when the TLF names no endpoint, so
        # the tier flow (obj -> end -> tlf) stays a legible near-DAG.
        for e in t["endpoint_ids"]:
            add_edge(f"end:{e}", nid, "end-tlf")
        if not t["endpoint_ids"]:
            for o in t["objective_ids"]:
                add_edge(f"obj:{o}", nid, "obj-tlf")
        if t["regulatory_rule"] and has_reg:
            add_edge("reg:ICH-E3", nid, "reg-tlf", rule=t["regulatory_rule"])

        # TLF -> ADaM (authoritative: adam-spec used_by_tables; fallback data_requirements)
        bridged_domains = set()
        linked_adam = False
        for d in adam:
            if _id_in(t, d["used_by_tables"]):
                add_edge(nid, f"adam:{d['name']}", "tlf-adam")
                linked_adam = True
                bridged_domains.update(d["sdtm_source"])
        if not linked_adam:
            for ds in t["req_adam"]:
                ds = ds.upper()
                if ds in adam_by_name:
                    add_edge(nid, f"adam:{ds}", "tlf-adam")
                    bridged_domains.update(adam_by_name[ds]["sdtm_source"])
        # declared-but-not-derived SDTM -> dashed tlf-sdtm
        for dom in t["req_sdtm"]:
            dom = dom.upper()
            if dom not in bridged_domains:
                ensure_sdtm(dom, absent=(dom not in sdtm_seen))
                add_edge(nid, f"sdtm:{dom}", "tlf-sdtm", dashed=True)

    issues = build_issues(objectives, endpoints, unresolved, tlfs, nodes, node_ids)

    graph = {
        "study": study,
        "counts": {
            "objectives": len(objectives),
            "endpoints": len(endpoints),
            "endpoints_unresolved": len(unresolved),
            "sdtm": sum(1 for n in nodes if n["type"] == "SDTM"),
            "sdtm_absent": sum(1 for n in nodes if n["type"] == "SDTM" and n.get("absent")),
            "adam": len(adam),
            "tlf": len(tlfs),
            "tlf_producible": counts_status["generated"],
        },
        "status": counts_status,
        "issues": issues,
        "nodes": nodes,
        "edges": edges,
    }
    return graph


def _id_in(tlf, used_by):
    """Does this TLF's final_id / candidate_id appear in a used_by_tables list?"""
    keys = {str(tlf["final_id"]), tlf["candidate_id"], _sanitize(tlf["final_id"] or ""),
            _sanitize(tlf["candidate_id"])}
    keys.discard("")
    for u in used_by:
        us = str(u)
        if us in keys or _sanitize(us) in keys:
            return True
    return False


def _code(raw, prefix):
    raw = str(raw or "")
    m = re.search(r"(\d+[\d._-]*\d|\d+)", raw)
    if m and prefix in ("OBJ", "END"):
        return f"{prefix}{m.group(1).lstrip('0') or m.group(1)}"
    if prefix == "T":
        m2 = re.search(r"(\d[\d._-]*\d|\d+)", raw)
        return f"T-{m2.group(1)}" if m2 else truncate(raw, 12)
    return truncate(raw, 12) or prefix


def _data_uri(path: Path):
    import base64
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    if len(raw) > MAX_EMBED_CHARS:  # keep the page openable
        return None
    return "data:image/png;base64," + base64.b64encode(raw).decode("ascii")


def build_issues(objectives, endpoints, unresolved, tlfs, nodes, node_ids):
    issues = []
    # blocked / needs-clarification TLFs
    for t in tlfs:
        nid = f"tlf:{t['candidate_id']}"
        if nid not in node_ids:
            continue
        if t["status"] == "blocked":
            related = [f"sdtm:{d.upper()}" for d in t["req_sdtm"] if f"sdtm:{d.upper()}" in node_ids]
            issues.append({"severity": "blocked",
                           "message": t["status_reason"] or f"{t['title'] or t['candidate_id']} is blocked.",
                           "nodeId": nid, "relatedNodeIds": related})
        elif t["status"] == "needs-clarification":
            issues.append({"severity": "clarification",
                           "message": t["status_reason"] or f"{t['title'] or t['candidate_id']} needs clarification.",
                           "nodeId": nid, "relatedNodeIds": []})
    # unresolved endpoints
    for eid in unresolved:
        nid = f"end:{eid}"
        if nid in node_ids:
            ep = endpoints.get(eid, {})
            issues.append({"severity": "clarification",
                           "message": f"Endpoint {eid} is unresolved: {truncate(ep.get('text', ''), 80) or 'no resolved measure'}.",
                           "nodeId": nid, "relatedNodeIds": []})
    # absent SDTM domains
    for n in nodes:
        if n["type"] == "SDTM" and n.get("absent"):
            blocks = [f"tlf:{t['candidate_id']}" for t in tlfs
                      if n["meta"]["domain"] in [d.upper() for d in t["req_sdtm"]]
                      and f"tlf:{t['candidate_id']}" in node_ids]
            issues.append({"severity": "blocked",
                           "message": f"Domain {n['meta']['domain']} is absent from the SDTM inventory"
                                      + (f"; blocks {len(blocks)} output(s)." if blocks else "."),
                           "nodeId": n["id"], "relatedNodeIds": blocks})
    # coverage gaps: objective / resolved endpoint with no downstream TLF
    tlf_endpoints = {e for t in tlfs for e in t["endpoint_ids"]}
    tlf_objectives = {o for t in tlfs for o in t["objective_ids"]}
    for obj in objectives:
        reaches = obj["id"] in tlf_objectives or any(e in tlf_endpoints for e in obj["endpoint_ids"])
        if not reaches and f"obj:{obj['id']}" in node_ids:
            issues.append({"severity": "gap",
                           "message": f"Objective {obj['id']} ({truncate(obj.get('text', ''), 60)}) has no downstream TLF.",
                           "nodeId": f"obj:{obj['id']}", "relatedNodeIds": []})
    for eid, ep in endpoints.items():
        if ep.get("resolved", True) and eid not in unresolved and eid not in tlf_endpoints \
                and f"end:{eid}" in node_ids:
            issues.append({"severity": "gap",
                           "message": f"Endpoint {eid} ({truncate(ep.get('text', ''), 60)}) has no downstream TLF.",
                           "nodeId": f"end:{eid}", "relatedNodeIds": []})
    # optional issues.md
    for base in (WORKSPACE, OUTPUT):
        p = base / "issues.md"
        if p.is_file():
            for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
                line = line.strip().lstrip("-*# ").strip()
                if line:
                    issues.append({"severity": "info", "message": line, "nodeId": None, "relatedNodeIds": []})
            break
    return issues


# A tiny label table so common CDISC SDTM domains read meaningfully; unknown
# domains fall back to the code itself (no external lookup, offline-safe).
SDTM_LABELS = {
    "DM": "Demographics", "AE": "Adverse Events", "CM": "Concomitant Meds",
    "EX": "Exposure", "VS": "Vital Signs", "LB": "Laboratory", "QS": "Questionnaires",
    "SV": "Subject Visits", "DS": "Disposition", "MH": "Medical History",
    "SC": "Subject Characteristics", "SUPPDM": "Suppl. Demographics",
    "DV": "Protocol Deviations", "EG": "ECG", "PC": "Pharmacokinetics",
    "RELREC": "Related Records", "TA": "Trial Arms", "TE": "Trial Elements",
}


# --------------------------------------------------------------------------- #
# HTML rendering
# --------------------------------------------------------------------------- #
def render_html(graph: dict) -> str:
    payload = json.dumps(graph, ensure_ascii=False, separators=(",", ":"))
    payload = payload.replace("</", "<\\/")  # never let embedded content close the <script>
    study_name = graph["study"].get("name") or graph["study"].get("id") or "Study"
    title = f"Traceability Explorer — {study_name}"
    return HTML_TEMPLATE.replace("__TITLE__", _esc(title)).replace("__GRAPH_JSON__", payload)


def _esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


HTML_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
  :root{
    --bg:#f7f8fa; --panel:#ffffff; --ink:#111827; --muted:#6b7280; --line:#e5e7eb;
    --chip:#f3f4f6; --shadow:0 1px 3px rgba(0,0,0,.12),0 1px 2px rgba(0,0,0,.06);
    --t-obj:#2a78d6; --t-end:#1baf7a; --t-tlf:#eda100; --t-adam:#008300; --t-sdtm:#4a3aa7; --t-reg:#64748b;
    --s-generated:#1a7f37; --s-blocked:#b42318; --s-clarify:#b54708; --s-gap:#6941c6;
    --dim:.14;
  }
  :root[data-theme="dark"], :root:not([data-theme="light"]) {}
  @media (prefers-color-scheme: dark){
    :root:not([data-theme="light"]){
      --bg:#0e1116; --panel:#161b22; --ink:#e6edf3; --muted:#9aa4b2; --line:#2a3038;
      --chip:#1f262e; --shadow:0 1px 3px rgba(0,0,0,.5);
      --t-obj:#3987e5; --t-end:#199e70; --t-tlf:#e0a836; --t-adam:#3ca63c; --t-sdtm:#9085e9; --t-reg:#8b98ad;
      --s-generated:#3fb950; --s-blocked:#f85149; --s-clarify:#d29922; --s-gap:#a78bfa;
    }
  }
  :root[data-theme="dark"]{
    --bg:#0e1116; --panel:#161b22; --ink:#e6edf3; --muted:#9aa4b2; --line:#2a3038;
    --chip:#1f262e; --shadow:0 1px 3px rgba(0,0,0,.5);
    --t-obj:#3987e5; --t-end:#199e70; --t-tlf:#e0a836; --t-adam:#3ca63c; --t-sdtm:#9085e9; --t-reg:#8b98ad;
    --s-generated:#3fb950; --s-blocked:#f85149; --s-clarify:#d29922; --s-gap:#a78bfa;
  }
  *{box-sizing:border-box}
  html,body{margin:0;height:100%;background:var(--bg);color:var(--ink);
    font-family:system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;font-size:14px}
  .mono{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
  header{display:flex;align-items:center;gap:12px;padding:10px 14px;border-bottom:1px solid var(--line);
    background:var(--panel);position:sticky;top:0;z-index:5;flex-wrap:wrap}
  header h1{font-size:15px;margin:0;font-weight:650;white-space:nowrap}
  header .study{color:var(--muted);font-size:12px}
  .counts{display:flex;gap:6px;flex-wrap:wrap;margin-left:auto}
  .pill{font-size:11px;padding:3px 8px;border-radius:999px;background:var(--chip);border:1px solid var(--line);white-space:nowrap}
  .pill b{font-weight:700}
  #search{padding:6px 9px;border:1px solid var(--line);border-radius:7px;background:var(--panel);color:var(--ink);min-width:150px}
  button{font:inherit;cursor:pointer;border:1px solid var(--line);background:var(--panel);color:var(--ink);
    border-radius:7px;padding:6px 9px}
  button:hover{background:var(--chip)}
  .layout{display:flex;height:calc(100vh - 49px)}
  .stage{position:relative;flex:1;overflow:hidden;background:
    radial-gradient(circle at 1px 1px, var(--line) 1px, transparent 0) 0 0/22px 22px}
  svg{width:100%;height:100%;display:block;cursor:grab}
  svg.grabbing{cursor:grabbing}
  .legend{position:absolute;left:12px;bottom:12px;display:flex;gap:6px;flex-wrap:wrap;max-width:60%}
  .chip{display:inline-flex;align-items:center;gap:6px;font-size:11px;padding:4px 8px;border-radius:999px;
    background:var(--panel);border:1px solid var(--line);cursor:pointer;user-select:none;box-shadow:var(--shadow)}
  .chip .sw{width:10px;height:10px;border-radius:3px}
  .chip.off{opacity:.4}
  .toolbar{position:absolute;right:12px;bottom:12px;display:flex;gap:6px}
  aside{width:390px;max-width:44vw;border-left:1px solid var(--line);background:var(--panel);
    display:flex;flex-direction:column;overflow:hidden}
  .tabs{display:flex;border-bottom:1px solid var(--line)}
  .tabs button{border:0;border-radius:0;border-bottom:2px solid transparent;flex:1;padding:9px}
  .tabs button.active{border-bottom-color:var(--t-obj);font-weight:650}
  .panel{padding:14px;overflow:auto;flex:1}
  .panel h2{font-size:14px;margin:0 0 2px}
  .panel .sub{color:var(--muted);font-size:12px;margin-bottom:10px}
  .kv{display:grid;grid-template-columns:auto 1fr;gap:3px 10px;font-size:12.5px;margin:8px 0}
  .kv .k{color:var(--muted)}
  .badge{display:inline-flex;align-items:center;gap:5px;font-size:11px;padding:2px 8px;border-radius:999px;
    border:1px solid var(--line);font-weight:600}
  .breadcrumb{font-size:11.5px;color:var(--muted);margin:6px 0 10px;line-height:1.7}
  .breadcrumb .n{padding:1px 6px;border-radius:5px;background:var(--chip);margin:0 1px;cursor:pointer}
  details{border:1px solid var(--line);border-radius:8px;margin:8px 0;background:var(--bg)}
  summary{cursor:pointer;padding:8px 10px;font-weight:600;font-size:12.5px}
  .scroll{overflow:auto;max-height:340px;border-top:1px solid var(--line)}
  pre{margin:0;padding:10px;font-size:11.5px;white-space:pre;font-family:ui-monospace,Menlo,Consolas,monospace}
  table.tbl{border-collapse:collapse;width:100%;font-size:11.5px}
  table.tbl th,table.tbl td{border:1px solid var(--line);padding:3px 6px;text-align:left;vertical-align:top}
  table.tbl th{background:var(--chip);position:sticky;top:0}
  iframe{width:100%;height:340px;border:1px solid var(--line);border-radius:8px;background:#fff}
  .issues-row{display:flex;gap:8px;align-items:flex-start;padding:8px;border:1px solid var(--line);
    border-radius:8px;margin-bottom:7px;cursor:pointer;font-size:12.5px}
  .issues-row:hover{background:var(--chip)}
  .dot{width:9px;height:9px;border-radius:50%;margin-top:4px;flex:none}
  .empty{color:var(--muted);font-size:12.5px;padding:6px 0}
  .filterbar{display:flex;gap:6px;align-items:center;padding:8px 14px;border-bottom:1px solid var(--line);
    font-size:12px;flex-wrap:wrap}
  .node text{pointer-events:none}
  .node .box{stroke-width:1.4px;rx:9}
  .node.dim{opacity:var(--dim)}
  .edge{fill:none;stroke:var(--muted);stroke-width:1.3px;opacity:.5}
  .edge.dim{opacity:.06}
  .edge.hot{opacity:.95;stroke-width:2.1px}
  .edge.dashed{stroke-dasharray:5 4}
  .warn{font-size:12px}
  @media (prefers-reduced-motion: no-preference){ .node,.edge{transition:opacity .18s} }
</style>
</head>
<body>
<header>
  <h1>Traceability Explorer</h1>
  <span class="study" id="studyName"></span>
  <input id="search" type="search" placeholder="Search id / title…" autocomplete="off">
  <button id="resetView" title="Fit graph to view">Fit</button>
  <button id="themeBtn" title="Toggle light/dark">Theme</button>
  <div class="counts" id="counts"></div>
</header>
<div class="layout">
  <div class="stage">
    <svg id="svg" role="img" aria-label="Traceability graph"></svg>
    <div class="legend" id="legend"></div>
    <div class="toolbar">
      <button id="zoomIn">+</button><button id="zoomOut">−</button>
    </div>
  </div>
  <aside>
    <div class="tabs">
      <button id="tabDetail" class="active">Detail</button>
      <button id="tabIssues">Issues <span id="issueCount" class="badge"></span></button>
    </div>
    <div class="filterbar" id="statusFilter"></div>
    <div class="panel" id="detailPanel"><div class="empty">Click any node to inspect its lineage and details.</div></div>
    <div class="panel" id="issuesPanel" style="display:none"></div>
  </aside>
</div>

<script id="graph-data" type="application/json">__GRAPH_JSON__</script>
<script>
"use strict";
const G = JSON.parse(document.getElementById('graph-data').textContent);
const SVGNS = "http://www.w3.org/2000/svg";
const TYPES = ["Objective","Endpoint","Regulatory","TLF","ADaM","SDTM"];
const TYPE_VAR = {Objective:"--t-obj",Endpoint:"--t-end",Regulatory:"--t-reg",TLF:"--t-tlf",ADaM:"--t-adam",SDTM:"--t-sdtm"};
const STATUS_ICON = {generated:"✅",blocked:"⛔",'needs-clarification':"❓"};
const SEV = {blocked:"--s-blocked",clarification:"--s-clarify",gap:"--s-gap",info:"--muted"};
const cssv = v => getComputedStyle(document.documentElement).getPropertyValue(v).trim();

const byId = {}; G.nodes.forEach(n=>byId[n.id]=n);
const outE={}, inE={};
G.edges.forEach(e=>{ (outE[e.source]=outE[e.source]||[]).push(e); (inE[e.target]=inE[e.target]||[]).push(e); });

/* ---- layout: layered columns by tier ---- */
const COLW=250, NODEW=168, NODEH=52, VGAP=20, MX=90, MY=40;
const tiers={}; G.nodes.forEach(n=>{(tiers[n.tier]=tiers[n.tier]||[]).push(n);});
const tierKeys=Object.keys(tiers).map(Number).sort((a,b)=>a-b);
let maxH=0;
tierKeys.forEach(t=>{ const h=tiers[t].length*(NODEH+VGAP); if(h>maxH)maxH=h; });
tierKeys.forEach(t=>{
  const col=tiers[t]; col.sort((a,b)=>(a.type+a.label).localeCompare(b.type+b.label));
  const h=col.length*(NODEH+VGAP); const y0=MY+(maxH-h)/2;
  col.forEach((n,i)=>{ n.x=MX+t*COLW; n.y=y0+i*(NODEH+VGAP); });
});
const worldW=MX*2+(tierKeys.length-1)*COLW+NODEW;
const worldH=MY*2+maxH;

/* ---- svg scaffold ---- */
const svg=document.getElementById('svg');
const root=document.createElementNS(SVGNS,'g'); svg.appendChild(root);
const edgeLayer=document.createElementNS(SVGNS,'g'); root.appendChild(edgeLayer);
const nodeLayer=document.createElementNS(SVGNS,'g'); root.appendChild(nodeLayer);
let view={x:0,y:0,k:1};
function applyView(){ root.setAttribute('transform',`translate(${view.x},${view.y}) scale(${view.k})`); }
function fit(){
  const r=svg.getBoundingClientRect();
  const k=Math.min(r.width/worldW, r.height/worldH, 1.15)*0.94;
  view.k=k; view.x=(r.width-worldW*k)/2; view.y=(r.height-worldH*k)/2; applyView();
}

const edgeEls=[], nodeEls={};
function edgePath(e){
  const s=byId[e.source], t=byId[e.target]; if(!s||!t) return "";
  const x1=s.x+NODEW, y1=s.y+NODEH/2, x2=t.x, y2=t.y+NODEH/2, mx=(x1+x2)/2;
  return `M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}`;
}
G.edges.forEach(e=>{
  const p=document.createElementNS(SVGNS,'path');
  p.setAttribute('class','edge'+(e.dashed?' dashed':'')); p.setAttribute('d',edgePath(e));
  p._e=e; edgeLayer.appendChild(p); edgeEls.push(p);
});
G.nodes.forEach(n=>{
  const g=document.createElementNS(SVGNS,'g'); g.setAttribute('class','node');
  g.setAttribute('transform',`translate(${n.x},${n.y})`);
  const color=cssv(TYPE_VAR[n.type]);
  const box=document.createElementNS(SVGNS,'rect');
  box.setAttribute('class','box'); box.setAttribute('width',NODEW); box.setAttribute('height',NODEH);
  box.setAttribute('rx',9); box.setAttribute('fill','var(--panel)'); box.setAttribute('stroke',color);
  if(n.absent||n.unresolved) box.setAttribute('stroke-dasharray','5 4');
  g.appendChild(box);
  const rail=document.createElementNS(SVGNS,'rect');
  rail.setAttribute('width',5); rail.setAttribute('height',NODEH); rail.setAttribute('rx',2.5);
  rail.setAttribute('fill',color); g.appendChild(rail);
  const chip=document.createElementNS(SVGNS,'text'); chip.setAttribute('x',14); chip.setAttribute('y',20);
  chip.setAttribute('class','mono'); chip.setAttribute('font-size','11'); chip.setAttribute('font-weight','700');
  chip.setAttribute('fill',color); chip.textContent=n.label||n.id; g.appendChild(chip);
  const sub=document.createElementNS(SVGNS,'text'); sub.setAttribute('x',14); sub.setAttribute('y',38);
  sub.setAttribute('font-size','11.5'); sub.setAttribute('fill','var(--ink)');
  sub.textContent=clip(n.sublabel||"",24); g.appendChild(sub);
  if(n.type==='TLF'&&n.status&&STATUS_ICON[n.status]){
    const st=document.createElementNS(SVGNS,'text'); st.setAttribute('x',NODEW-8); st.setAttribute('y',20);
    st.setAttribute('text-anchor','end'); st.setAttribute('font-size','12'); st.textContent=STATUS_ICON[n.status];
    g.appendChild(st);
  }
  const tip=document.createElementNS(SVGNS,'title'); tip.textContent=(n.title||n.sublabel||n.label||'')+(n.type?` [${n.type}]`:''); g.appendChild(tip);
  g._n=n; nodeLayer.appendChild(g); nodeEls[n.id]=g;
  g.addEventListener('click',ev=>{ ev.stopPropagation(); select(n.id); });
  enableDrag(g,n);
});

/* warning markers from the issues feed (data-derived, never hard-coded) */
const issueByNode={};
G.issues.forEach(is=>{ if(is.nodeId) (issueByNode[is.nodeId]=issueByNode[is.nodeId]||[]).push(is); });
Object.keys(issueByNode).forEach(id=>{
  const g=nodeEls[id]; if(!g)return;
  const m=document.createElementNS(SVGNS,'text'); m.setAttribute('x',NODEW-8); m.setAttribute('y',NODEH-8);
  m.setAttribute('text-anchor','end'); m.setAttribute('font-size','12'); m.setAttribute('class','warn');
  m.textContent="⚠️"; g.appendChild(m);
});

/* ---- lineage highlight (directed: ancestors ∪ descendants ∪ self) ---- */
function lineage(id){
  const anc=new Set(), desc=new Set();
  (function up(x){ (inE[x]||[]).forEach(e=>{ if(!anc.has(e.source)){anc.add(e.source);up(e.source);} }); })(id);
  (function dn(x){ (outE[x]||[]).forEach(e=>{ if(!desc.has(e.target)){desc.add(e.target);dn(e.target);} }); })(id);
  const all=new Set([id,...anc,...desc]); return {all,anc,desc};
}
let selected=null;
function select(id){
  selected=id;
  const {all}=lineage(id);
  G.nodes.forEach(n=>{ nodeEls[n.id].classList.toggle('dim', !all.has(n.id)); });
  edgeEls.forEach(p=>{
    const e=p._e, on=all.has(e.source)&&all.has(e.target);
    p.classList.toggle('hot',on); p.classList.toggle('dim',!on);
  });
  applyStatusFilter(true);
  renderDetail(byId[id]);
  showTab('detail');
}
function clearSelect(){ selected=null; G.nodes.forEach(n=>nodeEls[n.id].classList.remove('dim'));
  edgeEls.forEach(p=>{p.classList.remove('hot');p.classList.remove('dim');}); }
svg.addEventListener('click',clearSelect);

/* ---- detail panel ---- */
const dp=document.getElementById('detailPanel');
function renderDetail(n){
  if(!n){dp.innerHTML='<div class="empty">Nothing selected.</div>';return;}
  const m=n.meta||{}; let h='';
  const color=cssv(TYPE_VAR[n.type]);
  h+=`<h2><span class="mono" style="color:${color}">${esc(n.label)}</span> · ${esc(n.type)}</h2>`;
  h+=`<div class="sub">${esc(n.sublabel||'')}</div>`;
  h+=breadcrumb(n.id);
  if(n.type==='TLF'){
    if(m.status) h+=`<span class="badge" style="border-color:${cssv('--s-'+({generated:'generated',blocked:'blocked','needs-clarification':'clarify'}[m.status]||'generated'))}">${STATUS_ICON[m.status]||''} ${esc(m.status)}</span> `;
    if(n.isFigure) h+=`<span class="badge">Figure</span>`;
    h+=kv({'Title':m.title,'Final id':m.final_id,'Category':m.cat_label||m.category,'Type':m.type,
           'Method':m.method,'Population':m.analysisSet,'Where':m.analysisSetCond,'Data subset':m.dataSubset,
           'Purpose':m.purpose,'Status reason':m.status_reason});
    if(m.tflHtml){ h+=collapse('Rendered output', `<iframe sandbox srcdoc="${esc(m.tflHtml)}"></iframe>`, true); }
    else if(m.tflPng){ h+=collapse('Rendered output', `<div class="scroll"><img style="max-width:100%" src="${m.tflPng}"></div>`, true); }
    if(m.ardText){ h+=collapse('ARD (numbers)', ardBlock(m.ardText,m.ardKind)); }
    if(m.generateR){ h+=collapse('Generation code (R)', `<div class="scroll"><pre>${esc(m.generateR)}</pre></div>`); }
    if(m.truncated) h+=`<div class="empty">⚠️ Some embedded content was truncated to keep the page light.</div>`;
  } else if(n.type==='ADaM'){
    h+=kv({'Class':m.klass,'SDTM source':(m.sdtm_source||[]).join(', '),
           'Used by':(m.used_by_tables||[]).join(', ')});
    if((m.derivation_requirements||[]).length) h+=collapse('Derivation requirements',
        `<div class="scroll"><ul style="margin:8px 14px">${m.derivation_requirements.map(x=>`<li>${esc(x)}</li>`).join('')}</ul></div>`);
    if((m.variables||[]).length) h+=collapse(`Variables (${m.variables.length})`,
        table(['Variable','Role / derivation','Source'], m.variables.map(v=>[v.name, v.role, (v.source_domains||[]).join(', ')])), true);
    if((m.parameters||[]).length) h+=collapse(`Parameters (${m.parameters.length})`,
        table(['PARAMCD','PARAM','Note'], m.parameters.map(p=>[p.paramcd,p.param,p.note])));
  } else if(n.type==='SDTM'){
    h+=kv({'Domain':m.domain,'Label':m.label, 'In inventory': m.absent?'No (absent)':'Yes'});
    const consumers=G.nodes.filter(x=>x.type==='ADaM'&&(x.meta.sdtm_source||[]).includes(m.domain));
    h+=`<div class="sub" style="margin-top:8px">Consumed by</div>`;
    h+= consumers.length? `<div>${consumers.map(c=>`<span class="pill" style="cursor:pointer" onclick="window.__focus('${c.id}')">${esc(c.label)}</span>`).join(' ')}</div>`
       : `<div class="empty">No derived ADaM dataset references this domain.</div>`;
  } else if(n.type==='Endpoint'){
    h+=kv({'Level':m.level,'Measure':m.measure,'Type':m.measure_type,
           'Timepoints':(m.timepoints||[]).join(', '),'Resolved':m.resolved?'Yes':'No'});
    if(m.text) h+=`<p style="font-size:12.5px">${esc(m.text)}</p>`;
  } else if(n.type==='Objective'){
    h+=kv({'Level':m.level});
    if(m.text) h+=`<p style="font-size:12.5px">${esc(m.text)}</p>`;
  } else if(n.type==='Regulatory'){
    h+=kv({'Standard':m.standard}); if(m.note) h+=`<p style="font-size:12.5px">${esc(m.note)}</p>`;
  }
  const mine=issueByNode[n.id]||[];
  if(mine.length) h+=`<div class="sub" style="margin-top:10px">Issues</div>`+mine.map(is=>
      `<div class="issues-row"><span class="dot" style="background:${cssv(SEV[is.severity]||'--muted')}"></span><div>${esc(is.message)}</div></div>`).join('');
  dp.innerHTML=h;
}
function breadcrumb(id){
  const {anc,desc}=lineage(id);
  const order=['Objective','Endpoint','Regulatory','SDTM','ADaM','TLF'];
  const chain=[...anc,id,...desc].map(x=>byId[x]).filter(Boolean)
    .sort((a,b)=>order.indexOf(a.type)-order.indexOf(b.type));
  const seen=new Set();
  return `<div class="breadcrumb">`+chain.filter(n=>!seen.has(n.id)&&seen.add(n.id)).map(n=>
    `<span class="n mono" onclick="window.__focus('${n.id}')">${esc(n.label)}</span>`).join(' ▸ ')+`</div>`;
}
window.__focus=id=>{ focusNode(id); select(id); };

function kv(o){ let r='<div class="kv">'; for(const k in o){ if(o[k]) r+=`<div class="k">${esc(k)}</div><div>${esc(o[k])}</div>`; } return r+'</div>'; }
function collapse(t,inner,open){ return `<details ${open?'open':''}><summary>${esc(t)}</summary>${inner}</details>`; }
function table(head,rows){ if(!rows.length) return '<div class="empty">None.</div>';
  return `<div class="scroll"><table class="tbl"><thead><tr>${head.map(h=>`<th>${esc(h)}</th>`).join('')}</tr></thead><tbody>`+
    rows.map(r=>`<tr>${r.map(c=>`<td>${esc(c||'')}</td>`).join('')}</tr>`).join('')+`</tbody></table></div>`; }
function ardBlock(text,kind){
  if(kind==='csv'){
    const rows=parseCSV(text).slice(0,400);
    if(rows.length){ const head=rows[0]; return table(head, rows.slice(1)); }
  }
  return `<div class="scroll"><pre>${esc(text)}</pre></div>`;
}
function parseCSV(t){
  const out=[]; let row=[],cur='',q=false;
  for(let i=0;i<t.length;i++){ const c=t[i];
    if(q){ if(c=='"'){ if(t[i+1]=='"'){cur+='"';i++;} else q=false; } else cur+=c; }
    else if(c=='"') q=true; else if(c==','){row.push(cur);cur='';}
    else if(c=='\n'){row.push(cur);out.push(row);row=[];cur='';}
    else if(c!='\r') cur+=c;
  }
  if(cur.length||row.length){row.push(cur);out.push(row);} return out;
}

/* ---- issues panel ---- */
const ip=document.getElementById('issuesPanel');
function renderIssues(){
  document.getElementById('issueCount').textContent=G.issues.length||'';
  if(!G.issues.length){ ip.innerHTML='<div class="empty">No issues — every objective reaches a deliverable and every dependency resolved.</div>'; return; }
  const order={blocked:0,clarification:1,gap:2,info:3};
  const sorted=[...G.issues].sort((a,b)=>(order[a.severity]??9)-(order[b.severity]??9));
  ip.innerHTML=sorted.map(is=>`<div class="issues-row" ${is.nodeId?`onclick="window.__focus('${is.nodeId}')"`:''}>
     <span class="dot" style="background:${cssv(SEV[is.severity]||'--muted')}"></span>
     <div><b style="text-transform:capitalize">${esc(is.severity)}</b><br>${esc(is.message)}</div></div>`).join('');
}

/* ---- status filter ---- */
const statusesPresent=[...new Set(G.nodes.filter(n=>n.type==='TLF').map(n=>n.status))];
const statusHidden=new Set();
const sf=document.getElementById('statusFilter');
if(statusesPresent.length){
  sf.innerHTML='<span style="color:var(--muted)">Status:</span>'+statusesPresent.map(s=>
    `<label class="chip"><input type="checkbox" checked data-s="${s}" style="margin:0">${STATUS_ICON[s]||''} ${esc(s)}</label>`).join('');
  sf.querySelectorAll('input').forEach(cb=>cb.addEventListener('change',()=>{
    cb.checked?statusHidden.delete(cb.dataset.s):statusHidden.add(cb.dataset.s); applyStatusFilter();
  }));
} else { sf.style.display='none'; }
function applyStatusFilter(keepSelection){
  G.nodes.forEach(n=>{
    if(n.type==='TLF'&&statusHidden.has(n.status)){ nodeEls[n.id].style.display='none'; }
    else nodeEls[n.id].style.display='';
  });
  edgeEls.forEach(p=>{ const s=byId[p._e.source],t=byId[p._e.target];
    p.style.display=(nodeEls[s.id].style.display==='none'||nodeEls[t.id].style.display==='none')?'none':''; });
  if(selected&&!keepSelection) select(selected);
}

/* ---- type legend / filter ---- */
const legend=document.getElementById('legend'); const typeHidden=new Set();
const typesPresent=TYPES.filter(t=>G.nodes.some(n=>n.type===t));
legend.innerHTML=typesPresent.map(t=>`<span class="chip" data-t="${t}"><span class="sw" style="background:${cssv(TYPE_VAR[t])}"></span>${t}</span>`).join('');
legend.querySelectorAll('.chip').forEach(c=>c.addEventListener('click',()=>{
  const t=c.dataset.t; c.classList.toggle('off');
  typeHidden.has(t)?typeHidden.delete(t):typeHidden.add(t);
  G.nodes.forEach(n=>{ if(n.type===t) nodeEls[n.id].style.display=typeHidden.has(t)?'none':''; });
  edgeEls.forEach(p=>{ const s=byId[p._e.source],t2=byId[p._e.target];
    p.style.display=(typeHidden.has(s.type)||typeHidden.has(t2.type))?'none':''; });
}));

/* ---- search ---- */
document.getElementById('search').addEventListener('input',e=>{
  const q=e.target.value.trim().toLowerCase(); if(!q){clearSelect();return;}
  const hit=G.nodes.find(n=>(n.label||'').toLowerCase().includes(q)||(n.title||'').toLowerCase().includes(q)||(n.sublabel||'').toLowerCase().includes(q));
  if(hit){ focusNode(hit.id); select(hit.id); }
});

/* ---- counts bar ---- */
const c=G.counts;
document.getElementById('studyName').textContent=(G.study.name||G.study.id||'')+(G.study.phase?` · ${G.study.phase}`:'');
document.getElementById('counts').innerHTML=[
  ['Objectives',c.objectives],['Endpoints',c.endpoints+(c.endpoints_unresolved?` (${c.endpoints_unresolved}❗)`:'')],
  ['TLFs',c.tlf],['ADaM',c.adam],['SDTM',c.sdtm+(c.sdtm_absent?` (${c.sdtm_absent}⛔)`:'')],
  ['✅',G.status.generated],['⛔',G.status.blocked],['❓',G.status['needs-clarification']],
].filter(x=>x[1]!==undefined).map(x=>`<span class="pill">${x[0]} <b>${x[1]}</b></span>`).join('');

/* ---- interactions: pan / zoom / drag / focus ---- */
function focusNode(id){ const n=byId[id]; if(!n)return; const r=svg.getBoundingClientRect();
  view.x=r.width/2-(n.x+NODEW/2)*view.k; view.y=r.height/2-(n.y+NODEH/2)*view.k; applyView(); }
let panning=false,px,py;
svg.addEventListener('mousedown',e=>{ if(e.target.closest('.node'))return; panning=true;px=e.clientX;py=e.clientY;svg.classList.add('grabbing'); });
window.addEventListener('mousemove',e=>{ if(!panning)return; view.x+=e.clientX-px;view.y+=e.clientY-py;px=e.clientX;py=e.clientY;applyView(); });
window.addEventListener('mouseup',()=>{panning=false;svg.classList.remove('grabbing');});
svg.addEventListener('wheel',e=>{ e.preventDefault(); const r=svg.getBoundingClientRect();
  const mx=e.clientX-r.left,my=e.clientY-r.top; const f=e.deltaY<0?1.12:1/1.12; const nk=Math.max(.2,Math.min(3,view.k*f));
  view.x=mx-(mx-view.x)*(nk/view.k); view.y=my-(my-view.y)*(nk/view.k); view.k=nk; applyView(); },{passive:false});
function enableDrag(g,n){ let dr=false,ox,oy;
  g.addEventListener('mousedown',e=>{ e.stopPropagation(); dr=true; ox=e.clientX;oy=e.clientY; });
  window.addEventListener('mousemove',e=>{ if(!dr)return; n.x+=(e.clientX-ox)/view.k; n.y+=(e.clientY-oy)/view.k; ox=e.clientX;oy=e.clientY;
    g.setAttribute('transform',`translate(${n.x},${n.y})`);
    edgeEls.forEach(p=>{ if(p._e.source===n.id||p._e.target===n.id) p.setAttribute('d',edgePath(p._e)); }); });
  window.addEventListener('mouseup',()=>dr=false);
}
document.getElementById('zoomIn').onclick=()=>{view.k=Math.min(3,view.k*1.2);applyView();};
document.getElementById('zoomOut').onclick=()=>{view.k=Math.max(.2,view.k/1.2);applyView();};
document.getElementById('resetView').onclick=fit;
document.getElementById('themeBtn').onclick=()=>{
  const cur=document.documentElement.getAttribute('data-theme');
  const dark=cur? cur==='dark' : matchMedia('(prefers-color-scheme: dark)').matches;
  document.documentElement.setAttribute('data-theme',dark?'light':'dark');
  G.nodes.forEach(n=>{ const col=cssv(TYPE_VAR[n.type]); const g=nodeEls[n.id];
    g.querySelector('.box').setAttribute('stroke',col); g.querySelector('rect+rect')?.setAttribute('fill',col);
    g.querySelector('text').setAttribute('fill',col); });
  if(document.getElementById('issuesPanel').style.display!=='none') renderIssues();
  if(selected) renderDetail(byId[selected]);
};

/* ---- tabs ---- */
function showTab(which){
  const d=which==='detail';
  document.getElementById('tabDetail').classList.toggle('active',d);
  document.getElementById('tabIssues').classList.toggle('active',!d);
  document.getElementById('detailPanel').style.display=d?'':'none';
  document.getElementById('issuesPanel').style.display=d?'none':'';
  if(!d) renderIssues();
}
document.getElementById('tabDetail').onclick=()=>showTab('detail');
document.getElementById('tabIssues').onclick=()=>showTab('issues');

function esc(s){ return String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }
function clip(s,n){ s=String(s||''); return s.length>n? s.slice(0,n-1)+'…':s; }
renderIssues(); fit();
addEventListener('resize',()=>{ /* keep current pan/zoom; user can hit Fit */ });
</script>
</body>
</html>
"""


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)

    sm = load_json("study-model.json")
    plan = load_json("tlf-plan.json")
    aspec = load_json("analysis-spec.json")
    adamspec = load_json("adam-spec.json")

    missing = [n for n, v in (("study-model.json", sm), ("tlf-plan.json", plan)) if v is None]
    study, objectives, endpoints, unresolved = norm_study_model(sm)
    tlfs = norm_tlf_plan(plan)
    analysis = norm_analysis_spec(aspec)
    adam = norm_adam_spec(adamspec)

    graph = assemble(study, objectives, endpoints, unresolved, tlfs, analysis, adam)
    html_doc = render_html(graph)

    # write outputs to /output and mirror the machine artifacts to /workspace
    (OUTPUT / "traceability.html").write_text(html_doc, encoding="utf-8")
    (OUTPUT / "trace_graph.json").write_text(json.dumps(graph, ensure_ascii=False, indent=2), encoding="utf-8")

    manifest = {
        "study": study,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "files": [
            {"name": "traceability.html", "type": "explorer"},
            {"name": "trace_graph.json", "type": "graph-model"},
            {"name": "manifest.json", "type": "manifest"},
        ],
        "counts": graph["counts"],
        "status": graph["status"],
        "issues": len(graph["issues"]),
    }
    (OUTPUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    if WORKSPACE.is_dir():
        try:
            (WORKSPACE / "traceability.html").write_text(html_doc, encoding="utf-8")
            (WORKSPACE / "trace_graph.json").write_text(
                json.dumps(graph, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass

    status = "warn" if (missing or graph["issues"]) else "pass"
    result = {
        "status": status,
        "counts": graph["counts"],
        "statusTallies": graph["status"],
        "issues": len(graph["issues"]),
        "missingInputs": missing,
        "outputs": ["traceability.html", "trace_graph.json", "manifest.json"],
        "summary": (
            f"Traceability explorer built: {graph['counts']['tlf']} TLFs, "
            f"{graph['counts']['objectives']} objectives, {graph['counts']['endpoints']} endpoints, "
            f"{len(graph['issues'])} issue(s)."
            + (f" Missing inputs: {', '.join(missing)}." if missing else "")
        ),
    }
    (OUTPUT / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    sys.stderr.write("[build_traceability] " + result["summary"] + "\n")
    # Assembly is best-effort by contract (never drop a node); only a hard IO
    # failure is fatal. Missing optional inputs downgrade to a warn, not a crash.
    return 0


if __name__ == "__main__":
    sys.exit(main())
