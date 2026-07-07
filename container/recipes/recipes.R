# =============================================================================
# Standard-output recipe library (the deterministic, validated path).
#
# Each recipe turns an ADaM data frame + ARS-derived bindings into (a) a
# long-skinny ARD and (b) a rendered display. The AGENT parameterises these
# recipes for the standard safety outputs it can bind; it does NOT edit them.
# Custom (efficacy) outputs are drafted by the agent as standalone programs
# that emit the SAME long-skinny ARD contract (see ard_long_schema()).
#
# Built on cards / cardx / gtsummary (see the cdisc-case-3 spike). Two gotchas
# baked in:
#   1. cards 0.7.x ARD columns (group1_level, variable_level, stat, fmt_fun)
#      are list-columns — always unpack before joining/writing.
#   2. cards computes N from nrow(filtered input). For AE frequency tables that
#      is subjects-with-an-event, NOT the ADSL population N — the percentage is
#      wrong unless you override the denominator with the ADSL big-N. Population
#      N ALWAYS comes from ADSL.
# =============================================================================

suppressMessages({
  library(cards)
  library(dplyr)
  library(gtsummary)
  library(gt)
})

# The long-skinny ARD contract. Recipes AND agent-drafted custom programs must
# emit exactly these columns so package.R can consolidate + write results back.
ard_long_schema <- function() {
  c("output_id", "analysis_id", "operation_id",
    "group_var", "group_level", "variable", "variable_level",
    "stat_name", "stat_label", "stat_raw", "stat_fmt")
}

# Unpack a cards ARD data frame into the long-skinny contract.
# operation_map: named character vector stat_name -> ARS operationId (optional).
ard_to_long <- function(ard, output_id, analysis_id, operation_map = character()) {
  df <- as.data.frame(ard)
  first_chr <- function(x) if (length(x) && !is.null(x[[1]])) as.character(x[[1]]) else NA_character_
  fmt_one <- function(fmt, val) {
    if (is.function(fmt)) {
      out <- tryCatch(as.character(fmt(val)), error = function(e) NA_character_)
      if (length(out)) out[[1]] else NA_character_
    } else {
      first_chr(list(val))
    }
  }
  n <- nrow(df)
  has_var_level <- "variable_level" %in% names(df)
  out <- data.frame(
    output_id = rep(output_id, n),
    analysis_id = rep(analysis_id, n),
    group_var = if ("group1" %in% names(df)) vapply(df$group1, function(x) if (is.null(x)) NA_character_ else as.character(x)[[1]], character(1)) else NA_character_,
    group_level = if ("group1_level" %in% names(df)) vapply(df$group1_level, first_chr, character(1)) else NA_character_,
    variable = as.character(df$variable),
    variable_level = if (has_var_level) vapply(df$variable_level, first_chr, character(1)) else NA_character_,
    stat_name = as.character(df$stat_name),
    stat_label = if ("stat_label" %in% names(df)) as.character(df$stat_label) else as.character(df$stat_name),
    stringsAsFactors = FALSE
  )
  out$stat_raw <- vapply(seq_len(n), function(i) first_chr(df$stat[i]), character(1))
  out$stat_fmt <- vapply(seq_len(n), function(i) {
    fmt <- if ("fmt_fun" %in% names(df)) df$fmt_fun[[i]] else NULL
    fmt_one(fmt, df$stat[[i]])
  }, character(1))
  out$operation_id <- if (length(operation_map)) unname(operation_map[out$stat_name]) else NA_character_
  out[, ard_long_schema()]
}

# Persist one output's ARD + rendered display under work_dir/{ard,tfl}.
write_output <- function(long, gt_obj, output_id, work_dir, figure = NULL) {
  ard_dir <- file.path(work_dir, "ard")
  tfl_dir <- file.path(work_dir, "tfl")
  dir.create(ard_dir, recursive = TRUE, showWarnings = FALSE)
  dir.create(tfl_dir, recursive = TRUE, showWarnings = FALSE)
  write.csv(long, file.path(ard_dir, paste0(output_id, ".csv")), row.names = FALSE, na = "")
  if (!is.null(gt_obj)) {
    html <- gt::as_raw_html(gt_obj)
    writeLines(html, file.path(tfl_dir, paste0(output_id, ".html")))
  }
  if (!is.null(figure)) {
    ggplot2::ggsave(file.path(tfl_dir, paste0(output_id, ".png")), figure,
                    width = 9, height = 6, dpi = 300)
  }
  invisible(TRUE)
}

