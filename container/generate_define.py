"""Generate a Define-XML 2.1 document for the derived ADaM datasets.

Runs as the `generate-define` script step, between `derive-adam` and the CDISC
CORE conformance gate (`validate-core`). It reads the ADaM spec produced by
`tlf-analysis-spec` (`adam-spec.json`) and the derived datasets under
`/workspace/adam/`, and emits a Define-XML 2.1 (`define.xml`) describing each
dataset (ItemGroupDef) and variable (ItemDef). The define is then handed to
CORE so conformance is checked against the metadata contract, not just the raw
data — the standard submission pattern.

This is a deterministic PRODUCER, not a gate: it never recomputes a statistic
and it is tolerant (a missing spec downgrades to a minimal, clearly-marked
define rather than crashing). It writes a summary result.json but has a single
unconditional outgoing transition.

Inputs (read from /workspace, /output fallback):
  adam-spec.json     datasets[] (name, class, variables[], parameters[], ...)
  /workspace/adam/   derived ADaM datasets (column headers reconcile the spec)

Outputs:
  /workspace/define.xml, /output/define.xml   the Define-XML 2.1 document
  /output/result.json                          { status, datasets, variables, ... }
"""

from __future__ import annotations

import csv
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

WORKSPACE = Path(os.environ.get("WORKSPACE_DIR", "/workspace"))
OUTPUT = Path(os.environ.get("OUTPUT_DIR", "/output"))
ADAM_DIR = WORKSPACE / "adam"

ODM_NS = "http://www.cdisc.org/ns/odm/v1.3"
DEF_NS = "http://www.cdisc.org/ns/def/v2.1"
XLINK_NS = "http://www.w3.org/1999/xlink"
XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"

CLASS_MAP = {
    "ADSL": "SUBJECT LEVEL ANALYSIS DATASET",
    "BDS": "BASIC DATA STRUCTURE",
    "OCCDS": "OCCURRENCE DATA STRUCTURE",
    "TTE": "BASIC DATA STRUCTURE",
}
NUMERIC_NAMES = {
    "AVAL", "BASE", "CHG", "PCHG", "AVALN", "BASEN", "ADY", "AGE", "AVISITN",
    "VISITNUM", "TRTPN", "TRTAN", "TRT01PN", "TRT01AN", "ASEQ", " AENDY", "ASTDY",
    "AENDY", "CNSR", "STUDYDURN", "SITEGR1N",
}


def load_json(name: str):
    for base in (WORKSPACE, OUTPUT):
        p = base / name
        if p.is_file():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass
    return None


def datasets_from_spec(spec) -> list[dict]:
    if isinstance(spec, dict):
        datasets = spec.get("datasets")
        if not isinstance(datasets, list):
            datasets = [v for v in spec.values() if isinstance(v, dict) and (v.get("name") or v.get("dataset"))]
    elif isinstance(spec, list):
        datasets = spec
    else:
        datasets = []

    out = []
    for d in datasets or []:
        if not isinstance(d, dict):
            continue
        name = str(d.get("name") or d.get("dataset") or d.get("id") or "").upper()
        if not name:
            continue
        klass = str(d.get("class") or d.get("klass") or d.get("structure") or "").upper()
        variables = []
        for v in d.get("variables", []) or []:
            if isinstance(v, dict):
                vname = str(v.get("name") or v.get("variable") or "").upper()
                role = v.get("role") or v.get("label") or ""
            else:
                vname, role = str(v).upper(), ""
            if vname:
                variables.append({"name": vname, "role": role})
        out.append({"name": name, "class": klass, "variables": variables,
                    "label": d.get("label") or d.get("description") or name})
    return out


def columns_from_data(dataset_name: str) -> list[str]:
    """Reconcile spec variables against the actual derived dataset header, so the
    define reflects what was produced (extra columns are captured too)."""
    for ext in ("csv",):
        p = ADAM_DIR / f"{dataset_name.lower()}.{ext}"
        if not p.is_file():
            p = ADAM_DIR / f"{dataset_name.upper()}.{ext}"
        if p.is_file():
            try:
                with p.open(newline="", encoding="utf-8", errors="replace") as fh:
                    header = next(csv.reader(fh), [])
                return [c.strip().upper() for c in header if c.strip()]
            except OSError:
                return []
    return []


def data_type(var_name: str) -> str:
    if var_name in NUMERIC_NAMES or var_name.endswith("DY") or var_name.endswith("FN"):
        return "integer"
    if var_name in {"AVAL", "BASE", "CHG", "PCHG"}:
        return "float"
    return "text"


