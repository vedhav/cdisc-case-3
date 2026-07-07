#' traceR: Metadata-Driven, Reproducible Objective-to-Result Traceability
#'
#' traceR assembles a typed traceability graph that connects a clinical
#' study's Objectives and Endpoints (USDM) to the Analyses and Outputs that
#' address them (ARS), to the Results they produce (ARD), and down to the
#' ADaM and SDTM variables and Controlled Terminology that fed them
#' (define.xml + CDISC Library). It validates the lineage, detects gaps,
#' executes standard analyses into ARDs, and exports reproducible,
#' content-hashed traceability artifacts.
#'
#' The core object is a [trace_graph()]: a set of typed `nodes` and typed
#' `edges` assembled by [build_trace()] from source readers ([read_usdm()],
#' [read_ars()], [read_define()], [read_ard()]). Query it with
#' [trace_path()], [trace_ancestors()], [trace_descendants()]; validate it
#' with [trace_gaps()] and [trace_coverage()]; export it with
#' [trace_to_json()] / [trace_to_html()]; and pin it with [trace_manifest()].
#'
#' @keywords internal
"_PACKAGE"

## usethis namespace: start
#' @importFrom rlang check_installed
## usethis namespace: end
NULL

# Node type vocabulary --------------------------------------------------------

#' Controlled vocabulary of traceR node and edge types
#'
#' traceR uses a fixed vocabulary so graphs assembled from different sources
#' compose. Node ids are namespaced as `"<type>:<source-id>"` (see [nid()]).
#'
#' @format A list with `node_types` and `edge_types` character vectors.
#' @export
trace_vocab <- list(
  node_types = c(
    "objective", "endpoint", "estimand", "population",
    "analysis", "method", "operation", "output",
    "grouping", "datasubset", "result",
    "adam_dataset", "adam_var", "sdtm_dataset", "sdtm_var", "codelist"
  ),
  edge_types = c(
    "has_endpoint",   # objective -> endpoint
    "assesses",       # estimand  -> endpoint
    "in_population",  # estimand/analysis -> population
    "evaluated_by",   # endpoint  -> output   (endpoint->output bridge)
    "displayed_in",   # analysis  -> output
    "uses_method",    # analysis  -> method
    "has_operation",  # method    -> operation
    "grouped_by",     # analysis  -> grouping
    "subset_by",      # analysis  -> datasubset
    "operates_on",    # analysis  -> adam_var
    "in_dataset",     # var       -> dataset
    "derived_from",   # adam_var  -> sdtm_var / adam_var (predecessor)
    "uses_codelist",  # var       -> codelist
    "produces",       # analysis  -> result
    "yields"          # operation -> result
  )
)
