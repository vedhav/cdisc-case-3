test_that("build_trace merges sources and wires the endpoint->output bridge", {
  g <- cdiscpilot01_trace
  expect_s3_class(g, "trace_graph")
  expect_gt(nrow(g$nodes), 900)
  expect_true("evaluated_by" %in% g$edges$rel)
  expect_length(g$meta$sources, 4)
  expect_false(is.null(g$meta$hashes))
})

test_that("trace_path finds objective -> output lineage", {
  g <- cdiscpilot01_trace
  p <- trace_path(g, "Objective_2", "Out14-3-1-1")
  expect_equal(p$type, c("objective", "endpoint", "output"))
  expect_equal(p$via[2:3], c("has_endpoint", "evaluated_by"))
})

test_that("trace_descendants follows a single relationship", {
  g <- cdiscpilot01_trace
  d <- trace_descendants(g, "adam_var:ADAE.TRTAN", rel = "derived_from")
  expect_true("adam_var:ADSL.TRT01AN" %in% d$id)
})

test_that("node references resolve by id, bare id and unique label", {
  g <- cdiscpilot01_trace
  expect_error(trace_path(g, "does_not_exist", "Objective_1"), "No node")
  # bare source id works
  p <- trace_path(g, "Objective_1", "Endpoint_1")
  expect_gt(nrow(p), 0)
})

test_that("trace_lineage returns a connected subgraph", {
  g <- cdiscpilot01_trace
  sub <- trace_lineage(g, "Objective_2")
  expect_s3_class(sub, "trace_graph")
  expect_true("objective:Objective_2" %in% sub$nodes$id)
  expect_lt(nrow(sub$nodes), nrow(g$nodes))
})
