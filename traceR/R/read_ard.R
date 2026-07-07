#' Read a long-skinny Analysis Results Dataset (ARD) into a trace fragment
#'
#' Reads the reusable results-by-row ARD (the contract emitted by the
#' cdisc-case-3 executor and by [execute_analysis()]): one row per statistic with
#' columns `output_id, analysis_id, operation_id, group_var, group_level,
#' variable, variable_level, stat_name, stat_label, stat_raw, stat_fmt`.
#'
#' One `result` node is created per `analysis_id` (carrying every stat row in
#' its `attrs$stats` for querying), with a `produces` edge from the analysis
#' and `yields` edges from each contributing operation. This closes the
#' objective to result loop in the graph.
#'
#' @param path Path to the ARD CSV (or a data frame already read in).
#' @return A [trace_graph()] fragment with `result` nodes.
#' @export
read_ard <- function(path) {
  ard <- if (is.data.frame(path)) path else
    utils::read.csv(path, stringsAsFactors = FALSE, check.names = TRUE)
  src <- if (is.character(path)) paste0("ard:", basename(path)) else "ard:inline"
  req <- c("output_id", "analysis_id")
  if (!all(req %in% names(ard)))
    cli::cli_abort("ARD is missing required columns: {.field {setdiff(req, names(ard))}}")

  nodes <- list(); edges <- list()
  for (aid in unique(ard$analysis_id)) {
    if (is.na(aid) || !nzchar(aid)) next
    rows <- ard[ard$analysis_id == aid, , drop = FALSE]
    rid <- nid("result", aid)
    nodes[[length(nodes) + 1]] <- tibble::tibble(
      id = rid, type = "result",
      label = paste0(nrow(rows), " stats"), source = src,
      attrs = list(list(output_id = unique(rows$output_id),
                        n_stats = nrow(rows), stats = rows)))
    edges[[length(edges) + 1]] <- tibble::tibble(
      from = nid("analysis", aid), to = rid, rel = "produces",
      source = src, attrs = list(list()))
    ops <- unique(rows$operation_id[!is.na(rows$operation_id) & nzchar(rows$operation_id)])
    for (op in ops)
      edges[[length(edges) + 1]] <- tibble::tibble(
        from = nid("operation", op), to = rid, rel = "yields",
        source = src, attrs = list(list()))
  }

  trace_graph(
    nodes = bind_nodes(dplyr::bind_rows(nodes)),
    edges = bind_edges(dplyr::bind_rows(edges)),
    meta = list(sources = list(src))
  )
}
