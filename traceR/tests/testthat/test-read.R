test_that("read_usdm parses the simplified trace fixture", {
  f <- read_usdm(traceR_example("usdm_trace.json"))
  expect_s3_class(f, "trace_graph")
  expect_true(all(c("objective", "endpoint") %in% f$nodes$type))
  expect_equal(sum(f$nodes$type == "objective"), 6)
  expect_gt(length(f$meta$endpoint_output_map), 0)
})

test_that("read_ars parses analyses, outputs, methods and the LOC tree", {
  f <- read_ars(traceR_example("reporting_event.json"))
  expect_gt(sum(f$nodes$type == "analysis"), 30)
  expect_equal(sum(f$nodes$type == "output"), 7)
  # every analysis under an output is linked by displayed_in
  expect_true(any(f$edges$rel == "displayed_in"))
  expect_true(any(f$edges$rel == "operates_on"))
})

test_that("read_define handles define 1.0 attribute-style origins", {
  f <- read_define(traceR_example("define_adam.xml"), "adam")
  expect_true(all(c("adam_dataset", "adam_var", "codelist") %in% f$nodes$type))
  # ADaM predecessors resolve into derived_from edges
  expect_true(any(f$edges$rel == "derived_from"))
  # the classic ADAE.TRTAN <- ADSL.TRT01AN lineage is captured
  drv <- f$edges[f$edges$rel == "derived_from" & f$edges$from == "adam_var:ADAE.TRTAN", ]
  expect_true("adam_var:ADSL.TRT01AN" %in% drv$to)
})

test_that("read_ard requires the contract columns", {
  expect_error(read_ard(data.frame(x = 1)), "missing required")
})
