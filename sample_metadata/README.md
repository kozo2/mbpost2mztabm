# MPST000001 sample metadata

`MPST000001_samples.tsv` contains one row per abundance column, in the original
Excel column order. The source is `MPST000001.xlsx`, sheet `Table 1`:

| Cell line label | Replicate labels | Excel columns | Assay indices |
| --- | --- | --- | --- |
| Ba/F3 | 1–5 | K–O | 1–5 |
| Tm63bnull | 1–5 | P–T | 6–10 |
| Tm63bnull-mTMEM63B | 1–5 | U–Y | 11–15 |

The abundance header is K2, group labels are in row 3, and replicate labels
are in row 4. Group labels are filled across their merged header cells.
`source_column` and the header-cell columns retain extraction provenance;
some group-header cells are blank in Excel because they belong to a merge.
The quantification unit is `nmol/mg-protein`.

The generated assay/sample IDs concatenate the group label and replicate number.
Assay indices follow abundance-column order for alignment with SML/SMF columns.
Treating each abundance column as a separate sample is a working mapping: the
workbook does not specify whether the replicates are biological or technical.
If technical replicates share a biological sample, adjust `sample` accordingly.

Species, tissue, cell type, disease, acquisition-file names and per-run polarity
are not stated in this workbook. `location` and `scan_polarity` are `null`
placeholders. The precursor-ion column contains both positive and negative ions,
but does not establish the acquisition-run layout or each run's polarity.

`MPST000001_sample_mtd.tsv` is an MTD fragment containing only sample names,
descriptions, and custom `cell_line` and `replicate` parameters. It is not a
complete mzTab-M file. No species or cell-type annotations have been inferred.

## R use

```r
source("extract_mbpost_samples.R")
samples <- extract_mbpost_samples("mbpost_results/MPST000001.xlsx")
# Alternatively:
# samples <- read.delim("sample_metadata/MPST000001_samples.tsv",
#                       stringsAsFactors = FALSE, check.names = FALSE)

sample_mtd <- mbpost_extracted_sample_mtd(samples)
# sample_mtd is a two-column character matrix for combining with other MTD.
```

To build sample, run, assay and study-variable MTD together, supply the actual
run mapping first. RmzTabM 0.99.2 requires `positive` or `negative` in the
`scan_polarity` column; it does not accept `null` through `mtdFromSampleData()`.
The following applies when there is one measurement run per abundance column:

```r
library(RmzTabM)
# Fill samples$location with the corresponding file URIs (or "null" if absent).
# Fill samples$scan_polarity with confirmed "positive" / "negative" values.
stopifnot(all(samples$scan_polarity %in% c("positive", "negative")))
mtd_samples_runs_assays <- mtdFromSampleData(
    samples,
    sampleCols. = sampleCols(sample = "sample", description = "description",
                            cell_line = "cell_line", replicate = "replicate"),
    msRunCols. = msRunCols(location = "location", scan_polarity = "scan_polarity"),
    assayCols. = assayCols(assay = "assay"),
    groups = "cell_line",
    group_description = "Cell line label in the workbook abundance header"
)
# This already includes sample_mtd's fields; use it instead of adding both.
# Add the experiment's core MTD and the other mzTab-M sections separately.
```

For multiple acquisition runs per assay, expand the table to one row per run,
retaining the same assay ID, before using `mtdFromSampleData()`. For runs that
contain both polarities, add the confirmed indexed scan-polarity MTD fields
with the lower-level helpers; do not assign a single polarity from this table.

Regenerate the extraction with:

```sh
Rscript extract_mbpost_samples.R
```

Package reference: https://rformassspectrometry.github.io/RmzTabM/reference/MTD-export.html
