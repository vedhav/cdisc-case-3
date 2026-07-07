#!/usr/bin/env Rscript
# =============================================================================
# Step 5 (run-standard): execute the resolved recipe plan. DETERMINISTIC, NO LLM.
#
# This step writes NO analysis logic of its own. classify_outputs.py already
# decided which recipe runs over which data with which bindings and which real
# ARS analysis id; run_standard.R is a dumb executor that loads the ADaM, applies
# the population + subset filters, calls the fixed recipe, and writes the
# long-skinny ARD + a rendered display for every STANDARD output. The validated
# recipe library (recipes.R) is the only place statistics are computed.
#
# Reads:  <work>/standard_plan.json  (from classify)  + <adam>/*.csv
# Writes: <work>/ard/<outputId>.csv, <work>/tfl/<outputId>.html
#         and updates <work>/coverage.json status/repairs for each standard output
#
# Usage: Rscript run_standard.R --plan <work>/standard_plan.json \
#           --coverage <work>/coverage.json --adam <adam> --work <work>
# =============================================================================
if (nzchar(Sys.getenv("RLIB"))) .libPaths(c(Sys.getenv("RLIB"), .libPaths()))
suppressMessages({library(dplyr); library(jsonlite); library(cards); library(gt); library(gtsummary); library(tidyr)})

args <- commandArgs(trailingOnly = TRUE)
get_arg <- function(flag, default) { i <- match(flag, args); if (!is.na(i) && i < length(args)) args[[i + 1]] else default }
RECIPES <- Sys.getenv("RECIPES", get_arg("--recipes", "/app/container/recipes"))
plan_path <- get_arg("--plan", "/workspace/standard_plan.json")
cov_path <- get_arg("--coverage", "/workspace/coverage.json")
bind_path <- get_arg("--bindings", "/workspace/bindings.json")
adam_dir <- get_arg("--adam", "/workspace/adam")
work <- get_arg("--work", "/workspace")
source(file.path(RECIPES, "recipes.R"))
`%||%` <- function(a, b) if (!is.null(a) && length(a) && !is.na(a[[1]])) a else b

dir.create(file.path(work, "ard"), recursive = TRUE, showWarnings = FALSE)
dir.create(file.path(work, "tfl"), recursive = TRUE, showWarnings = FALSE)

plan <- fromJSON(plan_path, simplifyVector = FALSE)
coverage <- fromJSON(cov_path, simplifyVector = FALSE)

# --- ADaM loader (cache) -----------------------------------------------------
.adam_cache <- new.env()
load_adam <- function(name) {
  key <- toupper(name)
  if (!is.null(.adam_cache[[key]])) return(.adam_cache[[key]])
  f <- file.path(adam_dir, paste0(tolower(name), ".csv"))
  df <- if (file.exists(f)) read.csv(f, stringsAsFactors = FALSE, check.names = FALSE) else NULL
  .adam_cache[[key]] <- df
  df
}

# --- filter application (EQ / IN / NE), character-compared for robustness ----
apply_filter <- function(df, f) {
  v <- f$variable
  if (is.null(v) || !(v %in% names(df))) return(df)
  vals <- as.character(unlist(f$value))
  col <- as.character(df[[v]])
  cmp <- f$comparator %||% "EQ"
  keep <- switch(cmp,
    "EQ" = col %in% vals,
    "IN" = col %in% vals,
    "NE" = !(col %in% vals),
    "NOTIN" = !(col %in% vals),
    col %in% vals)
  df[keep & !is.na(keep), , drop = FALSE]
}
apply_filters <- function(df, filters) { for (f in filters) df <- apply_filter(df, f); df }

as_opmap <- function(x) { if (is.null(x) || !length(x)) return(character()); setNames(as.character(unlist(x)), names(x)) }

# --- generic display: pivot an output's long ARD into a gt (always renderable)
render_ard_gt <- function(long, title) {
  if (is.null(long) || !nrow(long)) return(gt::gt(data.frame(Note = "no results")))
  d <- long %>%
    mutate(Row = ifelse(is.na(variable_level) | variable_level == "",
                        paste0(variable, " — ", stat_label),
                        paste0(variable, " ", variable_level, " — ", stat_label))) %>%
    select(Row, group_level, stat_fmt)
  wide <- tryCatch(
    tidyr::pivot_wider(d, names_from = group_level, values_from = stat_fmt,
                       values_fn = function(x) paste(unique(x), collapse = "; ")),
    error = function(e) data.frame(Row = "results", stringsAsFactors = FALSE))
  gt::gt(wide) %>% gt::tab_header(title = gt::md(title))
}

# --- population helpers ------------------------------------------------------
adsl_population <- function(pop_filter) {
  adsl <- load_adam("ADSL")
  if (is.null(adsl)) stop("ADSL not staged")
  if (!is.null(pop_filter)) adsl <- apply_filter(adsl, pop_filter)
  adsl
}
restrict_to_pop <- function(df, adsl_pop, id_var = "USUBJID") {
  if (id_var %in% names(df) && id_var %in% names(adsl_pop))
    df[as.character(df[[id_var]]) %in% as.character(adsl_pop[[id_var]]), , drop = FALSE] else df
}

