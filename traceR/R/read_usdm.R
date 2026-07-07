#' Read a USDM study definition into a trace graph fragment
#'
#' Ingests the objectives, endpoints, estimands and analysis populations from
#' a CDISC USDM (Unified Study Definitions Model) JSON export. Two shapes are
#' supported automatically:
#'
#' * the **full USDM** export (DDF-RA `Examples/CDISC_Pilot`), where objectives
#'   live at `study$versions[[1]]$studyDesigns[[1]]$objectives`; and
#' * a **simplified trace** file `{objectives:[{id, text, endpoints:[...]}],
#'   endpointOutputMap, populationContext}` (as produced for a run fixture).
#'
#' If an `endpointOutputMap` is present it is stashed on the fragment's `meta`
#' so [build_trace()] can wire the endpoint to output bridge automatically.
#'
#' @param path Path to the USDM JSON file.
#' @return A [trace_graph()] fragment with `objective`, `endpoint`,
#'   `estimand` and `population` nodes.
#' @export
read_usdm <- function(path) {
  x <- jsonlite::read_json(path)
  if (!is.null(dig(x, "study", "versions"))) {
    frag <- read_usdm_full(x, path)
  } else if (!is.null(x$objectives)) {
    frag <- read_usdm_simple(x, path)
  } else {
    cli::cli_abort("Unrecognised USDM JSON at {.file {path}}.")
  }
  frag
}

# --- full DDF-RA USDM --------------------------------------------------------
read_usdm_full <- function(x, path) {
  sd <- dig(x, "study", "versions", 1, "studyDesigns", 1)
  if (is.null(sd)) cli::cli_abort("No studyDesign found in USDM at {.file {path}}.")
  src <- paste0("usdm:", basename(path))

  obj_nodes <- list(); end_nodes <- list(); est_nodes <- list()
  pop_nodes <- list(); edges <- list()

  for (o in sd$objectives %||% list()) {
    oid <- nid("objective", o$id)
    obj_nodes[[length(obj_nodes) + 1]] <- tibble::tibble(
      id = oid, type = "objective",
      label = scalar_chr(o$text %||% o$description %||% o$name),
      source = src,
      attrs = list(list(level = code_text(o$level), name = scalar_chr(o$name)))
    )
    for (e in o$endpoints %||% list()) {
      eid <- nid("endpoint", e$id)
      end_nodes[[length(end_nodes) + 1]] <- tibble::tibble(
        id = eid, type = "endpoint", label = scalar_chr(e$text %||% e$description),
        source = src,
        attrs = list(list(level = code_text(e$level), name = scalar_chr(e$name)))
      )
      edges[[length(edges) + 1]] <- tibble::tibble(
        from = oid, to = eid, rel = "has_endpoint", source = src, attrs = list(list())
      )
    }
  }

  for (p in sd$analysisPopulations %||% sd$population %||% list()) {
    if (is.null(p$id)) next
    pid <- nid("population", p$id)
    pop_nodes[[length(pop_nodes) + 1]] <- tibble::tibble(
      id = pid, type = "population", label = scalar_chr(p$label %||% p$name %||% p$text),
      source = src, attrs = list(list(text = scalar_chr(p$text %||% p$description)))
    )
  }

  for (es in sd$estimands %||% list()) {
    esid <- nid("estimand", es$id)
    est_nodes[[length(est_nodes) + 1]] <- tibble::tibble(
      id = esid, type = "estimand",
      label = scalar_chr(es$label %||% es$name %||% es$populationSummary),
      source = src,
      attrs = list(list(populationSummary = scalar_chr(es$populationSummary)))
    )
    if (!is.null(es$variableOfInterestId)) {
      edges[[length(edges) + 1]] <- tibble::tibble(
        from = esid, to = nid("endpoint", es$variableOfInterestId),
        rel = "assesses", source = src, attrs = list(list())
      )
    }
    if (!is.null(es$analysisPopulationId)) {
      edges[[length(edges) + 1]] <- tibble::tibble(
        from = esid, to = nid("population", es$analysisPopulationId),
        rel = "in_population", source = src, attrs = list(list())
      )
    }
  }

  trace_graph(
    nodes = bind_nodes(dplyr::bind_rows(obj_nodes), dplyr::bind_rows(end_nodes),
                       dplyr::bind_rows(est_nodes), dplyr::bind_rows(pop_nodes)),
    edges = bind_edges(dplyr::bind_rows(edges)),
    meta = list(sources = list(src), study = scalar_chr(dig(x, "study", "name")))
  )
}

# --- simplified trace fixture ------------------------------------------------
read_usdm_simple <- function(x, path) {
  src <- paste0("usdm:", basename(path))
  obj_nodes <- list(); end_nodes <- list(); edges <- list()

  for (o in x$objectives %||% list()) {
    oid <- nid("objective", o$id)
    obj_nodes[[length(obj_nodes) + 1]] <- tibble::tibble(
      id = oid, type = "objective", label = scalar_chr(o$text),
      source = src, attrs = list(list(level = scalar_chr(o$level)))
    )
    for (e in o$endpoints %||% list()) {
      eid <- nid("endpoint", e$id)
      end_nodes[[length(end_nodes) + 1]] <- tibble::tibble(
        id = eid, type = "endpoint", label = scalar_chr(e$text),
        source = src, attrs = list(list(level = scalar_chr(e$level)))
      )
      edges[[length(edges) + 1]] <- tibble::tibble(
        from = oid, to = eid, rel = "has_endpoint", source = src, attrs = list(list())
      )
    }
  }

  # endpoint -> output bridge, stashed for build_trace()
  eom <- x$endpointOutputMap %||% list()
  eom <- lapply(eom, function(v) unlist(v, use.names = FALSE))

  trace_graph(
    nodes = bind_nodes(dplyr::bind_rows(obj_nodes), dplyr::bind_rows(end_nodes)),
    edges = bind_edges(dplyr::bind_rows(edges)),
    meta = list(sources = list(src), study = scalar_chr(x$study),
                endpoint_output_map = eom)
  )
}
