## Build the mzTab-M metadata (MTD) section from an MB-POST result workbook.
##
## Usage: Rscript mbpost_mtd.R [workbook.xlsx] [output.mztab]
##
## The sample groups, replicates, quantification unit and scan polarities are
## read from the abundance table header of the workbook. Information the
## workbook does not provide (species, cell type, MS data files) is set below.

suppressPackageStartupMessages({
    library(readxl)
    library(RmzTabM)
})

## Not stated in the workbook: Ba/F3 is a murine pro-B cell line and the other
## groups (Tm63bnull, Tm63bnull-mTMEM63B) are lines derived from it.
.SPECIES <- "[NCBITaxon, NCBITaxon:10090, Mus musculus, ]"
.CELL_TYPE <- "[CL, CL:0000826, pro-B cell, ]"

## MRM transitions are fragmented in the collision cell (Collision energy (V)).
.FRAGMENTATION <- "[MS, MS:1000133, collision-induced dissociation, ]"

## Unit labels of the abundance table header and their CV terms.
.UNITS <- c(
    "nmol/mg-protein" =
        "[NCIT, NCIT:C67433, Nanomole per Milligram of Protein, ]")

## CVs referenced above, in addition to the mtdSkeleton() defaults.
.CVS <- data.frame(
    label = c("NCBITaxon", "CL", "NCIT"),
    full_name = c("NCBI organismal classification", "Cell Ontology",
                  "NCI Thesaurus OBO Edition"),
    version = c("2026-07-12", "2026-06-08", "26.02d"),
    uri = c("https://www.ebi.ac.uk/ols4/ontologies/ncbitaxon",
            "https://www.ebi.ac.uk/ols4/ontologies/cl",
            "https://www.ebi.ac.uk/ols4/ontologies/ncit"))

.POLARITY_CV <- c(positive = "[MS, MS:1000130, positive scan, ]",
                  negative = "[MS, MS:1000129, negative scan, ]")

.read_sheet <- function(xlsx, sheet = 1L) {
    x <- read_excel(xlsx, sheet = sheet, col_names = FALSE,
                    col_types = "text", .name_repair = "minimal")
    x <- as.matrix(x)
    x[] <- trimws(gsub("\\s+", " ", x))
    x
}

.find_cell <- function(x, pattern) {
    hit <- which(matrix(grepl(pattern, x), nrow(x)), arr.ind = TRUE)
    if (nrow(hit) != 1L)
        stop("Expected one cell matching '", pattern, "', found ", nrow(hit))
    hit[1L, ]
}

## Merged header cells are only filled in their first column.
.fill_right <- function(v) {
    c(NA_character_, v[!is.na(v)])[cumsum(!is.na(v)) + 1L]
}

## Polarities in the order positive, negative, from ions like "[M + H]+".
.polarity <- function(ion) {
    ion <- ion[!is.na(ion)]
    pol <- c("+" = "positive", "-" = "negative")[substring(ion, nchar(ion))]
    if (anyNA(pol))
        stop("Unsupported precursor ion(s): ",
             paste(unique(ion[is.na(pol)]), collapse = ", "))
    intersect(names(.POLARITY_CV), pol)
}

## Returns the sample data (one row per assay, i.e. abundance column) along
## with the table caption, quantification unit, scan polarities and the
## header row and abundance columns of the sheet read by .read_sheet().
mbpost_sample_data <- function(xlsx, sheet = 1L) {
    x <- .read_sheet(xlsx, sheet)
    amount <- .find_cell(x, "^Amount of .*\\(.+\\)$")
    r <- amount[["row"]]
    cols <- seq.int(amount[["col"]], ncol(x))
    group <- .fill_right(x[r + 1L, cols])
    replicate <- x[r + 2L, cols]
    keep <- !is.na(group) & !is.na(replicate)
    if (!any(keep))
        stop("No sample group / replicate found below the abundance header")
    group <- group[keep]
    replicate <- replicate[keep]
    assay <- paste0(group, "_", replicate)
    if (anyDuplicated(assay))
        stop("Duplicated sample group / replicate: ",
             paste(unique(assay[duplicated(assay)]), collapse = ", "))
    ion <- .find_cell(x, "^Precursor-ion")
    polarity <- .polarity(x[seq.int(r + 3L, nrow(x)), ion[["col"]]])
    samples <- data.frame(
        assay = assay,
        sample = assay,
        cell_line = group,
        replicate = as.integer(replicate),
        species = .SPECIES,
        cell_type = .CELL_TYPE,
        description = sprintf("%s, replicate %s", group, replicate),
        location = "null",
        polarity = polarity[1L],
        fragmentation_method = .FRAGMENTATION)
    list(samples = samples,
         caption = grep("^Supplementary Table", x, value = TRUE)[1L],
         unit = sub("^Amount of .*\\((.+)\\)$", "\\1", x[r, amount[["col"]]]),
         polarity = polarity,
         row = r,
         column = cols[keep])
}

