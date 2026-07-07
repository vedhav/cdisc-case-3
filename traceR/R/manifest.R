# Reproducibility manifest -----------------------------------------------------

#' Build a reproducible run manifest for a trace graph
#'
#' The reproducibility contract: a content-hashed record that pins an
#' objective-to-result lineage to the exact inputs, node/edge content, metadata
#' snapshot and package version that produced it. Re-running [build_trace()] on
#' the same inputs yields the same graph hashes; the manifest lets a reviewer
#' verify that an AI-assisted run is reproducible by construction, and detect
#' drift when an input changes.
#'
#' @param graph A [trace_graph()] (typically from [build_trace()]).
#' @param inputs Optional named character vector of input file paths to hash
#'   (e.g. `c(usdm = "...", ars = "...")`). Files that exist are hashed by
#'   content; missing ones are recorded as `NA`.
#' @param path Optional output path for the manifest JSON.
#' @return A manifest list (invisibly written to `path` if given).
#' @export
trace_manifest <- function(graph, inputs = NULL, path = NULL) {
  stopifnot(is_trace_graph(graph))
  input_hashes <- NULL
  if (length(inputs)) {
    input_hashes <- lapply(inputs, function(f) {
      if (is.character(f) && file.exists(f))
        list(path = f, sha = digest::digest(file = f, algo = "sha256"),
             bytes = as.numeric(file.info(f)$size))
      else list(path = as.character(f)[1], sha = NA_character_)
    })
  }
  man <- list(
    tool = "traceR",
    tool_version = tryCatch(as.character(utils::packageVersion("traceR")),
                            error = function(e) "dev"),
    study = graph$meta$study %||% NA_character_,
    reporting_event = graph$meta$reporting_event %||% NA_character_,
    sources = graph$meta$sources %||% list(),
    snapshot = graph$meta$snapshot %||% NA,
    counts = list(
      nodes = nrow(graph$nodes), edges = nrow(graph$edges),
      by_type = as.list(table(graph$nodes$type)),
      by_rel = as.list(table(graph$edges$rel))
    ),
    graph_hashes = graph$meta$hashes %||% graph_hashes(graph),
    coverage = tryCatch(trace_coverage(graph), error = function(e) NULL),
    gaps = tryCatch(nrow(trace_gaps(graph)), error = function(e) NA_integer_),
    inputs = input_hashes
  )
  if (!is.null(path)) {
    writeLines(jsonlite::toJSON(man, auto_unbox = TRUE, null = "null",
                                pretty = TRUE, dataframe = "rows"), path)
    cli::cli_alert_success("Wrote manifest to {.file {path}}")
    return(invisible(man))
  }
  man
}

#' Verify a trace graph against a previously written manifest
#'
#' Recomputes the graph's content hashes and compares them to a manifest,
#' reporting whether the lineage is unchanged (reproducible) or has drifted.
#'
#' @param graph A [trace_graph()].
#' @param manifest A manifest list or a path to a manifest JSON.
#' @return A list with `reproducible` (logical) and per-hash comparison.
#' @export
trace_verify <- function(graph, manifest) {
  if (is.character(manifest)) manifest <- jsonlite::read_json(manifest)
  now <- graph_hashes(graph)
  was <- manifest$graph_hashes
  same <- identical(now$nodes, was$nodes %||% was[["nodes"]]) &&
          identical(now$edges, was$edges %||% was[["edges"]])
  list(
    reproducible = same,
    nodes = list(now = now$nodes, manifest = was$nodes %||% was[["nodes"]]),
    edges = list(now = now$edges, manifest = was$edges %||% was[["edges"]])
  )
}
