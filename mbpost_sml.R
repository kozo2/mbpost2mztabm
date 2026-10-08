## Extract the mzTab-M small molecule summary (SML) from an MB-POST result
## workbook and write it as Parquet, linked to the MTD written by
## mbpost_mtd.R.
##
## Usage: Rscript mbpost_sml.R [workbook.xlsx] [mtd.mztab] [output.parquet]
##
## Column abundance_assay[i] holds the abundances of assay[i] of the MTD, and
## abundance_study_variable[j] / abundance_variation_study_variable[j] are
## computed from the assay_refs and functions of study_variable[j]. The
## Parquet file metadata names the MTD file, its mzTab-ID and the assays and
## study variables the columns refer to. mzTab "null" values are stored as
## Parquet nulls.

suppressPackageStartupMessages(library(nanoparquet))
source("mbpost_mtd.R")

.as_number <- function(v) {
    n <- suppressWarnings(as.numeric(v))
    bad <- !is.na(v) & is.na(n)
    if (any(bad))
        stop("Non-numeric value(s): ", paste(unique(v[bad]), collapse = ", "))
    n
}

## "C40H80N1O8P1" -> "C40H80NO8P"
.formula <- function(x) {
    gsub("([A-Z][a-z]?)1(?![0-9])", "\\1", x, perl = TRUE)
}

## "[M + NH4]+" -> "[M+NH4]1+"
.adduct <- function(x) {
    sub("\\]([+-])$", "]1\\1", gsub(" ", "", x, fixed = TRUE))
}

## The lipid species of the abundance table. Class totals ("PC total") and
## the internal standards ("IS_...", without abundances) are not reported.
mbpost_lipids <- function(xlsx, sheet = 1L,
                          info = mbpost_sample_data(xlsx, sheet)) {
    x <- .read_sheet(xlsx, sheet)
    column <- function(pattern) x[, .find_cell(x, pattern)[["col"]]]
    rows <- seq.int(info$row + 3L, nrow(x))
    name <- column("^Lipid name$")[rows]
    keep <- !is.na(name) & !grepl(" total$", name) & !grepl("^IS_", name)
    rows <- rows[keep]
    abundance <- matrix(.as_number(x[rows, info$column]), nrow = length(rows),
                        dimnames = list(NULL, info$samples$assay))
    list(name = name[keep],
         formula = .formula(column("^Formula$")[rows]),
         mass = .as_number(column("^Exact Mass$")[rows]),
         adduct = .adduct(column("^Precursor-ion")[rows]),
         abundance = abundance)
}

## The SML abundance columns are numbered by the abundance columns of the
## workbook; check that the MTD numbers its assays the same way.
.check_mtd <- function(mtd, info, id) {
    assay <- getMtdField(mtd, "assay\\[\\d+\\]$")
    assay <- assay[order(.index(names(assay), "^assay\\[(\\d+)\\]$"))]
    if (!identical(unname(assay), info$samples$assay))
        stop("The assays of the MTD do not match the abundance columns of ",
             "the workbook:\n  MTD: ", paste(assay, collapse = ", "),
             "\n  workbook: ", paste(info$samples$assay, collapse = ", "))
    if (!identical(unname(getMtdField(mtd, "mzTab-ID")), id))
        stop("The mzTab-ID of the MTD is not \"", id, "\"")
}

mbpost_sml <- function(xlsx, mtd, id = sub("\\.xlsx$", "", basename(xlsx)),
                       sheet = 1L) {
    if (is(mtd, "MzTabM"))
        mtd <- RmzTabM::mtd(mtd)
    info <- mbpost_sample_data(xlsx, sheet)
    .check_mtd(mtd, info, id)
    lip <- mbpost_lipids(xlsx, sheet, info)
    sml <- smlCreate(x = lip$abundance,
                     chemical_formula = lip$formula,
                     chemical_name = lip$name,
                     theoretical_neutral_mass = lip$mass,
                     adduct_ions = lip$adduct)
    sml <- smlAddStudyVariableColumns(sml, mtd)
    sml$SMH <- NULL
    sml[] <- lapply(sml, function(v) {
        if (is.character(v))
            v[v == "null"] <- NA_character_
        v
    })
    ## smlCreate() stores these as text.
    sml$theoretical_neutral_mass <- lip$mass
    sml$best_id_confidence_value <- .as_number(sml$best_id_confidence_value)
    rownames(sml) <- NULL
    sml
}

## Parquet key-value metadata linking the SML to its MTD.
.sml_metadata <- function(mtd, mtd_file) {
    field <- function(f) {
        v <- getMtdField(mtd, f)
        paste(v[order(.index(names(v), "^.*\\[(\\d+)\\]$"))], collapse = "|")
    }
    c("mzTab-version" = field("mzTab-version"),
      "mzTab-ID" = field("mzTab-ID"),
      "mzTab-section" = "SML",
      "mzTab-MTD" = mtd_file,
      "mzTab-assay" = field("assay\\[\\d+\\]$"),
      "mzTab-study_variable" = field("study_variable\\[\\d+\\]$"))
}

if (sys.nframe() == 0L) {
    args <- commandArgs(trailingOnly = TRUE)
    xlsx <- if (length(args)) args[1L] else "mbpost_results/MPST000001.xlsx"
    id <- sub("\\.xlsx$", "", basename(xlsx))
    mtd_file <- if (length(args) > 1L) args[2L] else
        file.path("mztabm_results", paste0(id, ".mztab"))
    out <- if (length(args) > 2L) args[3L] else
        file.path(dirname(mtd_file), paste0(id, "_sml.parquet"))
    if (!file.exists(mtd_file)) {
        message("No MTD at ", mtd_file, "; writing it first")
        writeMzTabM(mbpost_mtd(xlsx, id), mtd_file)
    }
    mtd <- RmzTabM::mtd(readMzTabM(mtd_file))
    sml <- mbpost_sml(xlsx, mtd, id)
    dir.create(dirname(out), recursive = TRUE, showWarnings = FALSE)
    rel <- if (dirname(out) == dirname(mtd_file)) basename(mtd_file) else
        normalizePath(mtd_file)
    write_parquet(sml, out, metadata = .sml_metadata(mtd, rel))
    message("Wrote ", out, " (", nrow(sml), " small molecules x ",
            ncol(sml), " columns), linked to ", mtd_file)
}
