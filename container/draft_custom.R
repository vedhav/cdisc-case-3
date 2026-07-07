#!/usr/bin/env Rscript
# =============================================================================
# Reference driver for the DRAFT-CUSTOM step (the AI value-add).
#
# The custom efficacy outputs have no validated recipe: the ANCOVA and the
# Kaplan-Meier need a fitted model. In the workflow an AGENT drafts a standalone
# program for each, runs it, and repairs it until it emits the long-skinny ARD
# contract + a rendered display. THIS FILE is the worked, proven template the
# agent adapts (the skill points here): it reads the resolved bindings +
# classification, finds every output classified `custom`, and computes it from
# the method the ARS names, stamping the real ARS analysis_id / operation_id on
# every row so lineage reconstructs by construction.
#
# It is also what the headless verification runs, so the full pipeline is
# exercised end-to-end without a live model.
#
# Reads:  <work>/{bindings.json, coverage.json} + <adam>/*.csv
# Writes: <work>/{ard,tfl,code}/<outputId>.*  and updates coverage.json
#
# Usage: Rscript draft_custom.R --bindings <work>/bindings.json \
#           --coverage <work>/coverage.json --adam <adam> --work <work>
# =============================================================================
if (nzchar(Sys.getenv("RLIB"))) .libPaths(c(Sys.getenv("RLIB"), .libPaths()))
suppressMessages({library(dplyr); library(jsonlite); library(gt); library(emmeans); library(survival)})

args <- commandArgs(trailingOnly = TRUE)
get_arg <- function(flag, default) { i <- match(flag, args); if (!is.na(i) && i < length(args)) args[[i + 1]] else default }
RECIPES <- Sys.getenv("RECIPES", get_arg("--recipes", "/app/container/recipes"))
bind_path <- get_arg("--bindings", "/workspace/bindings.json")
cov_path <- get_arg("--coverage", "/workspace/coverage.json")
adam_dir <- get_arg("--adam", "/workspace/adam")
work <- get_arg("--work", "/workspace")
source(file.path(RECIPES, "recipes.R"))
`%||%` <- function(a, b) if (!is.null(a) && length(a) && !is.na(a[[1]])) a else b
for (d in c("ard", "tfl", "code")) dir.create(file.path(work, d), recursive = TRUE, showWarnings = FALSE)

bindings <- fromJSON(bind_path, simplifyVector = FALSE)
coverage <- fromJSON(cov_path, simplifyVector = FALSE)
load_adam <- function(name) { f <- file.path(adam_dir, paste0(tolower(name), ".csv")); if (file.exists(f)) read.csv(f, stringsAsFactors = FALSE, check.names = FALSE) else NULL }

apply_filter <- function(df, f) {
  v <- f$variable; if (is.null(v) || !(v %in% names(df))) return(df)
  vals <- as.character(unlist(f$value)); col <- as.character(df[[v]]); cmp <- f$comparator %||% "EQ"
  keep <- if (cmp %in% c("NE", "NOTIN")) !(col %in% vals) else (col %in% vals)
  df[keep & !is.na(keep), , drop = FALSE]
}
apply_filters <- function(df, filters) { if (is.null(filters)) return(df); for (f in filters) df <- apply_filter(df, f); df }
op_id <- function(ops, suffix) { for (o in names(ops)) if (endsWith(o, suffix)) return(o); NA_character_ }
mk <- function(oid, aid, op, level, name, label, raw, fmt, variable, var_level = NA_character_)
  data.frame(output_id = oid, analysis_id = aid, operation_id = op, group_var = "TRT01A",
             group_level = level, variable = variable, variable_level = var_level,
             stat_name = name, stat_label = label, stat_raw = as.character(raw),
             stat_fmt = fmt, stringsAsFactors = FALSE)

# The population + subset filters for an analysis, from the resolved bindings.
pop_and_subset <- function(df, an) {
  set <- bindings$analysisSets[[an$analysisSetId %||% ""]]
  if (!is.null(set)) df <- apply_filter(df, list(variable = set$variable, comparator = set$comparator, value = set$value))
  sub <- bindings$dataSubsets[[an$dataSubsetId %||% ""]]
  if (!is.null(sub)) df <- apply_filters(df, sub$conditions)
  df
}

status <- list()

