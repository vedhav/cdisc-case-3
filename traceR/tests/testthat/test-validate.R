test_that("trace_gaps returns a tidy table with known safety-endpoint gaps", {
  g <- cdiscpilot01_trace
  gaps <- trace_gaps(g)
  expect_true(all(c("id", "type", "label", "gap", "severity") %in% names(gaps)))
  # efficacy endpoints with no mapped output show up as info gaps
  expect_true(any(gaps$type == "endpoint"))
  # analyses are not yet executed -> "produced no result" info gaps exist
  expect_true(any(grepl("no result", gaps$gap)))
})

test_that("trace_coverage summarises each objective", {
  g <- cdiscpilot01_trace
  cov <- trace_coverage(g)
  expect_equal(nrow(cov), 6)
  # the safety objective reaches many outputs/analyses
  saf <- cov[cov$objective == "objective:Objective_2", ]
  expect_gt(saf$n_outputs, 1)
  expect_gt(saf$n_analyses, 10)
  # without an ARD, nothing reaches a result yet
  expect_false(any(cov$reaches_result))
})
