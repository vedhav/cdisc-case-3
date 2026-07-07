# Internal helpers ------------------------------------------------------------

`%||%` <- function(x, y) if (is.null(x) || length(x) == 0) y else x

#' Build a namespaced node id
#'
#' Node ids are `"<type>:<source-id>"` so that ids from independent sources
#' (USDM, ARS, define.xml) never collide when merged into one graph.
#'
#' @param type Node type (one of `trace_vocab$node_types`).
#' @param id Source-native id (e.g. an ARS `Analysis.id`).
#' @return A character vector of namespaced ids.
#' @export
#' @examples
#' nid("analysis", "An01_05_SAF_Summ")
nid <- function(type, id) {
  paste0(type, ":", id)
}

# Coerce a possibly-NULL / possibly-nested JSON scalar to a length-1 chr.
scalar_chr <- function(x, default = NA_character_) {
  if (is.null(x) || length(x) == 0) return(default)
  x <- x[[1]]
  if (is.null(x) || length(x) == 0) return(default)
  as.character(x)
}

# Pull nested field by path, NULL-safe: dig(x, "a", "b", 1). Preserves the
# type of each key (character names and integer positions both work).
dig <- function(x, ...) {
  for (k in list(...)) {
    if (is.null(x)) return(NULL)
    x <- tryCatch(x[[k]], error = function(e) NULL)
  }
  x
}

# A named-list "coded value" in USDM/ARS is often {code, decode, ...}.
code_text <- function(x) {
  if (is.null(x)) return(NA_character_)
  scalar_chr(x$decode %||% x$code %||% x$standardCode$decode %||% x)
}

# Empty typed node/edge tibbles (the graph's canonical shape).
empty_nodes <- function() {
  tibble::tibble(
    id = character(), type = character(), label = character(),
    source = character(), attrs = list()
  )
}
empty_edges <- function() {
  tibble::tibble(
    from = character(), to = character(), rel = character(),
    source = character(), attrs = list()
  )
}

# Row-bind a fragment's parts, tolerating NULL.
bind_nodes <- function(...) {
  parts <- Filter(Negate(is.null), list(...))
  if (length(parts) == 0) return(empty_nodes())
  dplyr::bind_rows(parts)
}
bind_edges <- bind_nodes