## mtdMsRun() only reports scan_polarity[1]; add the other polarities of each
## run (placed next to it by .sort_index()).
.add_scan_polarity <- function(mtd, polarity) {
    k <- length(polarity)
    run <- sub("-location$", "", grep("^ms_run\\[\\d+\\]-location$",
                                      mtd[, 1L], value = TRUE))
    if (!k || !length(run))
        return(mtd)
    rbind(mtd, cbind(
        paste0(rep(run, each = k), "-scan_polarity[",
               rep(seq_len(k) + 1L, length(run)), "]"),
        rep(.POLARITY_CV[polarity], length(run))))
}

.index <- function(x, pattern) {
    i <- rep(0L, length(x))
    has <- grepl(pattern, x)
    i[has] <- as.integer(sub(pattern, "\\1", x[has]))
    i
}

## RmzTabM 0.99.2 orders sample, assay and ms_run fields by their index as
## text (sample[10] before sample[2]). Reorder each section by index, then
## the fields of an index in the order they first appear in the section
## (e.g. ms_run[i]-location, -scan_polarity[1], -scan_polarity[2], ...).
.sort_index <- function(mtd) {
    mtd <- mtdSort(mtd)
    name <- mtd[, 1L]
    section <- sub("\\[.*$", "", name)
    rest <- sub("^[^[]+(\\[\\d+\\])?", "", name)
    field <- paste(section, sub("\\[\\d+\\]$", "", rest))
    mtd[order(match(section, unique(section)),
              .index(name, "^[^[]+\\[(\\d+)\\].*$"),
              match(field, unique(field)),
              .index(rest, "^.*\\[(\\d+)\\]$")), , drop = FALSE]
}

mbpost_mtd <- function(xlsx, id = sub("\\.xlsx$", "", basename(xlsx)),
                       sheet = 1L) {
    info <- mbpost_sample_data(xlsx, sheet)
    unit <- unname(.UNITS[info$unit])
    if (is.na(unit))
        unit <- sprintf("[,, %s, ]", info$unit)
    mtd <- mtdSkeleton(
        id = id,
        software = sprintf("[,, RmzTabM, %s]", packageVersion("RmzTabM")),
        quantification_method = "[MS, MS:1001838, SRM quantitation analysis, ]",
        small_molecule_quantification_unit = unit,
        small_molecule_feature_quantification_unit = unit,
        mztab_profile = "M")
    sd <- mtdFromSampleData(
        info$samples,
        sampleCols. = sampleCols(sample = "sample", species = "species",
                                 cell_type = "cell_type",
                                 description = "description"),
        msRunCols. = msRunCols(location = "location",
                               scan_polarity = "polarity",
                               fragmentation_method = "fragmentation_method"),
        assayCols. = assayCols(assay = "assay"),
        groups = "cell_line",
        group_description = "Cell line of the abundance table column groups")
    mtd <- rbind(mtd, .add_scan_polarity(sd, info$polarity[-1L]))
    if (!is.na(info$caption))
        mtd <- setMtdField(mtd, "description", info$caption)
    mtd <- setMtdCv(mtd, label = .CVS$label, full_name = .CVS$full_name,
                    version = .CVS$version, uri = .CVS$uri)
    MzTabM(mtd = .sort_index(mtd))
}

if (sys.nframe() == 0L) {
    args <- commandArgs(trailingOnly = TRUE)
    xlsx <- if (length(args)) args[1L] else "mbpost_results/MPST000001.xlsx"
    id <- sub("\\.xlsx$", "", basename(xlsx))
    out <- if (length(args) > 1L) args[2L] else
        file.path("mztabm_results", paste0(id, ".mztab"))
    m <- mbpost_mtd(xlsx, id)
    writeMzTabM(m, out)
    message("Wrote ", out, " (", nrow(mtd(m)), " MTD rows)")
}
