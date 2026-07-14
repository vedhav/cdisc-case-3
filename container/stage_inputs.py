#!/usr/bin/env python3
"""Step 2 (stage-inputs): resolve the USDM + SDTM inputs for this run.

The human step uploads a USDM v3+ study-definition JSON and the SDTM datasets;
optionally, reference CSR outputs (ground truth) to enable the numeric diff in
generate-tlfs. Uploaded files land among the step inputs in /output (and
sometimes /workspace); we scan both. Nothing is bundled — a run needs an upload.

Writes:
  /workspace/usdm.json          the USDM study definition, for plan-tlfs
  /workspace/sdtm/*             the SDTM datasets, for derive-adam
  /workspace/ground_truth/*     (optional) reference CSR outputs for the numeric
                                diff in generate-tlfs — only when uploaded
  /output/result.json           a small run summary
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

WORKSPACE = Path("/workspace")
OUTPUT = Path("/output")

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

    # --- USDM (upload required) ---
    uploaded_usdm = find_uploaded_usdm()
    if uploaded_usdm is None:
        raise SystemExit("No USDM uploaded — provide a USDM study-definition JSON at Provide inputs.")
    usdm = json.loads(uploaded_usdm.read_text(encoding="utf-8"))
    if not looks_like_usdm(usdm):
        raise SystemExit(f"{uploaded_usdm} does not look like a USDM study definition.")
    (WORKSPACE / "usdm.json").write_text(json.dumps(usdm, indent=2), encoding="utf-8")

    # --- SDTM (upload required) ---
    uploaded_sdtm = find_uploaded_sdtm()
    if not uploaded_sdtm:
        raise SystemExit("No SDTM uploaded — provide the SDTM datasets at Provide inputs.")
    for src in uploaded_sdtm:
        shutil.copy2(src, sdtm_dir / src.name.lower())

    sdtm_files = sorted(p.name for p in sdtm_dir.iterdir() if p.is_file())
    if not sdtm_files:
        raise SystemExit("No SDTM datasets staged.")

    # --- Ground truth (optional upload; enables the numeric diff in generate-tlfs) ---
    ground_truth_source = None
    gt_uploads = []
    for directory in (OUTPUT, WORKSPACE):
        if directory.exists():
            gt_uploads += [p for p in directory.glob("*.md") if p.name.lower().startswith(("cdisc", "t-14", "f-14"))]
    if gt_uploads:
        gt_dir = WORKSPACE / "ground_truth"
        gt_dir.mkdir(parents=True, exist_ok=True)
        for src in gt_uploads:
            shutil.copy2(src, gt_dir / src.name)
        ground_truth_source = "upload"

    summary = {
        "status": "success",
        "usdmSource": "upload",
        "usdmVersion": usdm.get("usdmVersion"),
        "sdtmSource": "upload",
        "sdtmDatasets": sdtm_files,
        "groundTruth": ground_truth_source,
    }
    (OUTPUT / "result.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(
        f"Staged uploaded USDM and {len(sdtm_files)} SDTM datasets: {', '.join(sdtm_files)}"
        + (f"; ground truth: {len(gt_uploads)} files" if ground_truth_source else "; no ground truth (numeric diff skipped)")
    )


if __name__ == "__main__":
    main()
