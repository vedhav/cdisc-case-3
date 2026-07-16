"""Behavior test for container/build_trace_graph.py.

Assembles a small but representative workspace (study-model / tlf-plan /
analysis-spec / adam-spec + a staged SDTM inventory + a rendered TLF) and asserts
the deterministic graph model matches graph-data-schema.md: node/edge join,
two-way coverage, the `absent` SDTM flag, status tallies, and the issues feed.
Pure logic — no network, no secrets — so it MUST run green.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "container" / "build_trace_graph.py"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "trace"


def _build_workspace(tmp: Path) -> Path:
    """Copy the JSON artifacts + scaffold sdtm/ tfl/ ard/ into a fresh workspace."""
    ws = tmp / "workspace"
    ws.mkdir(parents=True)
    for name in ("study-model.json", "tlf-plan.json", "analysis-spec.json", "adam-spec.json"):
        shutil.copyfile(FIXTURES / name, ws / name)
    # Staged SDTM inventory: DM + QS present; DV deliberately absent.
    (ws / "sdtm").mkdir()
    (ws / "sdtm" / "DM.csv").write_text("USUBJID\n", encoding="utf-8")
    (ws / "sdtm" / "QS.csv").write_text("USUBJID,QSTESTCD\n", encoding="utf-8")
    (ws / "sdtm" / "_manifest.json").write_text("{}", encoding="utf-8")  # skipped (underscore)
    # Rendered + ARD for the two planned tables so they classify `generated`.
    (ws / "tfl").mkdir()
    (ws / "ard").mkdir()
    (ws / "tfl" / "T-14-3.01.generated.md").write_text("| stat | val |\n", encoding="utf-8")
    (ws / "tfl" / "T-14-1.01.generated.md").write_text("| n | pct |\n", encoding="utf-8")
    (ws / "ard" / "T-14-3.01.json").write_text('[{"stat": "lsmean"}]', encoding="utf-8")
    return ws


def _run(tmp: Path) -> dict:
    ws = _build_workspace(tmp)
    out = tmp / "output"
    out.mkdir()
    env = os.environ.copy()
    env.update({"WORKSPACE_DIR": str(ws), "OUTPUT_DIR": str(out)})
    proc = subprocess.run([sys.executable, str(SCRIPT)], env=env, capture_output=True, text=True)
    assert proc.returncode == 0, f"exit {proc.returncode}: {proc.stderr}"
    # Written to both workspace and output — assert parity, return the model.
    graph = json.loads((ws / "trace_graph.json").read_text(encoding="utf-8"))
    assert (out / "trace_graph.json").exists() and (out / "manifest.json").exists()
    assert json.loads((out / "result.json").read_text(encoding="utf-8"))["ok"] is True
    return graph


def test_counts_and_status_tallies() -> None:
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        g = _run(Path(tmp))
        assert g["counts"]["objectives"] == 2
        assert g["counts"]["endpoints"] == 2
        assert g["counts"]["endpoints_unresolved"] == 1
        assert g["counts"]["tlf"] == 3
        assert g["counts"]["adam"] == 2
        assert g["counts"]["sdtm_absent"] == 1
        # Two planned tables with rendered output -> generated; the DV listing -> blocked.
        assert g["status"] == {"generated": 2, "blocked": 1, "needs-clarification": 0}


def test_join_edges_and_absent_domain() -> None:
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        g = _run(Path(tmp))
        node_ids = {n["id"] for n in g["nodes"]}
        for expected in ("obj:Objective_1", "end:Endpoint_1", "reg:ich-e3",
                         "tlf:eff-END1-ancova-wk24-locf", "adam:ADSL", "adam:ADQSADAS",
                         "sdtm:DM", "sdtm:QS", "sdtm:DV"):
            assert expected in node_ids, f"missing node {expected}"

        edges = {(e["source"], e["target"], e["kind"]) for e in g["edges"]}
        assert ("obj:Objective_1", "end:Endpoint_1", "obj-end") in edges
        assert ("end:Endpoint_1", "tlf:eff-END1-ancova-wk24-locf", "end-tlf") in edges
        assert ("tlf:eff-END1-ancova-wk24-locf", "adam:ADQSADAS", "tlf-adam") in edges
        assert ("adam:ADQSADAS", "sdtm:QS", "adam-sdtm") in edges
        assert ("reg:ich-e3", "tlf:disp-reg-disposition", "reg-tlf") in edges
        # Blocked listing declares DV but has no ADaM bridge -> dashed tlf-sdtm.
        dv_edge = next(e for e in g["edges"]
                       if e["target"] == "sdtm:DV" and e["kind"] == "tlf-sdtm")
        assert dv_edge["dashed"] is True

        dv = next(n for n in g["nodes"] if n["id"] == "sdtm:DV")
        assert dv["absent"] is True
        dm = next(n for n in g["nodes"] if n["id"] == "sdtm:DM")
        assert dm["absent"] is False


def test_issues_feed_and_embedded_artifacts() -> None:
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        g = _run(Path(tmp))
        severities = {i["severity"] for i in g["issues"]}
        assert "blocked" in severities        # DV-absent listing
        assert "clarification" in severities   # unresolved Endpoint_2
        assert "gap" in severities             # Objective_2 has no downstream TLF
        # Blocked listing issue points at its node.
        assert any(i["nodeId"] == "tlf:dev-reg-protocol-deviations" and i["severity"] == "blocked"
                   for i in g["issues"])

        # Rendered TLF + ARD are embedded in the TLF node meta (render-only agent reads them).
        eff = next(n for n in g["nodes"] if n["id"] == "tlf:eff-END1-ancova-wk24-locf")
        assert eff["status"] == "generated"
        assert eff["meta"]["generatedMd"] is not None
        assert eff["meta"]["ardJson"] is not None
        assert eff["meta"]["analysisSet"] == "Efficacy Population"

        # Unresolved endpoint carries the flag.
        end2 = next(n for n in g["nodes"] if n["id"] == "end:Endpoint_2")
        assert end2["unresolved"] is True


if __name__ == "__main__":
    test_counts_and_status_tallies()
    test_join_edges_and_absent_domain()
    test_issues_feed_and_embedded_artifacts()
    print("test_build_trace_graph: all passed")