# --- Recipe: demographics / baseline characteristics -------------------------
recipe_demographics <- function(adsl, output_id, analysis_id,
                                group_var = "TRT01P",
                                cont_vars = c("AGE"),
                                cat_vars = c("SEX", "RACE"),
                                cont_stats = c("N", "mean", "sd", "median", "p25", "p75", "min", "max"),
                                operation_map = character()) {
  ard <- ard_stack(
    data = adsl,
    .by = all_of(group_var),
    ard_continuous(variables = all_of(cont_vars),
                   statistic = ~ continuous_summary_fns(cont_stats)),
    ard_categorical(variables = all_of(cat_vars))
  )
  tbl <- tbl_ard_summary(cards = ard, by = all_of(group_var),
                         include = all_of(c(cont_vars, cat_vars)))
  long <- ard_to_long(ard, output_id, analysis_id, operation_map)
  list(long = long, gt = as_gt(tbl), ard = ard)
}

# --- Recipe: continuous / categorical summary by group (disposition, labs) ---
recipe_summary_by_group <- function(data, output_id, analysis_id,
                                    group_var = "TRT01P",
                                    cont_vars = character(),
                                    cat_vars = character(),
                                    cont_stats = c("N", "mean", "sd", "median", "p25", "p75", "min", "max"),
                                    operation_map = character()) {
  # Use ard_stack (it injects `data` into each layer and handles the grouping);
  # standalone ard_continuous(by=) hits a broken fmt path in cards 0.7.x.
  has_cont <- length(cont_vars) > 0
  has_cat <- length(cat_vars) > 0
  ard <- if (has_cont && has_cat) {
    ard_stack(data = data, .by = all_of(group_var),
              ard_continuous(variables = all_of(cont_vars), statistic = ~ continuous_summary_fns(cont_stats)),
              ard_categorical(variables = all_of(cat_vars)))
  } else if (has_cont) {
    ard_stack(data = data, .by = all_of(group_var),
              ard_continuous(variables = all_of(cont_vars), statistic = ~ continuous_summary_fns(cont_stats)))
  } else {
    ard_stack(data = data, .by = all_of(group_var),
              ard_categorical(variables = all_of(cat_vars)))
  }
  tbl <- tbl_ard_summary(cards = ard, by = all_of(group_var),
                         include = all_of(c(cont_vars, cat_vars)))
  long <- ard_to_long(ard, output_id, analysis_id, operation_map)
  list(long = long, gt = as_gt(tbl), ard = ard)
}

# --- Recipe: count of subjects per group (population header, e.g. An01_05) ---
# data_pop: the analysis population (one row per subject, or de-duplicated on
# USUBJID). Emits one `n` row per group. op_n: the ARS operationId for the count.
recipe_count_subjects <- function(data_pop, output_id, analysis_id,
                                   group_var = "TRT01A", op_n = NA_character_,
                                   id_var = "USUBJID") {
  ids <- if (id_var %in% names(data_pop)) {
    data_pop %>% distinct(.data[[id_var]], .data[[group_var]])
  } else data_pop
  counts <- ids %>% count(.data[[group_var]], name = "n")
  long <- data.frame(
    output_id = output_id, analysis_id = analysis_id, operation_id = op_n,
    group_var = group_var, group_level = as.character(counts[[group_var]]),
    variable = id_var, variable_level = NA_character_,
    stat_name = "n", stat_label = "N", stat_raw = as.character(counts$n),
    stat_fmt = as.character(counts$n), stringsAsFactors = FALSE)
  long[, ard_long_schema()]
}

# --- Recipe: subjects with >=1 event of interest, % over ADSL N --------------
# events: ADAE already restricted to the population AND the event subset (the
# executor applies the dataSubset filters). adsl_pop: population denominator.
# Emits n + p per group for a single "any event" indicator (the output variable
# is the event category, labelled by the analysis).
recipe_ae_overall <- function(events, adsl_pop, output_id, analysis_id,
                              group_var = "TRT01A", label = "Subjects with event",
                              operation_map = character(), id_var = "USUBJID") {
  big_n <- adsl_pop %>% distinct(.data[[id_var]], .data[[group_var]]) %>%
    count(.data[[group_var]], name = "N_arm")
  subj <- events %>% distinct(.data[[id_var]], .data[[group_var]]) %>%
    count(.data[[group_var]], name = "n")
  d <- big_n %>% left_join(subj, by = group_var) %>%
    mutate(n = ifelse(is.na(n), 0L, n), pct = ifelse(N_arm > 0, n / N_arm * 100, NA_real_))
  op_n <- unname(operation_map["n"]); op_p <- unname(operation_map["p"])
  bind_rows(
    data.frame(output_id = output_id, analysis_id = analysis_id, operation_id = op_n %||% NA_character_,
               group_var = group_var, group_level = as.character(d[[group_var]]),
               variable = label, variable_level = NA_character_,
               stat_name = "n", stat_label = "n", stat_raw = as.character(d$n),
               stat_fmt = as.character(d$n), stringsAsFactors = FALSE),
    data.frame(output_id = output_id, analysis_id = analysis_id, operation_id = op_p %||% NA_character_,
               group_var = group_var, group_level = as.character(d[[group_var]]),
               variable = label, variable_level = NA_character_,
               stat_name = "p", stat_label = "%", stat_raw = as.character(round(d$pct, 4)),
               stat_fmt = sprintf("%.1f", d$pct), stringsAsFactors = FALSE)
  )[, ard_long_schema()]
}

