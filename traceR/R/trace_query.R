# Querying a trace graph -------------------------------------------------------

# Resolve a user-supplied node reference to a node id. Accepts a full
# namespaced id ("analysis:An01..."), a bare source id ("An01..."), or a
# label substring match. Errors if ambiguous or absent.
resolve_node <- function(graph, ref) {
  if (ref %in% graph$nodes$id) return(ref)
  hit <- graph$nodes$id[sub("^[^:]+:", "", graph$nodes$id) == ref]
  if (length(hit) == 1) return(hit)
  if (length(hit) > 1)
    cli::cli_abort(c("Ambiguous node reference {.val {ref}}.",
                     i = "Matches: {.val {hit}}"))
  lab <- graph$nodes$id[grepl(ref, graph$nodes$label, fixed = TRUE)]
  if (length(lab) == 1) return(lab)
  if (length(lab) > 1)
    cli::cli_abort(c("Ambiguous label reference {.val {ref}}.",
                     i = "Matches {length(lab)} nodes; use a node id."))
  cli::cli_abort("No node matching {.val {ref}}.")
}

#' Trace the lineage path between two nodes
#'
#' Finds a path connecting `from` to `to`. Because lineage runs in mixed
#' directions across sources (an analysis points *to* its output, an objective
#' points *to* its endpoint), the search is undirected by default so
#' "objective to result" style queries just work.
#'
#' @param graph A [trace_graph()].
#' @param from,to Node references: a full id, a bare source id, or a unique
#'   label substring.
#' @param directed If `TRUE`, respect edge direction.
#' @return A tibble of the ordered nodes on the path (empty if unreachable),
#'   with the connecting relationship in `via`.
#' @export
trace_path <- function(graph, from, to, directed = FALSE) {
  stopifnot(is_trace_graph(graph))
  fi <- resolve_node(graph, from); ti <- resolve_node(graph, to)
  ig <- as_igraph(graph)
  sp <- suppressWarnings(igraph::shortest_paths(
    ig, from = fi, to = ti,
    mode = if (directed) "out" else "all", output = "vpath"))
  vids <- names(sp$vpath[[1]])
  if (!length(vids)) return(graph$nodes[0, ])
  out <- graph$nodes[match(vids, graph$nodes$id), ]
  # annotate the relationship used to reach each node
  via <- rep(NA_character_, nrow(out))
  for (i in seq_len(nrow(out) - 1)) {
    e <- graph$edges
    hit <- e$rel[(e$from == vids[i] & e$to == vids[i + 1]) |
                 (e$from == vids[i + 1] & e$to == vids[i])]
    if (length(hit)) via[i + 1] <- hit[1]
  }
  out$via <- via
  out
}

# Generic neighbourhood walk in one direction.
walk_dir <- function(graph, ref, mode, rel = NULL, order = 50L) {
  fi <- resolve_node(graph, ref)
  g2 <- if (is.null(rel)) graph else
    structure(list(nodes = graph$nodes,
                   edges = graph$edges[graph$edges$rel %in% rel, , drop = FALSE],
                   meta = graph$meta), class = "trace_graph")
  ig <- as_igraph(g2)
  if (!fi %in% igraph::V(ig)$name) return(graph$nodes[0, ])
  nb <- igraph::ego(ig, order = order, nodes = fi, mode = mode)[[1]]
  ids <- setdiff(names(nb), fi)
  graph$nodes[match(ids, graph$nodes$id), ]
}

#' Ancestors and descendants of a node
#'
#' `trace_descendants()` follows edges *out* of a node (e.g. an objective down
#' to its endpoints, outputs, analyses, results); `trace_ancestors()` follows
#' edges *in* (e.g. a result back up to the objective). Optionally restrict to
#' particular relationship types.
#'
#' @param graph A [trace_graph()].
#' @param ref A node reference (see [trace_path()]).
#' @param rel Optional relationship type(s) to restrict the walk to.
#' @return A tibble of reachable nodes.
#' @export
trace_descendants <- function(graph, ref, rel = NULL)
  walk_dir(graph, ref, mode = "out", rel = rel)

#' @rdname trace_descendants
#' @export
trace_ancestors <- function(graph, ref, rel = NULL)
  walk_dir(graph, ref, mode = "in", rel = rel)

#' Extract the full lineage subgraph reachable from a node
#'
#' Returns the induced subgraph of everything connected to `ref` (undirected
#' reachability) — the complete traceable neighbourhood of, say, one objective
#' or one output. Handy for focused export.
#'
#' @param graph A [trace_graph()].
#' @param ref A node reference.
#' @return A `trace_graph` containing `ref` and all connected nodes/edges.
#' @export
trace_lineage <- function(graph, ref) {
  fi <- resolve_node(graph, ref)
  ig <- as_igraph(graph)
  comp <- names(igraph::subcomponent(ig, fi, mode = "all"))
  nodes <- graph$nodes[graph$nodes$id %in% comp, , drop = FALSE]
  edges <- graph$edges[graph$edges$from %in% comp & graph$edges$to %in% comp, , drop = FALSE]
  trace_graph(nodes, edges, meta = c(graph$meta, list(lineage_of = fi)))
}
