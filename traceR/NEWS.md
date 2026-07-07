# traceR 0.1.0

* Initial release.
* `build_trace()` assembles a typed objective→endpoint→analysis→output→result
  and ADaM→SDTM→CT traceability graph from USDM, ARS, define.xml and ARD.
* Source readers: `read_usdm()`, `read_ars()`, `read_define()` (define 1.0 &
  2.0), `read_ard()`.
* Query (`trace_path()`, `trace_ancestors()`/`trace_descendants()`,
  `trace_lineage()`), validation (`trace_gaps()`, `trace_coverage()`).
* Built-in executor for standard summary outputs (`execute_analysis()`,
  `execute_reporting_event()`) emitting the long-skinny ARD.
* CDISC Library client + reproducible snapshots (`cdisc_snapshot()`,
  `cl_product_variables()`) with an offline `snapshot_from_define()` fallback.
* Export (`trace_to_json()`, `trace_to_html()`) and a content-hashed
  reproducibility contract (`trace_manifest()`, `trace_verify()`).
* Bundled CDISCPILOT01 sample data (`cdiscpilot01_trace`, `cdiscpilot01_adsl`,
  `traceR_example()`).
