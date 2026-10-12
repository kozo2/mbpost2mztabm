## Convert the TOML / Parquet files written by extract_mbpost_tables.py to
## mzTab-M files (MTD + SML) with RmzTabM, one mzTab-M file per quantification
## table.
##
## Usage: Rscript mbpost_to_mztabm.R [input_dir] [output_dir] [name_regex]
##
##   input_dir    directory with <name>.toml and <name>.parquet (mbpost_extracted)
##   output_dir   directory for the mzTab-M files (mztabm_extracted)
##   name_regex   only the files whose name without extension matches
##
## A file with one table gives <name>.mztab, a file with several tables (sheets,
## or blocks of columns holding different quantities) one file per table named
## after the table id (<name>__<sheet>[__<quantity>].mztab). The tables and their
## mzTab-M files are listed in <output_dir>/mztabm_report.tsv.
##
## What an mzTab-M file holds, and what it does not:
## - MTD: the samples with the attributes of the TOML file as custom parameters,
##   one ms_run (location "null") and one assay per sample, and one study
##   variable, "undefined", with all assays, because the files state no study
##   design. The quantification unit is the one of the TOML file (an NCIT term
##   where the term is known, else the text), otherwise "Arbitrary quantification
##   unit". The quantification method is the RmzTabM default (LC-MS label-free
##   quantitation): the tables do not say how they were quantified.
## - scan_polarity only if the table shows it, from the sign of its adduct ions
##   or pos / neg in its name; otherwise the field is left out (RmzTabM can only
##   write "positive" or "negative").
## - SML: one row per metabolite, with chemical_name, chemical_formula and
##   adduct_ions in mzTab-M notation. A name with alternatives separated by "|"
##   (MS-DIAL) gets as many elements in the other list fields. Feature ID, m/z,
##   retention time (min) and InChIKey are optional columns (opt_global_*). There
##   is no SMF section.
##
## Run from the repository root, like the other R scripts.

source("mbpost_mztab.R")  # .sml_text(), .sort_index(), .add_scan_polarity(), .UNITS, .CVS
suppressPackageStartupMessages(library(RcppTOML))

## writeMzTabM() cuts non-ASCII text (µM, ①, ...) in a non-UTF-8 locale.
.use_utf8 <- function() {
    for (loc in c("en_US.UTF-8", "C.UTF-8"))
        if (!l10n_info()[["UTF-8"]])
            Sys.setlocale("LC_CTYPE", loc)
    if (!l10n_info()[["UTF-8"]])
        stop("A UTF-8 locale is needed, e.g. LC_ALL=en_US.UTF-8 Rscript ...")
}

## ---- text in mzTab-M notation ----------------------------------------------------

## "[M + H]+", "(M-H)-", "[M ‒ H]‒" -> "[M+H]1+", "[M-H]1-"; NA if it is no adduct.
.adduct <- function(x) {
    x <- gsub("[‐-―−]", "-", x)
    x <- gsub("\\s+", "", x)
    x <- sub("^\\((.*)\\)(\\d*[+-])$", "[\\1]\\2", x)
    x <- sub("\\]([+-])$", "]1\\1", x)
    x[!grepl("^\\[\\d*M([+-][A-Za-z0-9]+)*\\]\\d*[+-]$", x)] <- NA_character_
    x
}

## "C9 H15 N4 O8 P", "C40H80N1O8P1", "C36H61(D7)O5" -> "C9H15N4O8P", "C40H80NO8P", "C36H61[2H]7O5"
.formula2 <- function(x) {
    x <- gsub("\\s+", "", x)
    x <- gsub("\\(D(\\d*)\\)", "[2H]\\1", x)
    gsub("([A-Z][a-z]?)1(?![0-9])", "\\1", x, perl = TRUE)
}

## A name or value of a parameter "[label, accession, name, value]" that has a comma is quoted.
.quote <- function(x) {
    q <- grepl("[,\"]", x)
    x[q] <- paste0("\"", gsub("\"", "\\\\\"", x[q]), "\"")
    x
}

