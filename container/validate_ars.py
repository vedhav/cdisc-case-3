"""Deterministic ARS (Analysis Results Standard) conformance gate.

Runs as the `validate-ars` script step in the cdisc-case-3 workflow — the
automated conformance gate between `build-specs` (the `tlf-analysis-spec` agent)
and the human `review-specs` gate. It validates the ARS ReportingEvent the
spec step emits against the CDISC ARS Low-level Data Model (LDM) JSON Schema,
then runs a set of semantic cross-reference checks the raw schema cannot express
(every analysis resolves its method / analysis set / grouping; every list-of-
contents item resolves to a defined analysis or output).

Routing contract (see docs/workflow-examples/10-validation-gate.wd.json and the
mediforce-fullstack check-ci pattern): a validation FAILURE is NOT a process
error. This step ALWAYS exits 0 and encodes the outcome as fields in
/output/result.json; the workflow transitions branch on them:

    { passed: true }  -> review-specs (proceed)
    { passed: false, attempts < MAX } -> build-specs (agent fixes ARS + specs)
    { passed: false, attempts >= MAX } -> review-specs (human decides)

`attempts` is a monotonic counter persisted in /workspace so the auto-fix loop
terminates; the transition `when` expressions cap it (env/secrets are not
readable from `when`, so the cap value is emitted here as a field).

Inputs (read from /workspace, with /output as a fallback):
  reporting-event.json   the ARS ReportingEvent produced by tlf-analysis-spec
  (schema)               /app/container/schemas/ars_ldm.schema.json (baked in)

Outputs:
  /workspace/ars-validation.md    human-readable report (read by build-specs on
                                   a fail re-entry so the agent fixes the flagged
                                   items), mirrored to /output
  /output/ars-validation.json     the structured error list
  /output/result.json             { passed, attempts, maxAttempts, errorCount,
                                     schemaErrors, semanticErrors, status,
                                     summary }
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

WORKSPACE = Path(os.environ.get("WORKSPACE_DIR", "/workspace"))
OUTPUT = Path(os.environ.get("OUTPUT_DIR", "/output"))
SCHEMA_PATH = Path(
    os.environ.get("ARS_SCHEMA_PATH", "/app/container/schemas/ars_ldm.schema.json")
)
REPORTING_EVENT_NAME = "reporting-event.json"
GATE_KEY = "ars"
MAX_ATTEMPTS = int(os.environ.get("ARS_MAX_ATTEMPTS", "3"))
ATTEMPTS_FILE = WORKSPACE / ".gate-attempts.json"


def bump_attempts() -> int:
    """Monotonic per-gate run counter persisted in /workspace so the auto-fix
    loop terminates. Returns the attempt number for this run (1-based)."""
    state: dict = {}
    if ATTEMPTS_FILE.is_file():
        try:
            state = json.loads(ATTEMPTS_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            state = {}
    count = int(state.get(GATE_KEY, 0)) + 1
    state[GATE_KEY] = count
    try:
        WORKSPACE.mkdir(parents=True, exist_ok=True)
        ATTEMPTS_FILE.write_text(json.dumps(state), encoding="utf-8")
    except OSError:
        pass
    return count


def load_reporting_event():
    for base in (WORKSPACE, OUTPUT):
        p = base / REPORTING_EVENT_NAME
        if p.is_file():
            try:
                return json.loads(p.read_text(encoding="utf-8")), p
            except json.JSONDecodeError as exc:
                return None, f"{p}: invalid JSON — {exc}"
    return None, None


def schema_errors(instance: dict) -> list[dict]:
    """Every Draft-07 validation error, sorted by document location."""
    try:
        from jsonschema import Draft7Validator
    except ImportError:
        return [{"path": "(engine)", "message": "jsonschema not installed in image"}]
    try:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    except OSError as exc:
        return [{"path": "(schema)", "message": f"cannot read ARS schema: {exc}"}]

    validator = Draft7Validator(schema)
    out = []
    for err in sorted(validator.iter_errors(instance), key=lambda e: list(e.absolute_path)):
        loc = "/".join(str(p) for p in err.absolute_path) or "(root)"
        out.append({"path": loc, "message": err.message})
    return out


def semantic_errors(re_obj: dict) -> list[dict]:
    """Cross-reference checks the JSON Schema cannot express: dangling ids
    between analyses, methods, analysis sets, groupings, and the contents list.
    Every reference must resolve to a defined instance."""
    errors: list[dict] = []

    def ids(collection):
        return {
            item.get("id")
            for item in re_obj.get(collection, []) or []
            if isinstance(item, dict) and item.get("id")
        }

    method_ids = ids("methods")
    set_ids = ids("analysisSets")
    subset_ids = ids("dataSubsets")
    grouping_ids = ids("analysisGroupings")
    analyses = re_obj.get("analyses", []) or []
    analysis_ids = {a.get("id") for a in analyses if isinstance(a, dict)}
    output_ids = ids("outputs")

    for a in analyses:
        if not isinstance(a, dict):
            continue
        aid = a.get("id", "(unknown)")
        method_id = a.get("methodId")
        if method_id and method_id not in method_ids:
            errors.append({"path": f"analyses/{aid}/methodId",
                           "message": f"methodId '{method_id}' has no matching methods[].id"})
        set_id = a.get("analysisSetId")
        if set_id and set_id not in set_ids:
            errors.append({"path": f"analyses/{aid}/analysisSetId",
                           "message": f"analysisSetId '{set_id}' has no matching analysisSets[].id"})
        subset_id = a.get("dataSubsetId")
        if subset_id and subset_id not in subset_ids:
            errors.append({"path": f"analyses/{aid}/dataSubsetId",
                           "message": f"dataSubsetId '{subset_id}' has no matching dataSubsets[].id"})
        for og in a.get("orderedGroupings", []) or []:
            if isinstance(og, dict):
                gid = og.get("groupingId")
                if gid and gid not in grouping_ids:
                    errors.append({"path": f"analyses/{aid}/orderedGroupings",
                                   "message": f"groupingId '{gid}' has no matching analysisGroupings[].id"})

    # Every list-of-contents item must reference a defined analysis or output.
    def walk_list(nested, trail="mainListOfContents"):
        if not isinstance(nested, dict):
            return
        for i, item in enumerate(nested.get("listItems", []) or []):
            if not isinstance(item, dict):
                continue
            here = f"{trail}/listItems/{i}"
            an = item.get("analysisId")
            ou = item.get("outputId")
            if an and an not in analysis_ids:
                errors.append({"path": here, "message": f"analysisId '{an}' is not a defined analysis"})
            if ou and ou not in output_ids:
                errors.append({"path": here, "message": f"outputId '{ou}' is not a defined output"})
            if item.get("sublist"):
                walk_list(item["sublist"], here + "/sublist")

    walk_list(re_obj.get("mainListOfContents") or {})
    return errors


def render_report(passed, attempts, s_errors, sem_errors, re_obj) -> str:
    lines = ["# ARS conformance report", ""]
    lines.append(f"- Result: **{'PASS' if passed else 'FAIL'}**")
    lines.append(f"- Attempt: {attempts} of {MAX_ATTEMPTS}")
    if isinstance(re_obj, dict):
        lines.append(f"- ReportingEvent: `{re_obj.get('id', '?')}` — {re_obj.get('name', '')}")
        lines.append(f"- Analyses: {len(re_obj.get('analyses', []) or [])} · "
                     f"Methods: {len(re_obj.get('methods', []) or [])} · "
                     f"Outputs: {len(re_obj.get('outputs', []) or [])}")
    lines.append("")
    if passed:
        lines.append("The ARS ReportingEvent conforms to the ARS LDM schema and all "
                     "internal references resolve. Proceeding to human spec review.")
        return "\n".join(lines) + "\n"

    if s_errors:
        lines.append(f"## Schema errors ({len(s_errors)})")
        lines.append("Fix these in `reporting-event.json` so it validates against the ARS LDM schema.")
        lines.append("")
        for e in s_errors:
            lines.append(f"- `{e['path']}` — {e['message']}")
        lines.append("")
    if sem_errors:
        lines.append(f"## Reference errors ({len(sem_errors)})")
        lines.append("Every id referenced by an analysis or the list of contents must resolve to a defined instance.")
        lines.append("")
        for e in sem_errors:
            lines.append(f"- `{e['path']}` — {e['message']}")
        lines.append("")
    return "\n".join(lines) + "\n"


def write_outputs(report_md: str, structured: dict, result: dict) -> None:
    for base in (WORKSPACE, OUTPUT):
        base.mkdir(parents=True, exist_ok=True)
        (base / "ars-validation.md").write_text(report_md, encoding="utf-8")
    (OUTPUT / "ars-validation.json").write_text(json.dumps(structured, indent=2), encoding="utf-8")
    (OUTPUT / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")


def main() -> None:
    attempts = bump_attempts()
    re_obj, source = load_reporting_event()

    if re_obj is None:
        message = (source if isinstance(source, str)
                   else f"{REPORTING_EVENT_NAME} not found in /workspace or /output — "
                        "build-specs must emit an ARS ReportingEvent")
        s_errors = [{"path": REPORTING_EVENT_NAME, "message": message}]
        sem_errors: list[dict] = []
    else:
        s_errors = schema_errors(re_obj)
        sem_errors = semantic_errors(re_obj)

    error_count = len(s_errors) + len(sem_errors)
    passed = error_count == 0
    status = "pass" if passed else ("giveup" if attempts >= MAX_ATTEMPTS else "fail")

    report_md = render_report(passed, attempts, s_errors, sem_errors,
                              re_obj if isinstance(re_obj, dict) else {})
    structured = {"passed": passed, "schemaErrors": s_errors, "semanticErrors": sem_errors}
    summary = (f"ARS conformance {'passed' if passed else 'failed'} "
               f"({error_count} error(s), attempt {attempts}/{MAX_ATTEMPTS})")
    result = {
        "passed": passed,
        "attempts": attempts,
        "maxAttempts": MAX_ATTEMPTS,
        "errorCount": error_count,
        "schemaErrors": len(s_errors),
        "semanticErrors": len(sem_errors),
        "status": status,
        "summary": summary,
        "reportPath": "/output/ars-validation.md",
    }
    write_outputs(report_md, structured, result)
    print(f"validate_ars: {summary}", file=sys.stderr)
    # ALWAYS exit 0 — the gate outcome is routed via result.json, not the exit code.
    sys.exit(0)


if __name__ == "__main__":
    main()
