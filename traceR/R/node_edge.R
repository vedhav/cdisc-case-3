# The trace_graph S3 class ----------------------------------------------------

#' Construct a trace graph (or fragment)
#'
#' A `trace_graph` is the central traceR object: two typed tibbles, `nodes`
#' and `edges`, plus a `meta` list of provenance. Source readers
#' ([read_usdm()], [read_ars()], [read_define()], [read_ard()]) each return a
#' *fragment* (a `trace_graph` covering one source); [build_trace()] merges
#' fragments and resolves cross-source edges.
#'
#' @param nodes A tibble with columns `id`, `type`, `label`, `source`, `attrs`
#'   (a list-column of per-node metadata). Duplicated ids are de-duplicated,
#'   keeping the first and merging `attrs`.
#' @param edges A tibble with columns `from`, `to`, `rel`, `source`, `attrs`.
#' @param meta A named list of provenance (sources, hashes, snapshot version).
#' @return A `trace_graph`.
#' @export
trace_graph <- function(nodes = empty_nodes(), edges = empty_edges(),
                        meta = list()) {
  stopifnot(all(c("id", "type", "label") %in% names(nodes)))
  stopifnot(all(c("from", "to", "rel") %in% names(edges)))
  if (is.null(nodes$source)) nodes$source <- NA_character_
  if (is.null(nodes$attrs)) nodes$attrs <- vector("list", nrow(nodes))
  if (is.null(edges$source)) edges$source <- NA_character_
  if (is.null(edges$attrs)) edges$attrs <- vector("list", nrow(edges))
  nodes <- dedup_nodes(nodes)
  structure(
    list(nodes = tibble::as_tibble(nodes),
         edges = tibble::as_tibble(edges),
         meta = meta),
    class = "trace_graph"
  )
}

#' Test whether an object is a trace graph
#' @param x An object.
#' @return `TRUE` if `x` is a [trace_graph()].
#' @export
is_trace_graph <- function(x) inherits(x, "trace_graph")

# Keep first occurrence of each node id; union the attrs lists.
dedup_nodes <- function(nodes) {
  if (nrow(nodes) == 0 || !anyDuplicated(nodes$id)) return(nodes)
  keep <- !duplicated(nodes$id)
  nodes[keep, , drop = FALSE]
}

#' Merge trace graph fragments into one graph
#'
#' Unions nodes (de-duplicating ids) and edges (de-duplicating identical
#' `from`/`to`/`rel` triples). Provenance from each fragment is preserved.
#'
#' @param ... `trace_graph` fragments.
#' @param meta Extra provenance to attach to the merged graph.
#' @return A merged `trace_graph`.
#' @export
trace_merge <- function(..., meta = list()) {
  frags <- Filter(Negate(is.null), list(...))
  frags <- Filter(is_trace_graph, frags)
  if (length(frags) == 0) return(trace_graph(meta = meta))
  nodes <- dplyr::bind_rows(lapply(frags, `[[`, "nodes"))
  edges <- dplyr::bind_rows(lapply(frags, `[[`, "edges"))
  edges <- edges[!duplicated(edges[c("from", "to", "rel")]), , drop = FALSE]
  metas <- c(lapply(frags, `[[`, "meta"), list(meta))
  merged_meta <- Reduce(function(a, b) utils::modifyList(a, b), metas)
  # `sources` accumulates rather than being overwritten
  merged_meta$sources <- unique(unlist(lapply(metas, `[[`, "sources")))
  trace_graph(nodes, edges, merged_meta)
}

#' Accessors for a trace graph
#'
#' @param graph A `trace_graph`.
#' @param type Optional node type(s) to filter by.
#' @return A tibble of nodes / edges.
#' @export
trace_nodes <- function(graph, type = NULL) {
  stopifnot(is_trace_graph(graph))
  n <- graph$nodes
  if (!is.null(type)) n <- n[n$type %in% type, , drop = FALSE]
  n
}

#' @rdname trace_nodes
#' @param rel Optional relationship type(s) to filter by.
#' @export
trace_edges <- function(graph, rel = NULL) {
  stopifnot(is_trace_graph(graph))
  e <- graph$edges
  if (!is.null(rel)) e <- e[e$rel %in% rel, , drop = FALSE]
  e
}

#' @export
print.trace_graph <- function(x, ...) {
  cli::cli_h1("<trace_graph>")
  nt <- sort(table(x$nodes$type), decreasing = TRUE)
  et <- sort(table(x$edges$rel), decreasing = TRUE)
  cli::cli_text("{nrow(x$nodes)} nodes, {nrow(x$edges)} edges")
  if (length(nt)) {
    cli::cli_h3("nodes by type")
    for (i in seq_along(nt)) cli::cli_li("{names(nt)[i]}: {as.integer(nt[i])}")
  }
  if (length(et)) {
    cli::cli_h3("edges by relationship")
    for (i in seq_along(et)) cli::cli_li("{names(et)[i]}: {as.integer(et[i])}")
  }
  if (length(x$meta$sources)) {
    cli::cli_h3("sources")
    cli::cli_li(unlist(x$meta$sources))
  }
  invisible(x)
}

# Build an igraph view for path queries (directed).
as_igraph <- function(graph) {
  v <- graph$nodes
  e <- graph$edges
  # keep only edges whose endpoints exist as nodes
  ok <- e$from %in% v$id & e$to %in% v$id
  ig <- igraph::graph_from_data_frame(
    d = if (any(ok)) e[ok, c("from", "to", "rel")] else
      data.frame(from = character(), to = character(), rel = character()),
    vertices = v[c("id", "type", "label")],
    directed = TRUE
  )
  ig
}
