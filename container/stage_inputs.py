#!/usr/bin/env python3
"""Step 2 (stage-inputs): resolve the Reporting Event + ADaM for this run.

The human step may upload an ARS v1.0 Reporting Event JSON and/or ADaM datasets.
If present we use them; otherwise we fall back to the bundled CDISCPILOT01
reference (the same study Cases 1 and 2 use, so the three cases chain on one
trial). Uploaded files land among the step inputs in /output (and sometimes
/workspace); we scan both.

Writes:
  /workspace/reporting_event.json   the ARS spec, for the bind-validate step
  /workspace/adam/*.csv             the ADaM datasets, for the downstream steps
  /output/result.json              a small run summary
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

WORKSPACE = Path("/workspace")
OUTPUT = Path("/output")
BUNDLED_ARS = Path("/app/fixtures/reporting_event.json")
BUNDLED_ADAM = Path("/app/fixtures/adam")

RESERVED_JSON = {"result.json", "input.json", "reporting_event.json", "coverage.json", "manifest.json"}


def looks_like_reporting_event(doc: object) -> bool:
    if not isinstance(doc, dict):
        return False
    if doc.get("@type") == "ReportingEvent":
        return True
    return "analyses" in doc and "outputs" in doc


def find_uploaded_ars() -> Path | None:
    for directory in (OUTPUT, WORKSPACE):
        if not directory.exists():
            continue
        for candidate in sorted(directory.glob("*.json")):
            if candidate.name in RESERVED_JSON:
                continue
            try:
                if looks_like_reporting_event(json.loads(candidate.read_text(encoding="utf-8"))):
                    return candidate
            except (ValueError, OSError):
                continue
    return None


def find_uploaded_adam() -> list[Path]:
    """ADaM datasets uploaded as CSV. (Dataset-JSON / XPT support is a follow-up;
    the reference path and the recipes use CSV.)"""
    found: list[Path] = []
    for directory in (OUTPUT, WORKSPACE):
        if not directory.exists():
            continue
        for candidate in sorted(directory.glob("*.csv")):
            name = candidate.stem.lower()
            if name.startswith("ad"):
                found.append(candidate)
    return found


def main() -> None:
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    adam_dir = WORKSPACE / "adam"
    adam_dir.mkdir(parents=True, exist_ok=True)

    # --- Reporting Event ---
    uploaded_ars = find_uploaded_ars()
    ars_source = uploaded_ars if uploaded_ars is not None else BUNDLED_ARS
    if not ars_source.exists():
        raise SystemExit(f"No Reporting Event available — neither an upload nor the bundled fixture at {BUNDLED_ARS}.")
    ars = json.loads(ars_source.read_text(encoding="utf-8"))
    if not looks_like_reporting_event(ars):
        raise SystemExit(f"{ars_source} is not an ARS Reporting Event (no @type/analyses/outputs).")
    (WORKSPACE / "reporting_event.json").write_text(json.dumps(ars, indent=2), encoding="utf-8")

    # --- ADaM ---
    uploaded_adam = find_uploaded_adam()
    if uploaded_adam:
        for src in uploaded_adam:
            shutil.copy2(src, adam_dir / src.name.lower())
        adam_source = "upload"
    else:
        if not BUNDLED_ADAM.exists():
            raise SystemExit(f"No ADaM available — no upload and no bundled fixture at {BUNDLED_ADAM}.")
        for src in sorted(BUNDLED_ADAM.glob("*.csv")):
            shutil.copy2(src, adam_dir / src.name.lower())
        adam_source = "bundled-reference"

    adam_files = sorted(p.name for p in adam_dir.glob("*.csv"))
    if not adam_files:
        raise SystemExit("No ADaM datasets staged.")

    summary = {
        "status": "success",
        "arsSource": "upload" if uploaded_ars is not None else "bundled-reference",
        "reportingEventId": ars.get("id"),
        "reportingEventName": ars.get("name"),
        "outputs": len(ars.get("outputs", [])),
        "analyses": len(ars.get("analyses", [])),
        "adamSource": adam_source,
        "adamDatasets": adam_files,
    }
    (OUTPUT / "result.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(
        f"Staged Reporting Event '{ars.get('name')}' "
        f"({len(ars.get('outputs', []))} outputs, {len(ars.get('analyses', []))} analyses; {summary['arsSource']}) "
        f"and {len(adam_files)} ADaM datasets ({adam_source}): {', '.join(adam_files)}"
    )


if __name__ == "__main__":
    main()
