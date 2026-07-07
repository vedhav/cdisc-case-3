# traceR

<!-- badges: start -->
<!-- badges: end -->

**Metadata-driven, reproducible objective-to-result traceability for CDISC
studies.**

traceR reads the machine-readable CDISC metadata that describes a study end to
end — the **USDM** study definition (objectives, endpoints, estimands), the
**ARS** Reporting Event (analyses, outputs, methods, operations), the
**define.xml** for **SDTM** and **ADaM** (datasets, variables, derivations,
controlled terminology), and the resulting **ARD** — and assembles them into a
single typed **traceability graph**. You can then walk the lineage from an
objective down to the SDTM variable that fed a result, validate coverage and
detect gaps, execute the standard analyses into an ARD, and export a
content-hashed traceable artifact.

> The hard part of these standards is not the data — it's proving that a given
> result actually answers a given objective, reproducibly. traceR makes that
> lineage explicit and hashable, so AI-assisted automation on top of it becomes
> **reproducible by construction**.

## Install

```r
# from a local clone
pak::local_install("traceR")      # or devtools::install("traceR")
```

## The model

A `trace_graph` is two typed tibbles — `nodes` and `edges` — plus provenance.
Node ids are namespaced `"<type>:<source-id>"` so fragments from different
sources merge cleanly.

```
objective ─has_endpoint→ endpoint ─evaluated_by→ output ←displayed_in─ analysis
                                                                          │
   uses_method → method ─has_operation→ operation                        │
   in_population → population                                            operates_on
   grouped_by → grouping                                                  ↓
   subset_by → datasubset                                              adam_var ─in_dataset→ adam_dataset
   produces → result ←yields─ operation                                   │
                                                                     derived_from
                                                                          ↓
                                                                       sdtm_var ─in_dataset→ sdtm_dataset
                                                                          │
                                                                     uses_codelist → codelist
```

## Quick start

```r
library(traceR)

g <- build_trace(
  usdm   = traceR_example("usdm_trace.json"),
  ars    = traceR_example("reporting_event.json"),
  define = list(adam = traceR_example("define_adam.xml"),
                sdtm = traceR_example("define_sdtm.xml"))
)
g
#> <trace_graph> — 989 nodes, 1628 edges

# walk objective -> output
trace_path(g, "Objective_2", "Out14-3-1-1")

# ADaM -> SDTM predecessor lineage
trace_descendants(g, "adam_var:ADAE.TRTAN", rel = "derived_from")

# coverage & gaps
trace_coverage(g)
trace_gaps(g)

# execute the standard analyses into a long-skinny ARD
ex <- execute_reporting_event(g, dirname(traceR_example("adsl.csv")))

# reproducibility
man <- trace_manifest(g, "traceability_manifest.json")
trace_verify(g, man)$reproducible

# interactive artifact
trace_to_html(g, "traceability.html")
```

A prebuilt graph (`cdiscpilot01_trace`) and `cdiscpilot01_adsl` ship as data.

## Function map

| Area | Functions |
|------|-----------|
| Read sources | `read_usdm()`, `read_ars()`, `read_define()`, `read_ard()` |
| Assemble | `build_trace()`, `trace_merge()`, `trace_graph()` |
| Query | `trace_path()`, `trace_ancestors()`, `trace_descendants()`, `trace_lineage()`, `trace_nodes()`, `trace_edges()` |
| Validate | `trace_gaps()`, `trace_coverage()` |
| Execute | `execute_analysis()`, `execute_reporting_event()`, `ard_long_schema()` |
| Standards metadata | `cdisc_snapshot()`, `cl_product_variables()`, `snapshot_from_define()`, `load_snapshot()`, `annotate_standard()` |
| Export | `trace_to_json()`, `trace_to_html()` |
| Reproducibility | `trace_manifest()`, `trace_verify()` |
| Examples | `traceR_example()`, `cdiscpilot01_trace`, `cdiscpilot01_adsl` |

## CDISC Library

`cdisc_snapshot("sdtmig", "3-4")` downloads the exhaustive published variable
catalogue by following the API's links (metadata-driven — no hardcoded domain
list) and caches a **versioned snapshot** for reproducibility. It needs a CDISC
Library **member** API key in `CDISC_LIBRARY_API_KEY`. Without one,
`snapshot_from_define()` derives the same snapshot schema from a study's
define.xml, fully offline.

## Relationship to cdisc-case-3

traceR is the standalone, reusable R engine behind the objective→result
traceability shown in the cdisc-case-3 ARS→TFL workflow. The workflow *executes*
a Reporting Event into TFLs with an AI-drafted path for custom efficacy outputs;
traceR provides the deterministic, hashable **traceability spine** and a
built-in executor for the standard summary outputs. Model-based and hierarchical
outputs (ANCOVA, MMRM, Kaplan-Meier, AE by SOC/PT) remain the AI-drafted,
human-reviewed path in that workflow.

## Sources

- CDISC SDTM/ADaM pilot project (CDISCPILOT01)
- DDF-RA USDM examples (CDISC_Pilot)
- CDISC ARS v1.0 Common Safety Displays example