# --- Recipe: hierarchical AE table (SOC/PT) with ADSL denominator ------------
# adae: ADAE already restricted to the population AND the TEAE subset by the
# executor. adsl_pop: ADSL population (denominator source). Counts subjects with
# >=1 event; percentage uses ADSL N. `level` selects which rows to stamp/return:
#   "soc"   -> System Organ Class rows, stamped soc_analysis_id
#   "pt"    -> Preferred Term rows,      stamped pt_analysis_id
#   "socpt" -> both
recipe_ae_soc_pt <- function(adae, adsl_pop, output_id, analysis_id,
                             group_var = "TRT01A",
                             soc_var = "AESOC", pt_var = "AEDECOD",
                             teae_flag = "TRTEMFL",
                             level = "socpt",
                             soc_analysis_id = analysis_id,
                             pt_analysis_id = analysis_id,
                             operation_map = character()) {
  unlist_col <- function(x) vapply(x, function(v) if (is.null(v)) NA_character_ else as.character(v)[[1]], character(1))
  big_n <- adsl_pop %>% count(.data[[group_var]], name = "N_arm")

  teae <- adae
  if (teae_flag %in% names(adae)) teae <- teae %>% filter(.data[[teae_flag]] == "Y")
  teae <- teae %>% select(all_of(c("USUBJID", group_var, soc_var, pt_var))) %>% distinct()

  count_level <- function(subject_level, var) {
    ard <- ard_categorical(data = subject_level, variables = all_of(var),
                           by = all_of(group_var), statistic = ~ c("n", "N", "p"))
    df <- as.data.frame(ard) %>%
      mutate(arm = unlist_col(group1_level),
             level = unlist_col(variable_level))
    # Override denominator with ADSL big-N; recompute percentage.
    n_rows <- df %>% filter(stat_name == "n") %>%
      mutate(n_val = as.numeric(vapply(stat, function(s) as.character(s)[[1]], character(1)))) %>%
      left_join(big_n, by = c("arm" = group_var)) %>%
      mutate(pct = ifelse(N_arm > 0, n_val / N_arm * 100, NA_real_))
    n_rows
  }

  soc <- count_level(teae %>% select(all_of(c("USUBJID", group_var, soc_var))) %>% distinct(), soc_var)
  pt <- teae %>% group_by(.data[[soc_var]]) %>%
    group_modify(~ count_level(.x %>% select(all_of(c("USUBJID", group_var, pt_var))) %>% distinct(), pt_var)) %>%
    ungroup()

  `%||%` <- function(a, b) if (length(a) && !is.na(a)) a else b
  to_long <- function(d, level_name, aid) {
    if (is.null(d) || !nrow(d)) return(NULL)
    bind_rows(
      data.frame(output_id = output_id, analysis_id = aid,
                 operation_id = unname(operation_map["n"])[1] %||% NA_character_,
                 group_var = group_var, group_level = d$arm,
                 variable = level_name, variable_level = d$level,
                 stat_name = "n", stat_label = "n",
                 stat_raw = as.character(d$n_val), stat_fmt = as.character(d$n_val),
                 stringsAsFactors = FALSE),
      data.frame(output_id = output_id, analysis_id = aid,
                 operation_id = unname(operation_map["p"])[1] %||% NA_character_,
                 group_var = group_var, group_level = d$arm,
                 variable = level_name, variable_level = d$level,
                 stat_name = "p", stat_label = "%",
                 stat_raw = as.character(round(d$pct, 4)), stat_fmt = sprintf("%.1f", d$pct),
                 stringsAsFactors = FALSE)
    )
  }
  parts <- list()
  if (level %in% c("soc", "socpt")) parts <- c(parts, list(to_long(soc, "AESOC", soc_analysis_id)))
  if (level %in% c("pt", "socpt"))  parts <- c(parts, list(to_long(pt %>% rename(soc = 1), "AEDECOD", pt_analysis_id)))
  long <- bind_rows(parts)
  long <- long[, ard_long_schema()]

  # A simple gt of the SOC-level counts for the rendered display.
  disp <- soc %>% transmute(`System Organ Class` = level, Arm = arm,
                            `n (%)` = sprintf("%d (%.1f)", as.integer(n_val), pct)) %>%
    tidyr::pivot_wider(names_from = Arm, values_from = `n (%)`)
  list(long = long, gt = gt::gt(disp), ard_soc = soc, ard_pt = pt, big_n = big_n)
}
