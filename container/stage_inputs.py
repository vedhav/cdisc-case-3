#!/usr/bin/env python3
"""Step 2 (stage-inputs): resolve the USDM + SDTM inputs for this run.

The human step may upload a USDM v3+ study-definition JSON and/or SDTM datasets.
If present we use them; otherwise we fall back to the bundled CDISCPILOT01
reference (the same study Cases 1 and 2 use, so the three cases chain on one
trial). Uploaded files land among the step inputs in /output (and sometimes
/workspace); we scan both.

Writes:
  /workspace/usdm.json          the USDM study definition, for plan-tlfs
  /workspace/sdtm/*             the SDTM datasets, for derive-adam
  /workspace/ground_truth/*     (optional) reference CSR outputs for the numeric
                                diff in generate-tlfs — only when bundled/uploaded
  /output/result.json           a small run summary
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

WORKSPACE = Path("/workspace")
OUTPUT = Path("/output")
BUNDLED_USDM = Path("/app/fixtures/usdm.json")
BUNDLED_SDTM = Path("/app/fixtures/sdtm")
BUNDLED_GROUND_TRUTH = Path("/app/fixtures/ground_truth")

RESERVED_JSON = {
    "result.json", "input.json", "usdm.json", "study-model.json", "tlf-plan.json",
    "analysis-spec.json", "adam-spec.json", "coverage-report.json", "manifest.json",
}
SDTM_EXTS = {".xpt", ".csv", ".json"}


def looks_like_usdm(doc: object) -> bool:
    """USDM top-level has a `study` with versions/studyDesigns, or declares its
    usdmVersion. Be lenient — the planner does the real parsing."""
    if not isinstance(doc, dict):
        return False
    if "usdmVersion" in doc:
        return True
    study = doc.get("study")
    return isinstance(study, dict) and ("versions" in study or "studyDesigns" in study)


def find_uploaded_usdm() -> Path | None:
    for directory in (OUTPUT, WORKSPACE):
        if not directory.exists():
            continue
        for candidate in sorted(directory.glob("*.json")):
            if candidate.name in RESERVED_JSON:
                continue
            try:
                if looks_like_usdm(json.loads(candidate.read_text(encoding="utf-8"))):
                    return candidate
            except (ValueError, OSError):
                continue
    return None


def find_uploaded_sdtm() -> list[Path]:
    """SDTM domains uploaded as XPT / Dataset-JSON / CSV, named like a 2-letter
    domain (ae, dm, lb, qs, vs, ...) plus supp*/relrec."""
    found: list[Path] = []
    for directory in (OUTPUT, WORKSPACE):
        if not directory.exists():
            continue
        for candidate in sorted(directory.iterdir()):
            if not candidate.is_file() or candidate.suffix.lower() not in SDTM_EXTS:
                continue
            stem = candidate.stem.lower()
            if candidate.name in RESERVED_JSON:
                continue
            if len(stem) == 2 or stem.startswith("supp") or stem in {"relrec"} or (2 <= len(stem) <= 8 and stem.isalpha()):
                found.append(candidate)
    return found


def main() -> None:
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    sdtm_dir = WORKSPACE / "sdtm"
    sdtm_dir.mkdir(parents=True, exist_ok=True)

    # --- USDM ---
    uploaded_usdm = find_uploaded_usdm()
    usdm_source_path = uploaded_usdm if uploaded_usdm is not None else BUNDLED_USDM
    if not usdm_source_path.exists():
        raise SystemExit(f"No USDM available — neither an upload nor the bundled fixture at {BUNDLED_USDM}.")
    usdm = json.loads(usdm_source_path.read_text(encoding="utf-8"))
    if not looks_like_usdm(usdm):
        raise SystemExit(f"{usdm_source_path} does not look like a USDM study definition.")
    (WORKSPACE / "usdm.json").write_text(json.dumps(usdm, indent=2), encoding="utf-8")
    usdm_source = "upload" if uploaded_usdm is not None else "bundled-reference"

    # --- SDTM ---
    uploaded_sdtm = find_uploaded_sdtm()
    if uploaded_sdtm:
        for src in uploaded_sdtm:
            shutil.copy2(src, sdtm_dir / src.name.lower())
        sdtm_source = "upload"
    elif BUNDLED_SDTM.exists():
        for src in sorted(BUNDLED_SDTM.iterdir()):
            if src.is_file() and src.suffix.lower() in SDTM_EXTS:
                shutil.copy2(src, sdtm_dir / src.name.lower())
        sdtm_source = "bundled-reference"
    else:
        raise SystemExit(f"No SDTM available — no upload and no bundled fixture at {BUNDLED_SDTM}.")

    sdtm_files = sorted(p.name for p in sdtm_dir.iterdir() if p.is_file())
    if not sdtm_files:
        raise SystemExit("No SDTM datasets staged.")

    # --- Ground truth (optional; enables the numeric diff in generate-tlfs) ---
    ground_truth_source = None
    if uploaded_usdm is None and BUNDLED_GROUND_TRUTH.exists():
        gt_dir = WORKSPACE / "ground_truth"
        gt_dir.mkdir(parents=True, exist_ok=True)
        for src in sorted(BUNDLED_GROUND_TRUTH.glob("*")):
            if src.is_file():
                shutil.copy2(src, gt_dir / src.name)
        if any(gt_dir.iterdir()):
            ground_truth_source = "bundled-reference"

    summary = {
        "status": "success",
        "usdmSource": usdm_source,
        "usdmVersion": usdm.get("usdmVersion"),
        "sdtmSource": sdtm_source,
        "sdtmDatasets": sdtm_files,
        "groundTruth": ground_truth_source,
    }
    (OUTPUT / "result.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(
        f"Staged USDM ({usdm_source}) and {len(sdtm_files)} SDTM datasets ({sdtm_source}): "
        f"{', '.join(sdtm_files)}"
        + (f"; ground truth: {ground_truth_source}" if ground_truth_source else "; no ground truth (numeric diff skipped)")
    )


if __name__ == "__main__":
    main()
