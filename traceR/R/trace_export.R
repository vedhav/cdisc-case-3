# Exporting a trace graph ------------------------------------------------------

#' Palette for node types (used by HTML/JSON export and legends)
#' @export
trace_palette <- function() {
  c(objective = "#7c3aed", endpoint = "#a855f7", estimand = "#c084fc",
    population = "#64748b", output = "#0ea5e9", analysis = "#2563eb",
    method = "#1d4ed8", operation = "#3b82f6", grouping = "#0891b2",
    datasubset = "#0e7490", result = "#16a34a",
    adam_dataset = "#ea580c", adam_var = "#f97316",
    sdtm_dataset = "#b45309", sdtm_var = "#d97706", codelist = "#9ca3af")
}

#' Serialise a trace graph to JSON
#'
#' Emits a portable `{nodes, edges, meta}` document (the same shape the
#' interactive viewer and downstream tools consume). Node `attrs` are inlined.
#'
#' @param graph A [trace_graph()].
#' @param path Optional output path; if `NULL`, returns the JSON string.
#' @return Invisibly, the path (or the JSON string if `path` is `NULL`).
#' @export
trace_to_json <- function(graph, path = NULL) {
  stopifnot(is_trace_graph(graph))
  doc <- list(
    nodes = purrr::pmap(graph$nodes[c("id", "type", "label", "source", "attrs")],
                        function(id, type, label, source, attrs)
                          c(list(id = id, type = type, label = label, source = source),
                            attrs)),
    edges = purrr::pmap(graph$edges[c("from", "to", "rel", "source")],
                        function(from, to, rel, source)
                          list(from = from, to = to, rel = rel, source = source)),
    meta = graph$meta
  )
  js <- jsonlite::toJSON(doc, auto_unbox = TRUE, null = "null", pretty = TRUE)
  if (is.null(path)) return(invisible(js))
  writeLines(js, path)
  cli::cli_alert_success("Wrote trace JSON to {.file {path}}")
  invisible(path)
}

#' Render an interactive traceability graph to HTML
#'
#' Builds a self-contained interactive network (via visNetwork) coloured by
#' node type, with a legend and click-to-focus, and writes it to `path`. This
#' is the human-facing traceable artifact -- the objective-to-result lineage a
#' reviewer can explore.
#'
#' @param graph A [trace_graph()].
#' @param path Output HTML path.
#' @param title Page title.
#' @param hierarchical Use a left-to-right hierarchical layout.
#' @return Invisibly, `path`.
#' @export
trace_to_html <- function(graph, path, title = "traceR: objective to result",
                          hierarchical = FALSE) {
  stopifnot(is_trace_graph(graph))
  rlang::check_installed("visNetwork", "for trace_to_html()")
  pal <- trace_palette()
  nn <- graph$nodes
  vis_nodes <- data.frame(
    id = nn$id,
    label = ifelse(nchar(nn$label) > 40, paste0(substr(nn$label, 1, 38), "..."), nn$label),
    group = nn$type,
    title = paste0("<b>", nn$type, "</b><br>", nn$id, "<br>", nn$label),
    color = unname(pal[nn$type]),
    stringsAsFactors = FALSE
  )
  ee <- graph$edges
  vis_edges <- data.frame(
    from = ee$from, to = ee$to, label = ee$rel,
    arrows = "to", font.size = 0, title = ee$rel,
    stringsAsFactors = FALSE
  )
  net <- visNetwork::visNetwork(vis_nodes, vis_edges, main = title,
                                width = "100%", height = "800px")
  net <- visNetwork::visOptions(net, highlightNearest = list(enabled = TRUE, degree = 2, hover = TRUE),
                                nodesIdSelection = TRUE, selectedBy = "group")
  net <- visNetwork::visLegend(net, useGroups = TRUE, width = 0.12, position = "left")
  net <- visNetwork::visEdges(net, smooth = list(enabled = TRUE, type = "cubicBezier"))
  if (hierarchical)
    net <- visNetwork::visHierarchicalLayout(net, direction = "LR", sortMethod = "directed")
  else
    net <- visNetwork::visPhysics(net, stabilization = TRUE,
                                  barnesHut = list(gravitationalConstant = -8000))
  visNetwork::visSave(net, file = path, selfcontained = TRUE)
  cli::cli_alert_success("Wrote interactive trace to {.file {path}}")
  invisible(path)
}