## Numbers as written in the source sheets (15 significant digits).
.num15 <- function(x) {
    out <- sprintf("%.15g", x)
    out[is.na(x)] <- NA_character_
    out
}

## The elements of names "A|B"; NA if there is no name.
.elements <- function(name) {
    lapply(strsplit(ifelse(is.na(name), "", name), "|", fixed = TRUE), function(e) {
        e <- trimws(e)
        e <- e[nzchar(e)]
        if (length(e)) e else NA_character_
    })
}

## A value repeated for the k elements of a list field ("A|A"); NA stays NA.
.per_element <- function(value, k) {
    vapply(seq_along(value), function(i)
        if (is.na(value[i])) NA_character_ else paste(rep(value[i], k[i]), collapse = "|"), "")
}

## ---- table -> mzTab-M --------------------------------------------------------------

## The polarities (positive, negative) a table shows, and the evidence.
.polarities <- function(adduct, id) {
    sign <- substring(adduct[!is.na(adduct)], nchar(adduct[!is.na(adduct)]))
    pol <- c("positive", "negative")[c("+" %in% sign, "-" %in% sign)]
    if (length(pol))
        return(list(polarity = pol, basis = "adduct ions"))
    token <- tolower(regmatches(id, gregexpr("(?i)(?<![A-Za-z])(pos|neg)(itive|ative)?(?![A-Za-z])", id,
                                             perl = TRUE))[[1L]])
    pol <- c("positive", "negative")[c(any(startsWith(token, "pos")), any(startsWith(token, "neg")))]
    list(polarity = pol, basis = if (length(pol)) "name" else "none")
}

## The MTD of a table of the TOML file.
mbpost_mtd_table <- function(tbl, polarity = character()) {
    name <- vapply(tbl$sample, function(s) s$name, "")
    keys <- unique(unlist(lapply(tbl$sample, function(s) names(s$attributes))))
    x <- data.frame(sample = name, location = "null", assay = name,
                    scan_polarity = if (length(polarity)) polarity[1L] else "positive",
                    stringsAsFactors = FALSE)
    for (j in seq_along(keys))
        x[[paste0("attribute", j)]] <- vapply(tbl$sample, function(s) {
            v <- s$attributes[[keys[j]]]
            if (is.null(v)) "null" else .quote(gsub("|", "/", v, fixed = TRUE))
        }, "")
    reserved <- c("sample", "species", "tissue", "cell_type", "disease", "description")
    param <- .quote(ifelse(keys %in% reserved, paste0(keys, " (attribute)"), keys))
    cols <- c(sample = "sample", character())
    if (length(keys))
        cols <- c(cols, setNames(paste0("attribute", seq_along(keys)), param))
    mtd <- mtdFromSampleData(x, sampleCols. = cols,
                             msRunCols. = msRunCols(location = "location", scan_polarity = "scan_polarity"),
                             assayCols. = assayCols(assay = "assay"))
    if (length(polarity) > 1L)
        mtd <- .add_scan_polarity(mtd, polarity[-1L])
    else if (!length(polarity))  # RmzTabM needs a polarity to write: drop the placeholder
        mtd <- mtd[!grepl("^ms_run\\[\\d+\\]-scan_polarity\\[\\d+\\]$", mtd[, 1L]), , drop = FALSE]
    mtd
}

## The complete MTD: study level fields, unit, description and the MTD of the samples.
.mtd_study <- function(tbl, mtd) {
    unit <- tbl$unit
    args <- list(id = tbl$id, software = sprintf("[,, RmzTabM, %s]", packageVersion("RmzTabM")),
                 mztab_profile = "M+S")
    if (!is.null(unit)) {
        cv <- unname(.UNITS[unit])
        if (is.na(cv))
            cv <- sprintf("[,, %s, ]", .quote(unit))
        args$small_molecule_quantification_unit <- args$small_molecule_feature_quantification_unit <- cv
    }
    study <- rbind(do.call(mtdSkeleton, args), mtd)
    text <- paste0("MB-POST ", tbl$mbpost_id, ", ", tbl$source_file,
                   if (!is.null(tbl$sheet)) paste0(", sheet \"", tbl$sheet, "\""),
                   if (!is.null(tbl$block)) paste0(", ", tbl$block),
                   if (!is.null(tbl$description)) paste0(": ", tbl$description))
    study <- setMtdField(study, "description", text)
    if (!is.null(unit) && !is.na(.UNITS[unit])) {
        ncit <- .CVS[.CVS$label == "NCIT", ]
        study <- setMtdCv(study, label = ncit$label, full_name = ncit$full_name,
                          version = ncit$version, uri = ncit$uri)
    }
    .sort_index(study)
}

