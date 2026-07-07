# Execution layer: ARS analysis -> long-skinny ARD ----------------------------

#' The long-skinny ARD column contract
#'
#' Every result traceR produces (and every result [read_ard()] consumes) uses
#' these columns, so results are portable and each cell carries the ARS
#' `analysis_id`/`operation_id` lineage.
#' @return A character vector of column names.
#' @export
ard_long_schema <- function() {
  c("output_id", "analysis_id", "operation_id", "group_var", "group_level",
    "variable", "variable_level", "stat_name", "stat_label", "stat_raw", "stat_fmt")
}

empty_ard <- function() {
  m <- matrix(character(), nrow = 0, ncol = length(ard_long_schema()),
              dimnames = list(NULL, ard_long_schema()))
  tibble::as_tibble(m)
}

# Attribute accessor for a node id.
node_attr <- function(graph, id, field) {
  i <- match(id, graph$nodes$id)
  if (is.na(i)) return(NULL)
  graph$nodes$attrs[[i]][[field]]
}

# Operations of the method used by an analysis, as (id, label) rows.
analysis_operations <- function(graph, analysis_id) {
  aid <- resolve_node(graph, analysis_id)
  e <- graph$edges
  mid <- e$to[e$from == aid & e$rel == "uses_method"]
  if (!length(mid)) return(tibble::tibble(id = character(), label = character()))
  ops <- e$to[e$from %in% mid & e$rel == "has_operation"]
  tibble::tibble(id = sub("^operation:", "", ops),
                 label = graph$nodes$label[match(ops, graph$nodes$id)])
}

# Map a cards stat_name to an ARS operation id by keyword.
map_operation <- function(stat_name, ops) {
  if (!nrow(ops)) return(NA_character_)
  kw <- list(n = "count|number|n\\b|frequency", N = "\\bN\\b|population|total",
             p = "percent|%|proportion", mean = "mean", sd = "standard deviation|std|sd",
             median = "median", min = "min", max = "max", q1 = "q1|first quartile",
             q3 = "q3|third quartile")
  pat <- kw[[stat_name]] %||% stat_name
  hit <- which(grepl(pat, ops$label, ignore.case = TRUE))
  if (length(hit)) ops$id[hit[1]] else ops$id[1]
}

# Heuristic population filter from an analysis set id/label.
population_filter <- function(graph, analysis_id) {
  aid <- resolve_node(graph, analysis_id)
  e <- graph$edges
  pid <- e$to[e$from == aid & e$rel == "in_population"]
  lab <- paste(sub("^population:", "", pid),
               graph$nodes$label[match(pid, graph$nodes$id)])
  if (grepl("SAF", lab, ignore.case = TRUE)) return("SAFFL")
  if (grepl("ITT", lab, ignore.case = TRUE)) return("ITTFL")
  if (grepl("EFF", lab, ignore.case = TRUE)) return("EFFFL")
  NA_character_
}

# Treatment/grouping variable for an analysis.
grouping_var <- function(graph, analysis_id) {
  aid <- resolve_node(graph, analysis_id)
  e <- graph$edges
  gids <- e$to[e$from == aid & e$rel == "grouped_by"]
  for (g in gids) {
    gv <- node_attr(graph, g, "groupingVariable")
    if (!is.null(gv) && !is.na(gv)) return(gv)
  }
  NULL
}

#' Execute one ARS analysis into a long-skinny ARD
#'
#' Binds the analysis's dataset, variable, treatment grouping and population
#' straight from the trace graph, loads the matching ADaM CSV from `adam_dir`,
#' and computes the statistics with the `cards` engine. Supported shapes:
#' subject counts by group (variable `USUBJID`), a continuous summary by group,
#' and a categorical summary by group. Model-based / hierarchical outputs
#' (ANCOVA, MMRM, Kaplan-Meier, AE-by-SOC/PT) are out of scope for the built-in
#' executor and return `NULL` with a reason attribute — they are the
#' AI-drafted, human-reviewed path handled by the sibling ars-to-tfl workflow.
#'
#' @param graph A [trace_graph()] built from USDM+ARS(+define).
#' @param analysis_id An ARS analysis reference.
#' @param adam_dir Directory of ADaM CSVs (lowercase `<dataset>.csv`).
#' @param output_id Optional output id to stamp on the ARD (else resolved from
#'   the graph's `displayed_in` edge).
#' @return A long-skinny ARD tibble, or `NULL` if unsupported.
#' @export
execute_analysis <- function(graph, analysis_id, adam_dir, output_id = NULL) {
  rlang::check_installed("cards", "for execute_analysis()")
  aid_full <- resolve_node(graph, analysis_id)
  aid <- sub("^analysis:", "", aid_full)
  dataset <- node_attr(graph, aid_full, "dataset")
  variable <- node_attr(graph, aid_full, "variable")
  if (is.null(dataset) || is.na(dataset))
    return(unsupported("analysis has no dataset binding"))

  csv <- file.path(adam_dir, paste0(tolower(dataset), ".csv"))
  if (!file.exists(csv)) return(unsupported(sprintf("ADaM file not found: %s", csv)))
  dat <- utils::read.csv(csv, stringsAsFactors = FALSE)

  # population filter
  pf <- population_filter(graph, aid_full)
  if (!is.na(pf) && pf %in% names(dat)) dat <- dat[dat[[pf]] == "Y", , drop = FALSE]

  gv <- grouping_var(graph, aid_full)
  if (is.null(gv) || !(gv %in% names(dat))) {
    gv <- intersect(c("TRT01P", "TRTA", "TRTP", "ARM"), names(dat))[1]
  }
  if (is.na(gv)) return(unsupported("no usable grouping variable"))

  if (is.null(output_id)) {
    e <- graph$edges
    oid <- e$to[e$from == aid_full & e$rel == "displayed_in"]
    output_id <- if (length(oid)) sub("^output:", "", oid[1]) else NA_character_
  }
  ops <- analysis_operations(graph, aid_full)

  # dispatch on the variable
  if (identical(variable, "USUBJID") || is.null(variable) || is.na(variable)) {
    ard <- cards::ard_categorical(dat, by = dplyr::all_of(gv),
                                  variables = dplyr::all_of(gv))
    ard$variable <- "USUBJID"; ard$variable_level <- NA
  } else if (!variable %in% names(dat)) {
    return(unsupported(sprintf("variable %s absent from %s", variable, dataset)))
  } else if (is.numeric(dat[[variable]])) {
    ard <- cards::ard_continuous(dat, by = dplyr::all_of(gv),
                                 variables = dplyr::all_of(variable))
  } else {
    ard <- cards::ard_categorical(dat, by = dplyr::all_of(gv),
                                  variables = dplyr::all_of(variable))
  }
  cards_to_long(ard, output_id = output_id, analysis_id = aid, group_var = gv, ops = ops)
}

