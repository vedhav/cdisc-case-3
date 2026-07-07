skip_if_not_installed("cards")

adam_dir <- function() dirname(traceR_example("adsl.csv"))

test_that("execute_analysis reproduces the known ADSL age summary", {
  g <- cdiscpilot01_trace
  r <- execute_analysis(g, "An03_01_Age_Summ_ByTrt", adam_dir())
  expect_true(all(ard_long_schema() %in% names(r)))
  mean_pbo <- r$stat_raw[r$group_level == "Placebo" & r$stat_name == "mean"]
  expect_equal(round(as.numeric(mean_pbo), 3), 75.209)
  # the ARS operation id is carried through, not invented
  expect_true(all(grepl("^Mth", r$operation_id)))
})

test_that("execute_reporting_event runs the supported outputs and closes the loop", {
  g <- cdiscpilot01_trace
  ex <- execute_reporting_event(g, adam_dir())
  expect_true(all(c("ard", "status") %in% names(ex)))
  expect_gt(nrow(ex$ard), 0)
  expect_true(any(ex$status$status == "executed"))

  g2 <- build_trace(
    usdm = traceR_example("usdm_trace.json"),
    ars  = traceR_example("reporting_event.json"),
    ard  = ex$ard
  )
  cov <- trace_coverage(g2)
  expect_true(any(cov$reaches_result))
})
