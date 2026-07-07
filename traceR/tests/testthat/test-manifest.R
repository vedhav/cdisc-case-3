test_that("trace_manifest + trace_verify confirm reproducibility", {
  g <- cdiscpilot01_trace
  man <- trace_manifest(g, inputs = c(ars = traceR_example("reporting_event.json")))
  expect_equal(man$counts$nodes, nrow(g$nodes))
  expect_false(is.null(man$graph_hashes))
  expect_true(trace_verify(g, man)$reproducible)
})

test_that("rebuilding from identical inputs yields identical hashes", {
  g1 <- build_trace(
    usdm = traceR_example("usdm_trace.json"),
    ars  = traceR_example("reporting_event.json"),
    define = list(adam = traceR_example("define_adam.xml"),
                  sdtm = traceR_example("define_sdtm.xml"))
  )
  expect_equal(g1$meta$hashes, cdiscpilot01_trace$meta$hashes)
})

test_that("snapshot_from_define derives the offline standards snapshot", {
  snap <- load_snapshot(traceR_example("define-adam.json"))
  expect_true(all(c("dataset", "variable", "label") %in% names(snap)))
  expect_gt(nrow(snap), 100)

  g <- annotate_standard(cdiscpilot01_trace, snap)
  vi <- which(g$nodes$id == "adam_var:ADSL.AGE")
  expect_true(isTRUE(g$nodes$attrs[[vi]]$standard))
})

test_that("trace_to_json round-trips the graph shape", {
  js <- trace_to_json(cdiscpilot01_trace)
  doc <- jsonlite::fromJSON(js, simplifyVector = FALSE)
  expect_equal(length(doc$nodes), nrow(cdiscpilot01_trace$nodes))
  expect_equal(length(doc$edges), nrow(cdiscpilot01_trace$edges))
})