## The SML of a table: `rows` are its rows of the Parquet file, `mtd` its MTD.
mbpost_sml_table <- function(tbl, rows, mtd) {
    n <- length(tbl$sample)
    a <- as.matrix(rows[, paste0("abundance_assay[", seq_len(n), "]"), drop = FALSE])
    el <- .elements(rows$chemical_name)
    k <- lengths(el)
    one <- function(v, f = identity) .per_element(f(as.character(v)), k)
    opt <- list(feature_id = rows$feature_id, exp_mass_to_charge = .num15(rows$exp_mass_to_charge),
                retention_time_min = .num15(rows$retention_time_min), inchikey = rows$inchikey)
    opt <- opt[vapply(opt, function(v) any(!is.na(v)), NA)]
    sml <- do.call(smlCreate, c(list(
        x = a,
        database_identifier = ifelse(k > 1L, vapply(k, function(i) paste(rep("null", i), collapse = "|"), ""),
                                     NA_character_),
        chemical_formula = one(rows$chemical_formula, .formula2),
        smiles = one(rows$smiles),
        chemical_name = vapply(el, function(e) if (is.na(e[1L])) NA_character_ else paste(e, collapse = "|"), ""),
        theoretical_neutral_mass = one(.num15(rows$theoretical_neutral_mass)),
        adduct_ions = .adduct(rows$adduct_ions)), opt))
    sml <- smlAddStudyVariableColumns(sml, mtd)
    sml$SMH <- NULL
    ## RmzTabM takes the mean over all assays (NA if one is missing) but the
    ## variation without the missing ones: report neither if the mean is missing.
    for (col in grep("^abundance_study_variable\\[", names(sml), value = TRUE)) {
        cv <- sub("^abundance_", "abundance_variation_", col)
        miss <- !is.finite(sml[[col]])
        sml[[col]][miss] <- NA
        sml[[cv]][miss | !is.finite(sml[[cv]])] <- NA
    }
    sml
}

## The MTD and SML of one table of a TOML file, and what was assumed.
mbpost_table_to_mztabm <- function(tbl, rows) {
    pol <- .polarities(.adduct(rows$adduct_ions), tbl$id)
    mtd <- .mtd_study(tbl, mbpost_mtd_table(tbl, pol$polarity))
    list(MTD = mtd, SML = mbpost_sml_table(tbl, rows, mtd), polarity = pol)
}

## Check the written file: RmzTabM reads it back with the samples and the rows of
## the table, and its text holds the abundances of the table. (RmzTabM rounds
## the numbers it reads to 7 digits, so they are compared as text.)
.check_written <- function(path, tbl, rows) {
    z <- readMzTabM(path)
    n <- length(tbl$sample)
    mtd <- RmzTabM::mtd(z)
    samples <- getMtdField(mtd, "sample\\[\\d+\\]$")
    samples <- unname(samples[order(.index(names(samples), "^sample\\[(\\d+)\\]$"))])
    if (!identical(samples, vapply(tbl$sample, function(s) s$name, "")))
        stop("samples differ")
    if (nrow(RmzTabM::sml(z)) != nrow(rows))
        stop("SML has ", nrow(RmzTabM::sml(z)), " rows, expected ", nrow(rows))
    lines <- readLines(path, encoding = "UTF-8")
    field <- strsplit(lines[startsWith(lines, "SMH") | startsWith(lines, "SML")], "\t", fixed = TRUE)
    cols <- paste0("abundance_assay[", seq_len(n), "]")
    at <- match(cols, field[[1L]])
    if (anyNA(at))
        stop("abundance columns missing")
    got <- suppressWarnings(matrix(as.numeric(unlist(lapply(field[-1L], `[`, at))), ncol = n, byrow = TRUE))
    want <- as.matrix(rows[, cols])
    dimnames(want) <- NULL
    if (!identical(is.na(got), is.na(want)))
        stop("missing values differ")
    ok <- !is.na(want)
    if (any(abs(got[ok] - want[ok]) > 1e-14 * pmax(1, abs(want[ok]))))
        stop("abundances differ")
    invisible(TRUE)
}

