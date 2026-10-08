## Add the SML section stored in the Parquet file written by mbpost_sml.R to
## the mzTab-M file holding its MTD.
##
## Usage: Rscript mbpost_mztab.R [sml.parquet] [input.mztab] [output.mztab]
##
## The input defaults to the MTD file named in the Parquet metadata and the
## output to the input. Only the MTD of the input is kept (an SML already in
## it is replaced) and its mzTab-profile is set to "M+S".

source("mbpost_sml.R")

.parquet_kv <- function(file) {
    kv <- read_parquet_metadata(file)$file_meta_data$key_value_metadata[[1L]]
    setNames(kv$value, kv$key)
}

## The Parquet file has to be made for this MTD and provide an abundance
## column for every assay and study variable.
.check_link <- function(kv, mtd, sml) {
    keys <- c("mzTab-ID", "mzTab-assay", "mzTab-study_variable")
    exp <- .sml_metadata(mtd, "")
    bad <- keys[is.na(kv[keys]) | kv[keys] != exp[keys]]
    if (length(bad))
        stop("The Parquet file was not made for this MTD: ",
             paste(bad, collapse = ", "), " differ")
    sv <- names(getMtdField(mtd, "study_variable\\[\\d+\\]$"))
    cols <- c(paste0("abundance_", names(getMtdField(mtd, "assay\\[\\d+\\]$"))),
              paste0("abundance_", sv), paste0("abundance_variation_", sv))
    abund <- grep("^abundance_", names(sml), value = TRUE)
    if (!setequal(cols, abund))
        stop("Abundance columns not matching the MTD: ",
             paste(c(setdiff(cols, abund), setdiff(abund, cols)),
                   collapse = ", "))
}

## 17 significant digits read back as the same double with a correctly
## rounded parser (writeMzTabM() would use 15). R itself can be 1 ulp off
## when built without long double.
.num_text <- function(x) {
    out <- sprintf("%.17g", x)
    out[is.na(x)] <- NA_character_
    out
}

## SML text columns with "null" for missing values (writeMzTabM() would
## write "NA").
.sml_text <- function(sml) {
    sml[] <- lapply(sml, function(v) {
        v <- if (is.double(v)) .num_text(v) else as.character(v)
        v[is.na(v)] <- "null"
        v
    })
    data.frame(SMH = "SML", smlSort(sml), check.names = FALSE)
}

if (sys.nframe() == 0L) {
    args <- commandArgs(trailingOnly = TRUE)
    pq <- if (length(args)) args[1L] else
        "mztabm_results/MPST000001_sml.parquet"
    kv <- .parquet_kv(pq)
    mtd_file <- if (length(args) > 1L) args[2L] else kv[["mzTab-MTD"]]
    if (length(args) < 2L && !grepl("^(/|[A-Za-z]:)", mtd_file))
        mtd_file <- file.path(dirname(pq), mtd_file)
    out <- if (length(args) > 2L) args[3L] else mtd_file
    mtd <- RmzTabM::mtd(readMzTabM(mtd_file))
    sml <- as.data.frame(read_parquet(pq), check.names = FALSE)
    .check_link(kv, mtd, sml)
    mtd <- setMtdField(mtd, "mzTab-profile", "M+S")
    writeMzTabM(list(MTD = mtd, SML = .sml_text(sml)), out)
    message("Wrote ", out, ": MTD (", nrow(mtd), " rows) + SML (",
            nrow(sml), " rows) from ", pq)
}
