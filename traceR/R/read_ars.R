#' Read a CDISC ARS Reporting Event into a trace graph fragment
#'
#' Ingests an Analysis Results Standard (ARS) v1.0 `ReportingEvent` JSON:
#' its analyses, outputs, methods and operations, analysis sets, groupings and
#' data subsets. Edges capture the analysis wiring — which method, population,
#' groupings and subset each analysis uses, which ADaM `dataset.variable` it
#' operates on, and (by walking `mainListOfContents`) which output displays it.
#'
#' ADaM variable nodes are created with the id scheme `adam_var:<DATASET>.<VAR>`
#' so they merge with the nodes produced by [read_define()].
#'
#' @param path Path to the ARS Reporting Event JSON.
#' @return A [trace_graph()] fragment.
#' @export
read_ars <- function(path) {
  x <- jsonlite::read_json(path)
  src <- paste0("ars:", basename(path))
  nodes <- list(); edges <- list()
  add_n <- function(...) nodes[[length(nodes) + 1]] <<- tibble::tibble(...)
  add_e <- function(from, to, rel, attrs = list()) {
    edges[[length(edges) + 1]] <<- tibble::tibble(
      from = from, to = to, rel = rel, source = src, attrs = list(attrs))
  }

  # --- outputs ---
  for (o in x$outputs %||% list()) {
    add_n(id = nid("output", o$id), type = "output", label = scalar_chr(o$name),
          source = src, attrs = list(list(version = o$version %||% NA)))
  }

  # --- methods + operations ---
  for (m in x$methods %||% list()) {
    mid <- nid("method", m$id)
    add_n(id = mid, type = "method", label = scalar_chr(m$name %||% m$label),
          source = src, attrs = list(list(description = scalar_chr(m$description))))
    for (op in m$operations %||% list()) {
      opid <- nid("operation", op$id)
      add_n(id = opid, type = "operation",
            label = scalar_chr(op$name %||% op$label), source = src,
            attrs = list(list(resultPattern = scalar_chr(op$resultPattern))))
      add_e(mid, opid, "has_operation")
    }
  }

  # --- analysis sets (as populations), groupings, data subsets ---
  for (a in x$analysisSets %||% list()) {
    add_n(id = nid("population", a$id), type = "population",
          label = scalar_chr(a$label %||% a$name), source = src,
          attrs = list(list(kind = "analysisSet")))
  }
  for (g in x$analysisGroupings %||% list()) {
    add_n(id = nid("grouping", g$id), type = "grouping",
          label = scalar_chr(g$label %||% g$name), source = src,
          attrs = list(list(groupingVariable = scalar_chr(g$groupingVariable),
                            dataset = scalar_chr(g$groupingDataset))))
  }
  for (d in x$dataSubsets %||% list()) {
    add_n(id = nid("datasubset", d$id), type = "datasubset",
          label = scalar_chr(d$label %||% d$name), source = src, attrs = list(list()))
  }

  # --- analyses + their wiring ---
  for (a in x$analyses %||% list()) {
    aid <- nid("analysis", a$id)
    add_n(id = aid, type = "analysis", label = scalar_chr(a$name), source = src,
          attrs = list(list(dataset = scalar_chr(a$dataset),
                            variable = scalar_chr(a$variable),
                            purpose = code_text(a$purpose),
                            reason = code_text(a$reason))))
    if (!is.null(a$methodId))    add_e(aid, nid("method", a$methodId), "uses_method")
    if (!is.null(a$analysisSetId)) add_e(aid, nid("population", a$analysisSetId), "in_population")
    if (!is.null(a$dataSubsetId)) add_e(aid, nid("datasubset", a$dataSubsetId), "subset_by")
    for (og in a$orderedGroupings %||% list()) {
      if (!is.null(og$groupingId))
        add_e(aid, nid("grouping", og$groupingId), "grouped_by",
              attrs = list(order = og$order %||% NA))
    }
    # analysis operates on an ADaM variable (dataset.variable)
    if (!is.null(a$dataset) && !is.null(a$variable)) {
      ds <- scalar_chr(a$dataset); vr <- scalar_chr(a$variable)
      add_n(id = nid("adam_dataset", ds), type = "adam_dataset", label = ds,
            source = src, attrs = list(list()))
      vid <- nid("adam_var", paste0(ds, ".", vr))
      add_n(id = vid, type = "adam_var", label = paste0(ds, ".", vr),
            source = src, attrs = list(list(dataset = ds, variable = vr)))
      add_e(vid, nid("adam_dataset", ds), "in_dataset")
      add_e(aid, vid, "operates_on")
    }
  }

  # --- output -> analysis, from the mainListOfContents tree ---
  loc_edges <- walk_loc(x$mainListOfContents, src)
  for (le in loc_edges) add_e(le$analysis, le$output, "displayed_in")

  trace_graph(
    nodes = bind_nodes(dplyr::bind_rows(nodes)),
    edges = bind_edges(dplyr::bind_rows(edges)),
    meta = list(sources = list(src),
                reporting_event = scalar_chr(x$name %||% x$id))
  )
}

# Recursively walk mainListOfContents, tracking the nearest ancestor outputId,
# and emit (analysis, output) pairs for every analysisId found beneath it.
walk_loc <- function(loc, src) {
  out <- list()
  rec <- function(items, cur_output) {
    for (it in items %||% list()) {
      if (!is.null(it$outputId)) cur_output <- it$outputId
      if (!is.null(it$analysisId) && !is.null(cur_output)) {
        out[[length(out) + 1]] <<- list(
          analysis = nid("analysis", it$analysisId),
          output = nid("output", cur_output))
      }
      if (!is.null(it$sublist)) rec(it$sublist$listItems, cur_output)
    }
  }
  # top level: contentsList$listItems
  rec(dig(loc, "contentsList", "listItems"), NULL)
  out
}