## ---- files ----------------------------------------------------------------------------

## A file name for a table id: "#" -> "__", characters not allowed in file names -> "_".
.file_stem <- function(id) {
    x <- gsub("#", "__", id, fixed = TRUE)
    x <- gsub("[/\\\\:*?\"<>|[:cntrl:]]", "_", x)
    x <- sub("^\\.+", "", trimws(x))
    long <- nchar(x, "bytes") > 200
    x[long] <- substr(x[long], 1L, 100L)
    x
}

mbpost_to_mztabm <- function(input_dir = "mbpost_extracted", output_dir = "mztabm_extracted",
                             name_regex = "") {
    .use_utf8()
    dir.create(output_dir, recursive = TRUE, showWarnings = FALSE)
    tomls <- sort(list.files(input_dir, pattern = "\\.toml$"))
    tomls <- tomls[grepl(name_regex, sub("\\.toml$", "", tomls))]
    report <- list()
    used <- character()
    for (f in tomls) {
        stem <- sub("\\.toml$", "", f)
        header <- parseToml(file.path(input_dir, f), escape = FALSE)
        if (!length(header$table))
            next
        rows <- as.data.frame(read_parquet(file.path(input_dir, paste0(stem, ".parquet"))),
                              check.names = FALSE)
        for (tbl in header$table) {
            out <- .file_stem(tbl$id)
            while (tolower(out) %in% used)  # case-insensitive file systems
                out <- paste0(out, "_2")
            used <- c(used, tolower(out))
            path <- file.path(output_dir, paste0(out, ".mztab"))
            r <- rows[rows$table_id == tbl$id, , drop = FALSE]
            status <- tryCatch({
                if (nrow(r) != tbl$n_features)
                    stop("Parquet file has ", nrow(r), " rows, TOML ", tbl$n_features)
                res <- mbpost_table_to_mztabm(tbl, r)
                writeMzTabM(list(MTD = res$MTD, SML = .sml_text(res$SML)), path)
                .check_written(path, tbl, r)
                "ok"
            }, error = function(e) paste("failed:", conditionMessage(e)))
            if (status != "ok" && file.exists(path))
                file.remove(path)
            report[[length(report) + 1L]] <- data.frame(
                table_id = tbl$id, source_file = tbl$source_file, mztab = paste0(out, ".mztab"),
                n_assays = length(tbl$sample), n_rows = nrow(r),
                unit = if (is.null(tbl$unit)) "" else tbl$unit,
                polarity = if (status == "ok") paste(res$polarity$polarity, collapse = "+") else "",
                polarity_basis = if (status == "ok") res$polarity$basis else "",
                status = status, stringsAsFactors = FALSE)
            message(sprintf("%s: %s (%d assays, %d rows)", paste0(out, ".mztab"), status,
                            length(tbl$sample), nrow(r)))
        }
    }
    report <- do.call(rbind, report)
    write.table(report, file.path(output_dir, "mztabm_report.tsv"), sep = "\t", quote = FALSE,
                row.names = FALSE, na = "", fileEncoding = "UTF-8")
    invisible(report)
}

if (sys.nframe() == 0L) {
    args <- commandArgs(trailingOnly = TRUE)
    report <- mbpost_to_mztabm(
        input_dir = if (length(args) > 0L) args[1L] else "mbpost_extracted",
        output_dir = if (length(args) > 1L) args[2L] else "mztabm_extracted",
        name_regex = if (length(args) > 2L) args[3L] else "")
    failed <- sum(report$status != "ok")
    message("Wrote ", sum(report$status == "ok"), " mzTab-M files, ", failed, " failed")
    if (failed)
        quit(status = 1L)
}
