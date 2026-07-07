# Builds traceR's bundled sample data from the CDISC pilot sources.
#
# Run from the package root:  Rscript data-raw/make_sample_data.R
# It (1) copies a curated set of source files into inst/extdata, and
# (2) builds the lazy-loaded datasets documented in R/data.R.
#
# Sources (adjust if your local paths differ):
#   - ARS Reporting Event + USDM trace: this repo's fixtures/
#   - ADaM CSVs:                        this repo's fixtures/adam/
#   - define.xml (ADaM + SDTM):         the CDISC pilot submission package

suppressMessages({
  library(dplyr); library(tibble); library(xml2); library(jsonlite)
  library(igraph); library(cli); library(digest); library(purrr); library(tidyr)
})
for (f in list.files("R", full.names = TRUE)) source(f)

repo <- normalizePath("..", mustWork = FALSE)          # cdisc-case-3 root
fx   <- file.path(repo, "fixtures")
pilot <- "C:/Users/User/OneDrive/Documents/CDISC/sdtm-adam-pilot-project-master/updated-pilot-submission-package/900172/m5/datasets/cdiscpilot01"
adam_def <- file.path(pilot, "analysis/adam/datasets/define.xml")
sdtm_def <- file.path(pilot, "tabulations/sdtm/define.xml")

ext <- file.path("inst", "extdata")
adam_ext <- file.path(ext, "adam")
dir.create(adam_ext, showWarnings = FALSE, recursive = TRUE)

# (1) copy curated source files -------------------------------------------------
file.copy(file.path(fx, "reporting_event.json"), file.path(ext, "reporting_event.json"), overwrite = TRUE)
file.copy(file.path(fx, "usdm_trace.json"),      file.path(ext, "usdm_trace.json"),      overwrite = TRUE)
for (d in c("adsl", "adae", "adtte", "adqsadas"))
  file.copy(file.path(fx, "adam", paste0(d, ".csv")), file.path(adam_ext, paste0(d, ".csv")), overwrite = TRUE)
file.copy(adam_def, file.path(ext, "define_adam.xml"), overwrite = TRUE)
file.copy(sdtm_def, file.path(ext, "define_sdtm.xml"), overwrite = TRUE)

# offline, reproducible standards snapshots derived from define.xml
dir.create(file.path(ext, "snapshots"), showWarnings = FALSE, recursive = TRUE)
snapshot_from_define(file.path(ext, "define_adam.xml"), "adam", dir = file.path(ext, "snapshots"))
snapshot_from_define(file.path(ext, "define_sdtm.xml"), "sdtm", dir = file.path(ext, "snapshots"))

# (2) build lazy-loaded datasets ------------------------------------------------
cdiscpilot01_trace <- build_trace(
  usdm   = file.path(ext, "usdm_trace.json"),
  ars    = file.path(ext, "reporting_event.json"),
  define = list(adam = file.path(ext, "define_adam.xml"),
                sdtm = file.path(ext, "define_sdtm.xml"))
)
cdiscpilot01_adsl <- tibble::as_tibble(
  utils::read.csv(file.path(adam_ext, "adsl.csv"), stringsAsFactors = FALSE))

dir.create("data", showWarnings = FALSE)
save(cdiscpilot01_trace, file = "data/cdiscpilot01_trace.rda", compress = "xz")
save(cdiscpilot01_adsl,  file = "data/cdiscpilot01_adsl.rda",  compress = "xz")

cli::cli_alert_success("Sample data built: {nrow(cdiscpilot01_trace$nodes)} nodes, {nrow(cdiscpilot01_trace$edges)} edges.")
