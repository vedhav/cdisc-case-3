#' Read a define.xml into a trace graph fragment
#'
#' Parses a CDISC define.xml (Case Report Tabulation Data Definition) into
#' dataset, variable and codelist nodes plus their lineage edges. Handles both
#' define.xml 2.0 (where origin/derivation live in `def:Origin` and `MethodDef`
#' elements) and the older define 1.0 style used in the CDISC pilot ADaM
#' package (where `Origin` and the derivation source are *attributes* on
#' `ItemDef`). XPath is written with `local-name()` so it is agnostic to the
#' document's namespace prefixes.
#'
#' Variable nodes use the id scheme `<vartype>:<DATASET>.<VAR>` so ADaM
#' variables merge with the `operates_on` targets produced by [read_ars()], and
#' `derived_from` edges (ADaM variable to its predecessor SDTM/ADaM variable)
#' are inferred from `Origin = "Predecessor"` and from `DATASET.VAR` tokens in
#' the derivation comment.
#'
#' @param path Path to the define.xml file.
#' @param standard Which standard this define describes: `"sdtm"` or `"adam"`.
#'   Controls node types (`sdtm_dataset`/`sdtm_var` vs `adam_dataset`/
#'   `adam_var`).
#' @return A [trace_graph()] fragment.
#' @export
read_define <- function(path, standard = c("adam", "sdtm")) {
  standard <- match.arg(standard)
  ds_type  <- if (standard == "adam") "adam_dataset" else "sdtm_dataset"
  var_type <- if (standard == "adam") "adam_var" else "sdtm_var"
  src <- paste0("define:", standard, ":", basename(path))

  doc <- xml2::read_xml(path)
  ln <- function(node, name) xml2::xml_find_all(node, paste0(".//*[local-name()='", name, "']"))
  ln1 <- function(node, name) xml2::xml_find_first(node, paste0(".//*[local-name()='", name, "']"))
  is_node <- function(n) inherits(n, "xml_node")
  # text of the first TranslatedText under the first <name> child, or NA
  first_text <- function(node, name) {
    el <- ln1(node, name)
    if (!is_node(el)) return(NA_character_)
    tt <- ln1(el, "TranslatedText")
    if (is_node(tt)) xml2::xml_text(tt) else xml2::xml_text(el)
  }

  nodes <- list(); edges <- list()
  add_n <- function(...) nodes[[length(nodes) + 1]] <<- tibble::tibble(...)
  add_e <- function(from, to, rel, attrs = list())
    edges[[length(edges) + 1]] <<- tibble::tibble(
      from = from, to = to, rel = rel, source = src, attrs = list(attrs))

  # --- codelists ---
  for (cl in ln(doc, "CodeList")) {
    oid <- xml2::xml_attr(cl, "OID")
    if (is.na(oid)) next
    add_n(id = nid("codelist", oid), type = "codelist",
          label = xml2::xml_attr(cl, "Name") %||% oid, source = src,
          attrs = list(list(dataType = xml2::xml_attr(cl, "DataType"))))
  }

  # --- index ItemDefs by OID (variable definitions) ---
  itemdefs <- ln(doc, "ItemDef")
  item_by_oid <- stats::setNames(itemdefs, xml2::xml_attr(itemdefs, "OID"))

  # helper: create a variable node from an ItemDef under a dataset
  seen_var <- character()
  make_var <- function(item, ds_name) {
    var_name <- xml2::xml_attr(item, "Name")
    key <- paste0(ds_name, ".", var_name)
    vid <- nid(var_type, key)
    if (!vid %in% seen_var) {
      seen_var <<- c(seen_var, vid)
      # origin: attribute (define 1.0) or child def:Origin (define 2.0)
      origin_attr <- xml2::xml_attr(item, "Origin")
      origin_el <- ln1(item, "Origin")
      origin <- if (!is.na(origin_attr)) origin_attr
                else if (is_node(origin_el)) xml2::xml_attr(origin_el, "Type")
                else NA_character_
      deriv <- xml2::xml_attr(item, "Comment")
      if (is.na(deriv) || !nzchar(deriv)) {
        dtxt <- first_text(item, "Description")
        if (!is.na(dtxt)) deriv <- dtxt
      }
      add_n(id = vid, type = var_type, label = key, source = src,
            attrs = list(list(dataset = ds_name, variable = var_name,
                              label = xml2::xml_attr(item, "Label"),
                              dataType = xml2::xml_attr(item, "DataType"),
                              origin = origin, derivation = deriv)))
      add_e(vid, nid(ds_type, ds_name), "in_dataset")
      # codelist link
      clr <- ln1(item, "CodeListRef")
      if (is_node(clr)) {
        cloid <- xml2::xml_attr(clr, "CodeListOID")
        if (!is.na(cloid)) add_e(vid, nid("codelist", cloid), "uses_codelist")
      }
      # predecessor / derivation lineage
      link_predecessors(vid, origin, deriv, add_e)
    }
    vid
  }

  # --- datasets (ItemGroupDef) and their variables (ItemRef -> ItemDef) ---
  for (ig in ln(doc, "ItemGroupDef")) {
    ds_name <- xml2::xml_attr(ig, "Name")
    if (is.na(ds_name)) next
    label <- first_text(ig, "Description")
    if (is.na(label)) label <- xml2::xml_attr(ig, "Label") %||% ds_name
    add_n(id = nid(ds_type, ds_name), type = ds_type, label = label, source = src,
          attrs = list(list(class = xml2::xml_attr(ig, "Class") %||%
                              xml2::xml_attr(ig, "def:Class"))))
    for (ref in ln(ig, "ItemRef")) {
      oid <- xml2::xml_attr(ref, "ItemOID")
      item <- item_by_oid[[oid]]
      if (!is.null(item)) make_var(item, ds_name)
    }
  }

  trace_graph(
    nodes = bind_nodes(dplyr::bind_rows(nodes)),
    edges = bind_edges(dplyr::bind_rows(edges)),
    meta = list(sources = list(src))
  )
}

# Parse predecessor/derivation lineage into derived_from edges.
# Matches DATASET.VAR tokens (e.g. "ADSL.TRT01AN", "AE.AESEV"); the target is
# an adam_var when the dataset starts with "AD", otherwise an sdtm_var.
link_predecessors <- function(vid, origin, deriv, add_e) {
  txt <- deriv %||% ""
  if (is.na(txt)) txt <- ""
  toks <- unique(unlist(regmatches(
    txt, gregexpr("\\b[A-Z]{2,8}\\.[A-Z0-9_]+\\b", txt))))
  toks <- toks[toks != sub("^[^:]+:", "", vid)]  # not self
  for (t in toks) {
    ds <- sub("\\..*$", "", t)
    tgt_type <- if (grepl("^AD", ds)) "adam_var" else "sdtm_var"
    add_e(vid, nid(tgt_type, t), "derived_from",
          attrs = list(origin = origin))
  }
}