def xml_escape(s: str) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def build_define(study_name: str, datasets: list[dict]) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    parts: list[str] = []
    parts.append('<?xml version="1.0" encoding="UTF-8"?>')
    parts.append(
        f'<ODM xmlns="{ODM_NS}" xmlns:def="{DEF_NS}" xmlns:xlink="{XLINK_NS}" '
        f'xmlns:xsi="{XSI_NS}" ODMVersion="1.3.2" FileType="Snapshot" '
        f'FileOID="MEDIFORCE.{xml_escape(study_name)}.DEFINE" '
        f'CreationDateTime="{now}" def:Context="Other">'
    )
    parts.append(f'  <Study OID="STDY.{xml_escape(study_name)}">')
    parts.append("    <GlobalVariables>")
    parts.append(f"      <StudyName>{xml_escape(study_name)}</StudyName>")
    parts.append(f"      <StudyDescription>{xml_escape(study_name)} analysis datasets</StudyDescription>")
    parts.append(f"      <ProtocolName>{xml_escape(study_name)}</ProtocolName>")
    parts.append("    </GlobalVariables>")
    parts.append(
        '    <MetaDataVersion OID="MDV.ADaM" Name="ADaM Metadata" '
        'Description="ADaM define generated by the cdisc-case-3 pipeline" '
        'def:DefineVersion="2.1.0">'
    )
    parts.append("      <def:Standards>")
    parts.append(
        '        <def:Standard OID="STD.ADaMIG" def:Name="ADAMIG" def:Type="IG" '
        'def:Version="1.3" def:Status="Final"/>'
    )
    parts.append("      </def:Standards>")

    item_defs: list[str] = []
    seen_items: set[str] = set()

    for d in datasets:
        ds = d["name"]
        klass = CLASS_MAP.get(d["class"], CLASS_MAP.get(ds, "BASIC DATA STRUCTURE"))
        var_names = [v["name"] for v in d["variables"]]
        for col in columns_from_data(ds):
            if col not in var_names:
                var_names.append(col)
        if not var_names:
            var_names = ["STUDYID", "USUBJID"]

        parts.append(
            f'      <ItemGroupDef OID="IG.{ds}" Name="{ds}" Repeating="No" '
            f'Purpose="Analysis" SASDatasetName="{ds}" def:Structure="One record per subject" '
            f'def:ArchiveLocationID="LF.{ds}" def:Class="{xml_escape(klass)}">'
        )
        parts.append(f'        <Description><TranslatedText xml:lang="en">{xml_escape(d["label"])}'
                     "</TranslatedText></Description>")
        for i, vn in enumerate(var_names, start=1):
            mandatory = "Yes" if vn in ("STUDYID", "USUBJID") else "No"
            parts.append(f'        <ItemRef ItemOID="IT.{ds}.{vn}" Mandatory="{mandatory}" '
                         f'OrderNumber="{i}"/>')
        parts.append(f'        <def:leaf ID="LF.{ds}" xlink:href="{ds.lower()}.csv">')
        parts.append(f'          <def:title>{ds.lower()}.csv</def:title>')
        parts.append("        </def:leaf>")
        parts.append("      </ItemGroupDef>")

        for vn in var_names:
            oid = f"IT.{ds}.{vn}"
            if oid in seen_items:
                continue
            seen_items.add(oid)
            dtype = data_type(vn)
            length = "8" if dtype in ("integer", "float") else "200"
            role = next((v["role"] for v in d["variables"] if v["name"] == vn), "")
            item_defs.append(
                f'      <ItemDef OID="{oid}" Name="{vn}" DataType="{dtype}" '
                f'Length="{length}" SASFieldName="{vn}">'
            )
            label = xml_escape(role) if role else vn
            item_defs.append(f'        <Description><TranslatedText xml:lang="en">{label}'
                             "</TranslatedText></Description>")
            origin = "Predecessor" if vn in ("STUDYID", "USUBJID") else "Derived"
            item_defs.append(f'        <def:Origin Type="{origin}"/>')
            item_defs.append("      </ItemDef>")

    parts.extend(item_defs)
    parts.append("    </MetaDataVersion>")
    parts.append("  </Study>")
    parts.append("</ODM>")
    return "\n".join(parts) + "\n"


def main() -> None:
    spec = load_json("adam-spec.json")
    study_model = load_json("study-model.json") or {}
    study = study_model.get("study") if isinstance(study_model, dict) else None
    study_name = "STUDY"
    if isinstance(study, dict):
        study_name = str(study.get("id") or study.get("name") or "STUDY")
    elif isinstance(study, str):
        study_name = study
    study_name = "".join(c for c in study_name if c.isalnum() or c in "._-") or "STUDY"

    datasets = datasets_from_spec(spec)
    status = "ok" if datasets else "no-spec"
    if not datasets:
        # Tolerant fallback: reconstruct from whatever derived data exists.
        for p in sorted(ADAM_DIR.glob("*.csv")) if ADAM_DIR.is_dir() else []:
            name = p.stem.upper()
            datasets.append({"name": name, "class": "", "variables": [], "label": name})
        status = "reconstructed-from-data" if datasets else "empty"

    define_xml = build_define(study_name, datasets)
    for base in (WORKSPACE, OUTPUT):
        base.mkdir(parents=True, exist_ok=True)
        (base / "define.xml").write_text(define_xml, encoding="utf-8")

    variable_count = sum(len(d["variables"]) or len(columns_from_data(d["name"])) for d in datasets)
    result = {
        "status": status,
        "study": study_name,
        "datasets": [d["name"] for d in datasets],
        "datasetCount": len(datasets),
        "variableCount": variable_count,
        "definePath": "/output/define.xml",
        "summary": f"Define-XML 2.1 generated for {len(datasets)} ADaM dataset(s)",
    }
    (OUTPUT / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"generate_define: {result['summary']} (status={status})", file=sys.stderr)
    sys.exit(0)


if __name__ == "__main__":
    main()
