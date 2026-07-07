# CDISC Library API client + reproducible snapshots ---------------------------

CL_BASE <- "https://library.cdisc.org/api"

#' Resolve a CDISC Library API key
#'
#' Looks up the key from the argument, then the `CDISC_LIBRARY_API_KEY` and
#' `CDISC_API_KEY` environment variables.
#' @param key Optional explicit key.
#' @return The key string, or `""` if none is set.
#' @export
cdisc_library_key <- function(key = NULL) {
  key %||% {
    k <- Sys.getenv("CDISC_LIBRARY_API_KEY")
    if (!nzchar(k)) k <- Sys.getenv("CDISC_API_KEY")
    k
  }
}

# Low-level GET against the CDISC Library API. Authenticates with the `api-key`
# header (the scheme the API documents). Gives a clear error on the
# members-only 401 so callers know it is an entitlement problem, not a bug.
cl_get <- function(path, key = cdisc_library_key(), base = CL_BASE) {
  rlang::check_installed("httr2", "to call the CDISC Library API")
  if (!nzchar(key))
    cli::cli_abort(c("No CDISC Library API key.",
      i = "Set {.envvar CDISC_LIBRARY_API_KEY} or pass {.arg key}."))
  resp <- httr2::request(paste0(base, path)) |>
    httr2::req_headers("api-key" = key, Accept = "application/json") |>
    httr2::req_timeout(60) |>
    httr2::req_error(is_error = function(r) FALSE) |>
    httr2::req_perform()
  st <- httr2::resp_status(resp)
  if (st == 401)
    cli::cli_abort(c("CDISC Library returned 401 (members-only).",
      x = "The API key is not entitled: {.val {substr(httr2::resp_body_string(resp),1,120)}}",
      i = "A CDISC member API key is required. Use {.fn snapshot_from_define} for an offline, reproducible alternative."))
  if (st != 200)
    cli::cli_abort("CDISC Library {path} returned HTTP {st}.")
  httr2::resp_body_json(resp)
}

#' List CDISC Library products
#'
#' @param key A CDISC Library API key; defaults to [cdisc_library_key()].
#' @return A tibble of product hrefs discovered under `/mdr/products`.
#' @export
cl_products <- function(key = cdisc_library_key()) {
  j <- cl_get("/mdr/products", key)
  links <- j[["_links"]] %||% list()
  rows <- purrr::imap(links, function(v, family) {
    hrefs <- if (!is.null(v$href)) list(v) else v
    purrr::map_dfr(hrefs, function(h) tibble::tibble(
      family = family, title = h$title %||% NA_character_, href = h$href %||% NA_character_))
  })
  dplyr::bind_rows(rows)
}

#' Download an exhaustive variable catalogue for a product (metadata-driven)
#'
#' Discovers the product's datasets by following the API's `_links` (rather than
#' hardcoding a domain list), then pulls every variable of every dataset. Works
#' for SDTMIG (`product = "sdtmig", version = "3-4"`) and ADaMIG
#' (`product = "adamig", version = "1-3"`), among others.
#'
#' @param product Product slug, e.g. `"sdtmig"` or `"adamig"`.
#' @param version Version slug, e.g. `"3-4"`.
#' @param key A CDISC Library API key; defaults to [cdisc_library_key()].
#' @return A tibble in the traceR snapshot schema (one row per variable).
#' @export
cl_product_variables <- function(product, version, key = cdisc_library_key()) {
  root <- cl_get(sprintf("/mdr/%s/%s", product, version), key)
  ds_links <- dig(root, "_links", "datasets") %||% dig(root, "_links", "dataStructures") %||% list()
  standard <- if (grepl("adam", product)) "adam" else "sdtm"
  out <- purrr::map_dfr(ds_links, function(dl) {
    href <- dl$href
    if (is.null(href)) return(NULL)
    dj <- cl_get(sub("^.*/api", "", href), key)
    ds_name <- dj$name %||% basename(href)
    var_links <- dig(dj, "_links", "analysisVariables") %||%
                 dig(dj, "_links", "variables") %||%
                 dig(dj, "_links", "analysisVariableSets") %||% list()
    # variables may be inline or linked; handle inline first
    vars <- dj$analysisVariables %||% dj$variables %||% list()
    if (length(vars)) {
      purrr::map_dfr(vars, function(v) snapshot_row(standard, product, version, ds_name, v))
    } else {
      purrr::map_dfr(var_links, function(vl) {
        vj <- cl_get(sub("^.*/api", "", vl$href), key)
        snapshot_row(standard, product, version, ds_name, vj)
      })
    }
  })
  out
}

# Normalise one Library variable payload into the snapshot schema.
snapshot_row <- function(standard, product, version, dataset, v) {
  tibble::tibble(
    standard = standard, product = product, version = version,
    dataset = dataset,
    variable = v$name %||% NA_character_,
    label = v$label %||% NA_character_,
    data_type = v$simpleDatatype %||% v$datatype %||% NA_character_,
    role = v$role %||% NA_character_,
    core = v$core %||% NA_character_,
    codelist = paste(unlist(dig(v, "_links", "codelist")), collapse = ";") %||% NA_character_
  )
}

