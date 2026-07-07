# Validating a trace graph -----------------------------------------------------

#' Detect traceability gaps
#'
#' Walks the graph for the structural holes that break objective-to-result
#' traceability, returning them as a tidy table so they can be triaged or
#' gated in a pipeline. Detected gaps include:
#'
#' * an objective with no endpoint;
#' * an endpoint not linked to any output (`evaluated_by` missing);
#' * an output that displays no analysis (`displayed_in` missing);
#' * an analysis with no method, no population, or that produces no result;
#' * an analysis whose `operates_on` variable is not defined in any define.xml
#'   (an *unbound* ADaM variable — present only as an inferred stub);
#' * a `derived_from` predecessor variable referenced but never defined.
#'
#' @param graph A [trace_graph()].
#' @return A tibble with `id`, `type`, `gap`, `severity`.
#' @export
trace_gaps <- function(graph) {
  stopifnot(is_trace_graph(graph))
  n <- graph$nodes; e <- graph$edges
  gap <- function(ids, type, msg, sev = "warning") {
    if (!length(ids)) return(NULL)
    tibble::tibble(id = ids, type = type, gap = msg, severity = sev)
  }
  has_out <- function(ids, rel) ids %in% e$from[e$rel %in% rel]
  has_in  <- function(ids, rel) ids %in% e$to[e$rel %in% rel]

  obj <- n$id[n$type == "objective"]
  end <- n$id[n$type == "endpoint"]
  out <- n$id[n$type == "output"]
  ana <- n$id[n$type == "analysis"]
  stubs <- n$id[vapply(n$attrs, function(a) isTRUE(a$stub), logical(1))]

  res <- dplyr::bind_rows(
    gap(obj[!has_out(obj, "has_endpoint")], "objective",
        "objective has no endpoint"),
    gap(end[!has_out(end, "evaluated_by")], "endpoint",
        "endpoint not linked to any output", "info"),
    gap(out[!has_in(out, "displayed_in")], "output",
        "output displays no analysis"),
    gap(ana[!has_out(ana, "uses_method")], "analysis",
        "analysis has no method"),
    gap(ana[!has_out(ana, "in_population")], "analysis",
        "analysis has no population/analysis-set"),
    gap(ana[!has_out(ana, "produces")], "analysis",
        "analysis produced no result (not yet executed)", "info"),
    gap(intersect(stubs, unique(e$to[e$rel == "operates_on"])), "adam_var",
        "analysis operates on a variable not defined in define.xml", "error"),
    gap(intersect(stubs, unique(e$to[e$rel == "derived_from"])), "sdtm_var",
        "predecessor variable referenced but not defined", "info")
  )
  if (is.null(res) || !nrow(res)) return(tibble::tibble(
    id = character(), type = character(), gap = character(), severity = character()))
  # attach labels
  res$label <- n$label[match(res$id, n$id)]
  res[c("id", "type", "label", "gap", "severity")]
}

#' Objective-to-result coverage summary
#'
#' For each objective, reports how much of the lineage is realised: how many
#' endpoints, outputs, analyses and results are reachable, and whether the
#' objective reaches at least one executed result. This is the "did we actually
#' answer the question we set out to answer" view.
#'
#' @param graph A [trace_graph()].
#' @return A tibble, one row per objective.
#' @export
trace_coverage <- function(graph) {
  stopifnot(is_trace_graph(graph))
  ig <- as_igraph(graph)
  n <- graph$nodes
  objs <- n$id[n$type == "objective"]
  reach_type <- function(oid, type) {
    if (!oid %in% igraph::V(ig)$name) return(character())
    comp <- names(igraph::subcomponent(ig, oid, mode = "all"))
    intersect(comp, n$id[n$type == type])
  }
  rows <- lapply(objs, function(oid) {
    tibble::tibble(
      objective = oid,
      label = n$label[match(oid, n$id)],
      level = vapply(oid, function(i) n$attrs[[match(i, n$id)]]$level %||% NA_character_, character(1)),
      n_endpoints = length(reach_type(oid, "endpoint")),
      n_outputs   = length(reach_type(oid, "output")),
      n_analyses  = length(reach_type(oid, "analysis")),
      n_results   = length(reach_type(oid, "result")),
      reaches_result = length(reach_type(oid, "result")) > 0
    )
  })
  dplyr::bind_rows(rows)
}