unsupported <- function(reason) {
  structure(list(), reason = reason, class = "traceR_unsupported")
}
is_unsupported <- function(x) inherits(x, "traceR_unsupported") || is.null(x)

# Convert a cards ARD to the long-skinny contract with ARS ids.
cards_to_long <- function(ard, output_id, analysis_id, group_var, ops) {
  df <- as.data.frame(ard, stringsAsFactors = FALSE)
  keep <- df$stat_name %in% c("n", "N", "p", "mean", "sd", "median", "min",
                              "max", "q1", "q3", "var")
  df <- df[keep, , drop = FALSE]
  if (!nrow(df)) return(empty_ard())
  fmt <- function(name, x) {
    x <- suppressWarnings(as.numeric(x))
    if (name == "p") sprintf("%.1f%%", 100 * x)
    else if (name %in% c("mean", "sd", "median", "q1", "q3")) sprintf("%.1f", x)
    else format(round(x, 3))
  }
  tibble::tibble(
    output_id = output_id, analysis_id = analysis_id,
    operation_id = vapply(df$stat_name, map_operation, character(1), ops = ops),
    group_var = group_var,
    group_level = as.character(df$group1_level %||% NA),
    variable = as.character(df$variable),
    variable_level = as.character(df$variable_level %||% NA),
    stat_name = df$stat_name,
    stat_label = as.character(df$stat_label %||% df$stat_name),
    stat_raw = vapply(df$stat, function(v) as.character(v)[1], character(1)),
    stat_fmt = mapply(fmt, df$stat_name, df$stat, USE.NAMES = FALSE)
  )
}

#' Execute all supported analyses in a reporting event
#'
#' Loops the ARS analyses in the graph, executes the ones the built-in engine
#' supports (see [execute_analysis()]), writes per-analysis ARDs if `ard_dir`
#' is given, and returns the consolidated long-skinny ARD plus a per-analysis
#' status table. Merge the results back with `build_trace(..., ard = <ard>)` to
#' close the objective-to-result loop.
#'
#' @param graph A [trace_graph()].
#' @param adam_dir Directory of ADaM CSVs.
#' @param ard_dir Optional directory to write `<analysis_id>.csv` files.
#' @return A list with `ard` (consolidated tibble) and `status` (tibble).
#' @export
execute_reporting_event <- function(graph, adam_dir, ard_dir = NULL) {
  aids <- graph$nodes$id[graph$nodes$type == "analysis"]
  if (!is.null(ard_dir)) dir.create(ard_dir, showWarnings = FALSE, recursive = TRUE)
  results <- list(); status <- list()
  for (a in aids) {
    aid <- sub("^analysis:", "", a)
    res <- tryCatch(execute_analysis(graph, a, adam_dir),
                    error = function(e) unsupported(conditionMessage(e)))
    if (is_unsupported(res)) {
      status[[length(status) + 1]] <- tibble::tibble(
        analysis_id = aid, status = "unsupported",
        reason = attr(res, "reason") %||% "unsupported", n_rows = 0L)
      next
    }
    results[[length(results) + 1]] <- res
    if (!is.null(ard_dir) && nrow(res))
      utils::write.csv(res, file.path(ard_dir, paste0(aid, ".csv")), row.names = FALSE)
    status[[length(status) + 1]] <- tibble::tibble(
      analysis_id = aid, status = if (nrow(res)) "executed" else "empty",
      reason = NA_character_, n_rows = nrow(res))
  }
  ard <- if (length(results)) dplyr::bind_rows(results) else empty_ard()
  cli::cli_alert_info("Executed {sum(sapply(results, nrow) > 0)}/{length(aids)} analyses ({nrow(ard)} ARD rows).")
  list(ard = ard, status = dplyr::bind_rows(status))
}
