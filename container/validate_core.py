"""Deterministic CDISC CORE (conformance) gate for the derived ADaM.

Runs as the `validate-core` script step, between `generate-define` and
`generate-tlfs`. It runs the CDISC Open Rules Engine (`cdisc-rules-engine`,
CLI `core`) over the derived ADaM datasets, checked AGAINST the Define-XML 2.1
produced upstream, and gates on the conformance result: ERROR-severity findings
must be resolved (fixed by re-deriving) or, once the bounded auto-fix loop is
exhausted, justified by a human. Lower-severity findings (WARNING/NOTICE) are
reported but do not block.

Routing contract (same as validate_ars): a conformance FAILURE is NOT a process
error — this step ALWAYS exits 0 and encodes the outcome in /output/result.json.
The transitions branch on it:

    { passed: true }                       -> generate-tlfs (proceed)
    { passed: false, attempts < MAX }      -> derive-adam (re-derive to fix ERRORs)
    { passed: false, attempts >= MAX }     -> generate-tlfs (proceed; report carried
                                              into traceability + surfaced at review-tlfs)

The rules engine needs a rules cache. It is populated in the image at build time
(`core update-cache`, needs CDISC_LIBRARY_API_KEY) or mounted; if the engine or
its cache is unavailable this is an INFRA problem, not a data problem, so re-
deriving cannot fix it. In that case the gate does not burn the loop: it reports
`status=core-unavailable` and proceeds (passed=true) UNLESS CORE_REQUIRED=true,
so a missing engine never silently bricks a run — it is flagged loudly in the
report and result.json.

Env knobs:
  CORE_BIN            engine command (default "core")
  CORE_STANDARD       standard slug (default "adamig")
  CORE_VERSION        standard version (default "1.3")
  CORE_MAX_ATTEMPTS   auto-fix loop cap (default "2")
  CORE_REQUIRED       "true" => an unavailable engine fails the gate (default false)

Inputs (from /workspace, /output fallback):
  /workspace/adam/    derived ADaM datasets (.xpt / Dataset-JSON / .csv)
  define.xml          Define-XML 2.1 from generate-define

Outputs:
  /workspace/core-report.md, /output/core-report.md   human-readable summary
  /output/core-report.raw                              raw engine output (if any)
  /output/result.json   { passed, attempts, maxAttempts, errorCount, warningNoticeCount,
                          status, standard, version, summary }
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

WORKSPACE = Path(os.environ.get("WORKSPACE_DIR", "/workspace"))
OUTPUT = Path(os.environ.get("OUTPUT_DIR", "/output"))
ADAM_DIR = WORKSPACE / "adam"
DEFINE_CANDIDATES = (WORKSPACE / "define.xml", OUTPUT / "define.xml")

GATE_KEY = "core"
MAX_ATTEMPTS = int(os.environ.get("CORE_MAX_ATTEMPTS", "2"))
ATTEMPTS_FILE = WORKSPACE / ".gate-attempts.json"

CORE_BIN = os.environ.get("CORE_BIN", "core")
STANDARD = os.environ.get("CORE_STANDARD", "adamig")
VERSION = os.environ.get("CORE_VERSION", "1.3")
CORE_REQUIRED = os.environ.get("CORE_REQUIRED", "").lower() in ("1", "true", "yes")

DATASET_GLOBS = ("*.xpt", "*.json", "*.csv")
ERROR_TOKENS = {"error", "reject", "critical"}


def bump_attempts() -> int:
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


def find_define() -> Path | None:
    for p in DEFINE_CANDIDATES:
        if p.is_file():
            return p
    return None


def find_datasets() -> list[Path]:
    if not ADAM_DIR.is_dir():
        return []
    found: list[Path] = []
    for pattern in DATASET_GLOBS:
        found.extend(sorted(ADAM_DIR.glob(pattern)))
        if found:  # prefer the first available format (xpt > json > csv)
            break
    return found


def engine_available() -> bool:
    return shutil.which(CORE_BIN) is not None


def run_core(datasets: list[Path], define: Path | None) -> tuple[int, str]:
    """Invoke the rules engine; return (returncode, combined_output). Raises
    FileNotFoundError if the binary is absent."""
    report_path = OUTPUT / "core-report"
    cmd = [CORE_BIN, "validate", "-s", STANDARD, "-v", VERSION,
           "-of", "JSON", "-o", str(report_path)]
    if define is not None:
        cmd += ["-dxp", str(define)]
    for ds in datasets:
        cmd += ["-dp", str(ds)]
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(WORKSPACE))
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def parse_report() -> tuple[int, int, list[dict]]:
    """Best-effort parse of the engine's JSON report → (errors, warn_notice,
    sample_findings). Tolerant to the report shape varying by engine version."""
    for name in ("core-report.json", "core-report"):
        p = OUTPUT / name
        if p.is_file():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            return _count_findings(data)
    return 0, 0, []


def _count_findings(data) -> tuple[int, int, list[dict]]:
    errors = 0
    warn_notice = 0
    sample: list[dict] = []

    def note(entry, severity):
        nonlocal errors, warn_notice
        sev = str(severity or "").strip().lower()
        is_error = any(tok in sev for tok in ERROR_TOKENS)
        if is_error:
            errors += 1
        else:
            warn_notice += 1
        if len(sample) < 25:
            sample.append({"severity": sev or "unknown",
                           "rule": entry.get("rule_id") or entry.get("core_id") or entry.get("id") or "",
                           "message": entry.get("message") or entry.get("description") or ""})

    def walk(obj):
        if isinstance(obj, dict):
            sev = obj.get("severity") or obj.get("Severity") or obj.get("status")
            if sev is not None and ("message" in obj or "description" in obj or "rule_id" in obj):
                note(obj, sev)
            for v in obj.values():
                walk(v)
        elif isinstance(obj, list):
            for v in obj:
                walk(v)

    walk(data)
    return errors, warn_notice, sample


def render_report(status, passed, attempts, errors, warn_notice, sample, extra="") -> str:
    lines = ["# CDISC CORE conformance report", ""]
    lines.append(f"- Standard: `{STANDARD}` v`{VERSION}`")
    lines.append(f"- Result: **{'PASS' if passed else 'FAIL'}** (status: {status})")
    lines.append(f"- Attempt: {attempts} of {MAX_ATTEMPTS}")
    lines.append(f"- ERROR-severity findings: {errors}")
    lines.append(f"- WARNING/NOTICE findings: {warn_notice}")
    lines.append("")
    if status == "core-unavailable":
        lines.append("> **CORE engine or rules cache unavailable in this image.** This is an "
                     "infrastructure gap, not a data defect — re-deriving ADaM cannot fix it. "
                     "Populate the cache at build time (`core update-cache`, needs "
                     "CDISC_LIBRARY_API_KEY) or set CORE_REQUIRED=true to hard-block.")
        if extra:
            lines.append("")
            lines.append("```")
            lines.append(extra[-1500:])
            lines.append("```")
        return "\n".join(lines) + "\n"
    if passed:
        lines.append("No ERROR-severity conformance findings against the ADaM standard. "
                     "Proceeding to TLF generation.")
    else:
        lines.append("ERROR-severity findings must be resolved (re-derive ADaM) or, once the "
                     "auto-fix loop is exhausted, justified by the reviewer.")
    if sample:
        lines.append("")
        lines.append("## Findings (sample)")
        for f in sample:
            rule = f" `{f['rule']}`" if f["rule"] else ""
            lines.append(f"- **{f['severity']}**{rule} — {f['message']}")
    return "\n".join(lines) + "\n"


def write_outputs(report_md: str, result: dict) -> None:
    for base in (WORKSPACE, OUTPUT):
        base.mkdir(parents=True, exist_ok=True)
        (base / "core-report.md").write_text(report_md, encoding="utf-8")
    (OUTPUT / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")


def main() -> None:
    attempts = bump_attempts()
    datasets = find_datasets()
    define = find_define()

    errors = warn_notice = 0
    sample: list[dict] = []
    extra = ""

    if not engine_available():
        status = "core-unavailable"
        extra = f"'{CORE_BIN}' not found on PATH"
    elif not datasets:
        status = "no-datasets"
        extra = f"no ADaM datasets found under {ADAM_DIR}"
    else:
        try:
            rc, combined = run_core(datasets, define)
            (OUTPUT / "core-report.raw").write_text(combined, encoding="utf-8")
            errors, warn_notice, sample = parse_report()
            # rc != 0 with a parseable report just means findings exist; rc != 0
            # with no report is an engine failure.
            if rc != 0 and not sample and errors == 0:
                status = "core-unavailable"
                extra = combined
            else:
                status = "ran"
        except FileNotFoundError:
            status = "core-unavailable"
            extra = f"'{CORE_BIN}' could not be executed"

    if status == "ran":
        passed = errors == 0
    elif status == "no-datasets":
        passed = False  # genuine data problem — re-derive
    elif status == "core-unavailable":
        passed = not CORE_REQUIRED  # proceed unless CORE is declared required
    else:
        passed = errors == 0

    if not passed and attempts >= MAX_ATTEMPTS and status != "core-unavailable":
        routing_status = "giveup"
    elif passed:
        routing_status = "pass"
    else:
        routing_status = "fail"

    report_md = render_report(status, passed, attempts, errors, warn_notice, sample, extra)
    summary = (f"CORE {status}: {errors} error(s), {warn_notice} warning/notice "
               f"(attempt {attempts}/{MAX_ATTEMPTS}) -> {'PASS' if passed else 'FAIL'}")
    result = {
        "passed": passed,
        "attempts": attempts,
        "maxAttempts": MAX_ATTEMPTS,
        "errorCount": errors,
        "warningNoticeCount": warn_notice,
        "status": status,
        "routingStatus": routing_status,
        "standard": STANDARD,
        "version": VERSION,
        "summary": summary,
        "reportPath": "/output/core-report.md",
    }
    write_outputs(report_md, result)
    print(f"validate_core: {summary}", file=sys.stderr)
    sys.exit(0)


if __name__ == "__main__":
    main()
