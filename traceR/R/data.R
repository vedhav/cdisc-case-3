# Bundled sample data + example accessors -------------------------------------

#' CDISCPILOT01 traceability graph (prebuilt)
#'
#' A [trace_graph()] built from the bundled CDISC pilot metadata — the USDM
#' objectives/endpoints, the ARS Common Safety Displays Reporting Event, and the
#' ADaM + SDTM define.xml. Use it to explore the query, validation and export
#' functions without re-parsing the sources. Rebuild with
#' `data-raw/make_sample_data.R`.
#'
#' @format A `trace_graph` with ~989 nodes and ~1628 edges.
#' @source CDISC SDTM/ADaM pilot project (CDISCPILOT01) and DDF-RA USDM example.
"cdiscpilot01_trace"

#' CDISCPILOT01 subject-level analysis dataset (ADSL)
#'
#' The ADaM ADSL for the CDISC pilot study, bundled as sample data for the
#' execution examples.
#'
#' @format A tibble, one row per subject.
#' @source CDISC SDTM/ADaM pilot project (CDISCPILOT01).
"cdiscpilot01_adsl"

#' Paths to bundled example source files
#'
#' traceR ships a curated set of raw CDISC pilot source files in
#' `inst/extdata` (the ARS Reporting Event, USDM trace, ADaM CSVs, ADaM/SDTM
#' define.xml, and offline standards snapshots). This returns their paths.
#'
#' @param name Optional file name (e.g. `"reporting_event.json"`,
#'   `"define_adam.xml"`). If `NULL`, all example files are listed.
#' @return A file path (for `name`) or a named character vector of all example
#'   paths.
#' @export
#' @examples
#' traceR_example()                       # list everything
#' traceR_example("reporting_event.json") # one path
traceR_example <- function(name = NULL) {
  root <- system.file("extdata", package = "traceR")
  if (!nzchar(root)) root <- file.path("inst", "extdata")
  all <- list.files(root, recursive = TRUE, full.names = TRUE)
  names(all) <- sub(paste0("^", root, "/?"), "", all)
  if (is.null(name)) return(all)
  hit <- all[basename(all) == name | names(all) == name]
  if (!length(hit)) cli::cli_abort("No example file {.val {name}}. See {.code traceR_example()}.")
  unname(hit[1])
}
