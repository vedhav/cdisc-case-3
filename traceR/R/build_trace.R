#' Assemble a full traceability graph from CDISC source metadata
#'
#' The centrepiece of traceR. Reads (or accepts pre-read fragments for) the
#' USDM study definition, the ARS Reporting Event, one or more define.xml
#' files, and optionally an ARD; merges them into one [trace_graph()]; and
#' resolves the cross-source edges that no single source expresses:
#'
#' * the **endpoint to output bridge** (`evaluated_by`), taken from the USDM
#'   fragment's `endpointOutputMap` when present, or from `endpoint_output_map`;
#' * **stub materialisation** for lineage targets referenced by an edge but not
#'   defined by any parsed source (e.g. an SDTM predecessor variable when only
#'   the ADaM define was read) — so lineage is never silently dropped.
#'
#' The result carries provenance and content hashes in `meta` for
#' reproducibility (see [trace_manifest()]).
#'
#' @param usdm A path to a USDM JSON, or a fragment from [read_usdm()], or NULL.
#' @param ars A path to an ARS JSON, or a fragment from [read_ars()], or NULL.
#' @param define A named list of define fragments/paths, e.g.
#'   `list(adam = "adam/define.xml", sdtm = "sdtm/define.xml")`. Names set the
#'   `standard` when a path is given.
#' @param ard A path/data.frame/fragment of results, or NULL.
#' @param endpoint_output_map Optional named list mapping endpoint source-ids to
#'   output source-ids; overrides/augments the USDM fragment's own map.
#' @return A `trace_graph`.
#' @export
build_trace <- function(usdm = NULL, ars = NULL, define = NULL, ard = NULL,
                        endpoint_output_map = NULL) {
  as_frag <- function(x, reader) {
    if (is.null(x) || is_trace_graph(x)) x else reader(x)
  }
  f_usdm <- as_frag(usdm, read_usdm)
  f_ars  <- as_frag(ars,  read_ars)
  f_ard  <- if (is.null(ard) || is_trace_graph(ard)) ard else read_ard(ard)

  f_defines <- list()
  if (!is.null(define)) {
    nms <- names(define) %||% rep("adam", length(define))
    for (i in seq_along(define)) {
      d <- define[[i]]
      f_defines[[i]] <- if (is_trace_graph(d)) d
        else read_define(d, standard = if (nms[i] %in% c("adam", "sdtm")) nms[i] else "adam")
    }
  }

  frags <- c(list(f_usdm, f_ars, f_ard), f_defines)
  g <- do.call(trace_merge, c(frags, list(meta = list(built = TRUE))))

  # endpoint -> output bridge
  eom <- endpoint_output_map %||% dig(f_usdm, "meta", "endpoint_output_map")
  if (length(eom)) {
    br <- list()
    for (ep in names(eom)) for (ou in eom[[ep]]) {
      br[[length(br) + 1]] <- tibble::tibble(
        from = nid("endpoint", ep), to = nid("output", ou),
        rel = "evaluated_by", source = "bridge:endpointOutputMap",
        attrs = list(list()))
    }
    g$edges <- dplyr::bind_rows(g$edges, dplyr::bind_rows(br))
    g$edges <- g$edges[!duplicated(g$edges[c("from", "to", "rel")]), , drop = FALSE]
  }

  g <- materialize_stubs(g)
  g$meta$sources <- unique(unlist(g$meta$sources))
  g$meta$hashes <- graph_hashes(g)
  g
}

# Add lightweight stub nodes for any edge endpoint not present as a node,
# typed from the id's namespace prefix. Keeps lineage visible.
materialize_stubs <- function(g) {
  refd <- unique(c(g$edges$from, g$edges$to))
  missing <- setdiff(refd, g$nodes$id)
  if (!length(missing)) return(g)
  stubs <- tibble::tibble(
    id = missing,
    type = sub(":.*$", "", missing),
    label = sub("^[^:]+:", "", missing),
    source = "inferred:stub",
    attrs = replicate(length(missing), list(stub = TRUE), simplify = FALSE)
  )
  g$nodes <- dplyr::bind_rows(g$nodes, stubs)
  g
}

graph_hashes <- function(g) {
  # radix ordering is locale-independent, so hashes are portable across
  # machines and the C-locale used under R CMD check.
  no <- order(g$nodes$id, method = "radix")
  eo <- order(g$edges$from, g$edges$to, g$edges$rel, method = "radix")
  # as.data.frame drops tibble attributes so the digest depends only on content
  list(
    nodes = digest::digest(as.data.frame(g$nodes[no, c("id", "type", "label")],
                                         stringsAsFactors = FALSE), ascii = TRUE),
    edges = digest::digest(as.data.frame(g$edges[eo, c("from", "to", "rel")],
                                         stringsAsFactors = FALSE), ascii = TRUE)
  )
}