#' Cache a product variable catalogue as a reproducible snapshot
#'
#' Downloads [cl_product_variables()] and writes it to
#' `dir/<product>-<version>.json` together with the retrieval time and a content
#' hash, so a build can be pinned to an exact standards version.
#'
#' @param product,version Product/version slugs.
#' @param dir Snapshot directory (defaults to the package's bundled
#'   `extdata/snapshots`).
#' @param key A CDISC Library API key; defaults to [cdisc_library_key()].
#' @return Invisibly, the snapshot file path.
#' @export
cdisc_snapshot <- function(product, version, dir = snapshot_dir(),
                           key = cdisc_library_key()) {
  vars <- cl_product_variables(product, version, key)
  dir.create(dir, showWarnings = FALSE, recursive = TRUE)
  path <- file.path(dir, sprintf("%s-%s.json", product, version))
  doc <- list(
    product = product, version = version,
    retrieved = as.character(Sys.time()),
    sha = digest::digest(vars),
    n_variables = nrow(vars),
    variables = vars
  )
  writeLines(jsonlite::toJSON(doc, auto_unbox = TRUE, dataframe = "rows", pretty = TRUE), path)
  cli::cli_alert_success("Snapshot: {nrow(vars)} variables -> {.file {path}}")
  invisible(path)
}

#' @rdname cdisc_snapshot
#' @export
snapshot_dir <- function() {
  d <- system.file("extdata", "snapshots", package = "traceR")
  if (nzchar(d)) d else file.path("inst", "extdata", "snapshots")
}

#' Load a snapshot (API- or define-derived) into a tibble
#' @param file Path to a snapshot JSON.
#' @return A tibble of variables in the snapshot schema.
#' @export
load_snapshot <- function(file) {
  j <- jsonlite::read_json(file, simplifyVector = TRUE)
  tibble::as_tibble(j$variables)
}

#' Derive a reproducible snapshot from a define.xml (offline fallback)
#'
#' When a CDISC Library member key is unavailable, this derives the same
#' snapshot schema from a study's define.xml. It is fully offline and
#' reproducible; it captures the *study's* variables rather than the full
#' published standard, but serves the same conformance/annotation role.
#'
#' @param define_path Path to a define.xml.
#' @param standard `"adam"` or `"sdtm"`.
#' @param dir Optional directory to write a snapshot JSON to.
#' @return A tibble in the snapshot schema (invisibly written if `dir` given).
#' @export
snapshot_from_define <- function(define_path, standard = c("adam", "sdtm"),
                                 dir = NULL) {
  standard <- match.arg(standard)
  frag <- read_define(define_path, standard = standard)
  vtype <- if (standard == "adam") "adam_var" else "sdtm_var"
  vs <- frag$nodes[frag$nodes$type == vtype, ]
  vars <- purrr::map_dfr(seq_len(nrow(vs)), function(i) {
    a <- vs$attrs[[i]]
    tibble::tibble(
      standard = standard, product = paste0("define:", standard), version = "study",
      dataset = a$dataset %||% NA_character_, variable = a$variable %||% NA_character_,
      label = a$label %||% NA_character_, data_type = a$dataType %||% NA_character_,
      role = NA_character_, core = NA_character_, origin = a$origin %||% NA_character_)
  })
  if (!is.null(dir)) {
    dir.create(dir, showWarnings = FALSE, recursive = TRUE)
    path <- file.path(dir, sprintf("define-%s.json", standard))
    writeLines(jsonlite::toJSON(list(product = paste0("define:", standard),
      version = "study", retrieved = as.character(Sys.time()),
      sha = digest::digest(vars), n_variables = nrow(vars), variables = vars),
      auto_unbox = TRUE, dataframe = "rows", pretty = TRUE), path)
    cli::cli_alert_success("Define snapshot: {nrow(vars)} variables -> {.file {path}}")
    return(invisible(vars))
  }
  vars
}

#' Annotate variable nodes as standard vs custom against a snapshot
#'
#' Adds `attrs$standard = TRUE/FALSE` to each `adam_var`/`sdtm_var` node
#' depending on whether its `DATASET.VARIABLE` appears in the snapshot. This is
#' the conformance layer: it flags study variables that are not part of the
#' pinned published standard.
#'
#' @param graph A [trace_graph()].
#' @param snapshot A snapshot tibble (from [load_snapshot()] or
#'   [snapshot_from_define()]) or a path to one.
#' @return The graph with annotated variable nodes.
#' @export
annotate_standard <- function(graph, snapshot) {
  if (is.character(snapshot)) snapshot <- load_snapshot(snapshot)
  keyset <- paste0(snapshot$dataset, ".", snapshot$variable)
  n <- graph$nodes
  is_var <- n$type %in% c("adam_var", "sdtm_var")
  for (i in which(is_var)) {
    key <- sub("^[^:]+:", "", n$id[i])
    n$attrs[[i]]$standard <- key %in% keyset
  }
  graph$nodes <- n
  graph
}
