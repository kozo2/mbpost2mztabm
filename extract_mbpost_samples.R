# Extract abundance-column metadata without adding biological annotations.
# Usage: Rscript extract_mbpost_samples.R [workbook.xlsx] [output_directory]

extract_mbpost_samples <- function(xlsx = "mbpost_results/MPST000001.xlsx",
                                  sheet = 1L) {
    if (!requireNamespace("readxl", quietly = TRUE))
        stop("Install the readxl package to read the workbook.")
    sheets <- readxl::excel_sheets(xlsx)
    sheet_name <- if (is.numeric(sheet)) sheets[[sheet]] else sheet
    x <- as.matrix(readxl::read_excel(
        xlsx, sheet = sheet_name, col_names = FALSE,
        col_types = "text", .name_repair = "minimal"))
    x[] <- trimws(gsub("\\s+", " ", x))
    x[!is.na(x) & x == ""] <- NA_character_
    hit <- which(!is.na(x) & grepl("^Amount of .*\\(.+\\)$", x),
                 arr.ind = TRUE)
    if (nrow(hit) != 1L)
        stop("Expected exactly one abundance-table header.")
    header_row <- hit[1L, "row"]
    if (header_row + 2L > nrow(x))
        stop("Missing group and replicate header rows.")
    columns <- seq.int(hit[1L, "col"], ncol(x))
    group <- x[header_row + 1L, columns]
    # Merged cells are populated only in the first column of each group.
    for (j in seq_along(group))
        if (j > 1L && is.na(group[j])) group[j] <- group[j - 1L]
    replicate <- x[header_row + 2L, columns]
    keep <- !is.na(replicate)
    if (!any(keep) || anyNA(group[keep]))
        stop("Missing sample group / replicate labels.")
    group <- group[keep]
    replicate <- replicate[keep]
    columns <- columns[keep]
    if (any(!grepl("^[1-9][0-9]*$", replicate)))
        stop("Replicate labels must be positive integers.")
    sample_id <- paste0(group, "_", replicate)
    if (anyDuplicated(sample_id))
        stop("Duplicate group / replicate combinations.")
    excel_column <- function(n) {
        label <- ""
        while (n > 0L) {
            label <- paste0(LETTERS[(n - 1L) %% 26L + 1L], label)
            n <- (n - 1L) %/% 26L
        }
        label
    }
    unit <- sub("^Amount of .*\\((.+)\\)$", "\\1",
                x[header_row, hit[1L, "col"]])
    data.frame(
        assay_index = seq_along(sample_id),
        assay = sample_id,
        sample = sample_id,
        cell_line = group,
        replicate = as.integer(replicate),
        study_variable_index = match(group, unique(group)),
        description = sprintf("%s, replicate %s", group, replicate),
        quantification_unit = unit,
        location = "null",
        scan_polarity = "null",
        source_file = basename(xlsx),
        source_sheet = sheet_name,
        source_column = vapply(columns, excel_column, character(1)),
        group_header_cell = paste0(vapply(columns, excel_column, character(1)),
                                   header_row + 1L),
        replicate_header_cell = paste0(vapply(columns, excel_column, character(1)),
                                       header_row + 2L),
        stringsAsFactors = FALSE
    )
}

# Sample MTD only: combine with the core, assay, run and study-variable MTD
# of the final experiment. Custom parameters preserve the workbook labels.
mbpost_extracted_sample_mtd <- function(samples) {
    if (!requireNamespace("RmzTabM", quietly = TRUE))
        stop("Install RmzTabM to generate the sample MTD matrix.")
    RmzTabM::mtdSample(
        sample = samples$sample,
        description = samples$description,
        cell_line = samples$cell_line,
        replicate = as.character(samples$replicate))
}

if (sys.nframe() == 0L) {
    args <- commandArgs(trailingOnly = TRUE)
    xlsx <- if (length(args)) args[1L] else "mbpost_results/MPST000001.xlsx"
    outdir <- if (length(args) > 1L) args[2L] else "sample_metadata"
    samples <- extract_mbpost_samples(xlsx)
    sample_mtd <- mbpost_extracted_sample_mtd(samples)
    dir.create(outdir, recursive = TRUE, showWarnings = FALSE)
    id <- tools::file_path_sans_ext(basename(xlsx))
    utils::write.table(samples, file.path(outdir, paste0(id, "_samples.tsv")),
                       sep = "\t", quote = FALSE, row.names = FALSE, na = "null")
    utils::write.table(cbind("MTD", sample_mtd),
                       file.path(outdir, paste0(id, "_sample_mtd.tsv")),
                       sep = "\t", quote = FALSE, row.names = FALSE,
                       col.names = FALSE, na = "null")
    message("Extracted ", nrow(samples), " abundance columns across ",
            length(unique(samples$cell_line)), " groups to ", outdir)
}
