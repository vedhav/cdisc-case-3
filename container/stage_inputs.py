"""Deterministically stage the run's uploaded inputs into the shared workspace.

Runs INSIDE the `plan-tlfs` agent container as its mandatory STEP 0 (the agent
invokes `python3 /app/container/stage_inputs.py` before any planning). Uploaded
files are mounted read-only at /data ONLY on the step that directly follows the
upload — this script content-detects the USDM among them and persists the rest as
the SDTM inventory in /workspace so every later step can read them. Splitting this
off the LLM removes the risk of an agent mis-identifying the USDM or silently
dropping datasets while hand-copying up to 200 files.

USDM detection is by CONTENT, not extension: SDTM can also arrive as Dataset-JSON,
so a `.json` is only the USDM when it carries `usdmVersion` or a `study` object.

Reads:   /data/*                (uploaded USDM + SDTM datasets)
Writes:  /workspace/usdm.json           the detected USDM study-definition
         /workspace/sdtm/<name>         every other uploaded file (the SDTM inventory)
         /workspace/stage_manifest.json { usdm, sdtm[], sdtmCount }

Paths are overridable via DATA_DIR / WORKSPACE_DIR for local testing. Exits
non-zero (fail-fast) when no USDM or no SDTM dataset is found — the run cannot
plan without both.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

DATA = Path(os.environ.get("DATA_DIR", "/data"))
WORKSPACE = Path(os.environ.get("WORKSPACE_DIR", "/workspace"))


def is_usdm(path: Path) -> bool:
    """A JSON file carrying `usdmVersion` or a `study` object is the USDM."""
    if path.suffix.lower() != ".json":
        return False
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return False
    if not isinstance(doc, dict):
        return False
    if "usdmVersion" in doc:
        return True
    study = doc.get("study")
    return isinstance(study, dict) and "versions" in study


def die(message: str) -> None:
    print(f"stage_inputs: {message}", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    if not DATA.is_dir():
        die(f"input directory {DATA} not found — uploaded files are mounted at /data only on the step after upload")

    uploads = sorted(p for p in DATA.iterdir() if p.is_file())
    if not uploads:
        die(f"no files found under {DATA}")

    usdm_candidates = [p for p in uploads if is_usdm(p)]
    if not usdm_candidates:
        die("no USDM study-definition JSON found among the uploads (need `usdmVersion` or a `study.versions` object)")
    usdm = usdm_candidates[0]
    if len(usdm_candidates) > 1:
        print(f"stage_inputs: {len(usdm_candidates)} USDM-looking files; using {usdm.name}", file=sys.stderr)

    sdtm_dir = WORKSPACE / "sdtm"
    sdtm_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(usdm, WORKSPACE / "usdm.json")

    sdtm_names: list[str] = []
    for upload in uploads:
        if upload == usdm:
            continue
        shutil.copyfile(upload, sdtm_dir / upload.name)
        sdtm_names.append(upload.name)

    if not sdtm_names:
        die("no SDTM datasets found among the uploads (only the USDM was uploaded)")

    manifest = {"usdm": usdm.name, "sdtm": sdtm_names, "sdtmCount": len(sdtm_names)}
    (WORKSPACE / "stage_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"stage_inputs: USDM={usdm.name} → /workspace/usdm.json; {len(sdtm_names)} SDTM datasets → /workspace/sdtm/", file=sys.stderr)


if __name__ == "__main__":
    main()