# --- execute one block -> long ARD rows --------------------------------------
run_block <- function(b, notes) {
  oid <- b$output_id; aid <- b$analysis_id; gv <- b$group_var %||% "TRT01A"
  opmap <- as_opmap(b$operation_map)
  adsl_pop <- adsl_population(b$pop_filter)

  if (b$recipe == "count_subjects") {
    return(recipe_count_subjects(adsl_pop, oid, aid, group_var = gv, op_n = opmap[["n"]] %||% NA_character_))
  }
  if (b$recipe == "summary_categorical") {
    r <- recipe_summary_by_group(adsl_pop, oid, aid, group_var = gv,
                                 cat_vars = b$variable, operation_map = opmap)
    return(r$long)
  }
  if (b$recipe == "summary_continuous") {
    df <- load_adam(b$dataset); if (is.null(df)) stop(paste(b$dataset, "not staged"))
    df <- restrict_to_pop(df, adsl_pop)
    df <- apply_filters(df, b$subset_filters)
    # If several parameters remain (e.g. vital signs), summarise the most frequent
    # one so the display is coherent; record which was chosen (surfaced, not hidden).
    if ("PARAMCD" %in% names(df) && dplyr::n_distinct(df$PARAMCD) > 1) {
      pick <- names(sort(table(df$PARAMCD), decreasing = TRUE))[1]
      df <- df[df$PARAMCD == pick, , drop = FALSE]
      notes$msg <- c(notes$msg, sprintf("%s: collapsed %s to PARAMCD=%s", aid, b$dataset, pick))
    }
    if (!(b$variable %in% names(df)) || all(is.na(df[[b$variable]])))
      stop(sprintf("%s has no non-missing values in %s (spec references it, data does not populate it)", b$variable, b$dataset))
    df <- df[!is.na(df[[b$variable]]), , drop = FALSE]
    r <- recipe_summary_by_group(df, oid, aid, group_var = gv,
                                 cont_vars = b$variable, operation_map = opmap)
    return(r$long)
  }
  if (b$recipe == "ae_overall") {
    ev <- load_adam(b$dataset); if (is.null(ev)) stop(paste(b$dataset, "not staged"))
    ev <- restrict_to_pop(ev, adsl_pop)
    ev <- apply_filters(ev, b$subset_filters)
    return(recipe_ae_overall(ev, adsl_pop, oid, aid, group_var = gv,
                             label = analysis_label(aid), operation_map = opmap))
  }
  if (b$recipe == "ae_soc_pt") {
    ev <- load_adam(b$dataset); if (is.null(ev)) stop(paste(b$dataset, "not staged"))
    ev <- restrict_to_pop(ev, adsl_pop)
    ev <- apply_filters(ev, b$subset_filters)
    r <- recipe_ae_soc_pt(ev, adsl_pop, oid, aid, group_var = gv, level = b$level %||% "socpt",
                          soc_analysis_id = aid, pt_analysis_id = aid, operation_map = opmap)
    return(r$long)
  }
  stop(paste("unknown recipe", b$recipe))
}

# analysis id -> human label, from bindings.json (falls back to the id)
.an_labels <- new.env()
if (file.exists(bind_path)) {
  .bind <- fromJSON(bind_path, simplifyVector = FALSE)
  for (aid in names(.bind$analyses)) .an_labels[[aid]] <- .bind$analyses[[aid]]$name %||% aid
}
analysis_label <- function(aid) (.an_labels[[aid]]) %||% aid

# --- main loop ---------------------------------------------------------------
status_by_output <- list()
for (po in plan$outputs) {
  oid <- po$output_id
  notes <- new.env(); notes$msg <- character()
  longs <- list()
  for (b in po$blocks) {
    res <- tryCatch(run_block(b, notes), error = function(e) {
      notes$msg <- c(notes$msg, sprintf("%s (%s) failed: %s", b$analysis_id, b$recipe, conditionMessage(e)))
      NULL
    })
    if (!is.null(res) && nrow(res)) longs[[length(longs) + 1]] <- res
  }
  long <- if (length(longs)) bind_rows(longs) else data.frame()
  ard_ok <- FALSE; tfl_ok <- FALSE
  if (nrow(long)) {
    long <- long[, ard_long_schema()]
    write.csv(long, file.path(work, "ard", paste0(oid, ".csv")), row.names = FALSE, na = "")
    ard_ok <- TRUE
    title <- oid
    gtobj <- tryCatch(render_ard_gt(long, title), error = function(e) NULL)
    if (!is.null(gtobj)) {
      html <- tryCatch(gt::as_raw_html(gtobj), error = function(e) NULL)
      if (!is.null(html)) { writeLines(html, file.path(work, "tfl", paste0(oid, ".html"))); tfl_ok <- TRUE }
    }
  }
  status_by_output[[oid]] <- list(rendered = ard_ok && tfl_ok, notes = notes$msg,
                                  ardRows = nrow(long))
  cat(sprintf("  %-14s blocks=%d  ardRows=%d  rendered=%s\n", oid, length(po$blocks), nrow(long), ard_ok && tfl_ok))
  if (length(notes$msg)) for (m in notes$msg) cat("      note:", m, "\n")
}

# --- write run status back into coverage.json --------------------------------
for (i in seq_along(coverage$outputs)) {
  oid <- coverage$outputs[[i]]$outputId
  st <- status_by_output[[oid]]
  if (!is.null(st)) {
    coverage$outputs[[i]]$status <- if (isTRUE(st$rendered)) "rendered" else "failed"
    coverage$outputs[[i]]$ardRows <- st$ardRows
    if (length(st$notes)) coverage$outputs[[i]]$repairs <- as.list(st$notes)
  }
}
write_json(coverage, cov_path, auto_unbox = TRUE, pretty = TRUE, null = "null")
n_ok <- sum(vapply(status_by_output, function(s) isTRUE(s$rendered), logical(1)))
cat(sprintf("run-standard: %d standard output(s) rendered.\n", n_ok))