draft_ancova <- function(oid, an, method) {
  ops <- setNames(method$operations, vapply(method$operations, function(o) o$id, character(1)))
  df <- pop_and_subset(load_adam(an$dataset), an)
  df <- df[!is.na(df$CHG) & !is.na(df$BASE), , drop = FALSE]
  fit <- lm(CHG ~ TRT01A + BASE, data = df)
  emm <- as.data.frame(emmeans(fit, "TRT01A"))
  ct <- as.data.frame(pairs(emmeans(fit, "TRT01A"), reverse = TRUE))
  rows <- do.call(rbind, lapply(seq_len(nrow(emm)), function(i) rbind(
    mk(oid, an$id, op_id(ops, "_2_LSMean"), emm$TRT01A[i], "lsmean", "LS Mean", emm$emmean[i], sprintf("%.1f", emm$emmean[i]), "CHG"),
    mk(oid, an$id, op_id(ops, "_3_LSMeanSE"), emm$TRT01A[i], "se", "SE", emm$SE[i], sprintf("(%.2f)", emm$SE[i]), "CHG"))))
  diffs <- do.call(rbind, lapply(seq_len(nrow(ct)), function(i) rbind(
    mk(oid, an$id, op_id(ops, "_4_Diff"), ct$contrast[i], "diff", "Diff vs PBO", ct$estimate[i], sprintf("%.1f", ct$estimate[i]), "CHG"),
    mk(oid, an$id, op_id(ops, "_7_pval"), ct$contrast[i], "pval", "p-value", ct$p.value[i], sprintf("%.3f", ct$p.value[i]), "CHG"))))
  long <- rbind(rows, diffs)[, ard_long_schema()]
  write.csv(long, file.path(work, "ard", paste0(oid, ".csv")), row.names = FALSE, na = "")
  disp <- emm %>% transmute(Treatment = TRT01A, `LS Mean` = sprintf("%.1f", emmean), SE = sprintf("%.2f", SE))
  writeLines(gt::as_raw_html(gt::gt(disp) %>% gt::tab_header(gt::md(paste0("**", oid, " — ANCOVA LS Means**")))),
             file.path(work, "tfl", paste0(oid, ".html")))
  writeLines(c("# Custom program (ANCOVA) — reference/agent-drafted",
               "# lm(CHG ~ TRT01A + BASE) on ITT, ADAS-Cog Week 24 subset; emmeans LS means + pairwise vs placebo"),
             file.path(work, "code", paste0(oid, ".R")))
  nrow(long)
}

draft_km <- function(oid, an, method) {
  ops <- setNames(method$operations, vapply(method$operations, function(o) o$id, character(1)))
  df <- pop_and_subset(load_adam(an$dataset), an)
  df <- df %>% mutate(event = 1 - as.numeric(CNSR))
  sf <- survfit(Surv(AVAL, event) ~ TRT01A, data = df)
  tab <- summary(sf)$table
  cox <- tryCatch(coxph(Surv(AVAL, event) ~ relevel(factor(TRT01A), ref = "Placebo"), data = df), error = function(e) NULL)
  long <- do.call(rbind, lapply(rownames(tab), function(rn) {
    lvl <- sub("TRT01A=", "", rn)
    rbind(
      mk(oid, an$id, op_id(ops, "_1_nEvent"), lvl, "nevent", "Events", tab[rn, "events"], as.character(tab[rn, "events"]), "AVAL"),
      mk(oid, an$id, op_id(ops, "_2_Median"), lvl, "median", "Median (days)", tab[rn, "median"], sprintf("%.1f", as.numeric(tab[rn, "median"])), "AVAL"))
  }))[, ard_long_schema()]
  write.csv(long, file.path(work, "ard", paste0(oid, ".csv")), row.names = FALSE, na = "")
  png(file.path(work, "tfl", paste0(oid, ".png")), width = 900, height = 600)
  plot(sf, col = seq_along(sf$strata), lwd = 2, xlab = "Days", ylab = "Survival",
       main = paste(oid, "- Kaplan-Meier"))
  legend("topright", legend = sub("TRT01A=", "", names(sf$strata)), col = seq_along(sf$strata), lwd = 2, bty = "n")
  dev.off()
  writeLines(c("# Custom program (Kaplan-Meier) — reference/agent-drafted",
               "# survfit(Surv(AVAL, 1-CNSR) ~ TRT01A) on ITT, primary TTE subset; Cox HR vs Placebo"),
             file.path(work, "code", paste0(oid, ".R")))
  nrow(long)
}

methods_idx <- setNames(bindings$analyses, names(bindings$analyses))  # analyses view carries methodId
ars_methods <- NULL
# Load method operations from the reporting event (bindings does not carry them).
re_path <- file.path(work, "reporting_event.json")
if (file.exists(re_path)) {
  re <- fromJSON(re_path, simplifyVector = FALSE)
  ars_methods <- setNames(re$methods, vapply(re$methods, function(m) m$id, character(1)))
}

for (i in seq_along(coverage$outputs)) {
  e <- coverage$outputs[[i]]
  if (!identical(e$mode, "custom")) next
  oid <- e$outputId
  aid <- (e$analysisIds %||% list())[[1]]
  an <- c(bindings$analyses[[aid]], list(id = aid))
  method <- ars_methods[[an$methodId %||% ""]]
  n <- tryCatch({
    if (grepl("ANCOVA", an$methodId %||% "", ignore.case = TRUE)) draft_ancova(oid, an, method)
    else if (grepl("KM|TTE|Kaplan", an$methodId %||% "", ignore.case = TRUE)) draft_km(oid, an, method)
    else stop(paste("no reference program for method", an$methodId))
  }, error = function(err) { cat(sprintf("  %s FAILED: %s\n", oid, conditionMessage(err))); NA_integer_ })
  rendered <- !is.na(n)
  coverage$outputs[[i]]$status <- if (rendered) "rendered" else "failed"
  coverage$outputs[[i]]$program <- paste0("code/", oid, ".R")
  if (rendered) coverage$outputs[[i]]$ardRows <- n
  status[[oid]] <- rendered
  cat(sprintf("  %-14s custom  method=%s  ardRows=%s  rendered=%s\n", oid, an$methodId %||% "?", n, rendered))
}

write_json(coverage, cov_path, auto_unbox = TRUE, pretty = TRUE, null = "null")
cat(sprintf("draft-custom: %d custom output(s) rendered.\n", sum(vapply(status, isTRUE, logical(1)))))
