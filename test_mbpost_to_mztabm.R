## Tests of mbpost_to_mztabm.R on small synthetic tables (no data files needed).
##
## Usage, from the repository root: Rscript test_mbpost_to_mztabm.R

suppressMessages(source("mbpost_to_mztabm.R"))
.use_utf8()

n_tests <- 0L
check <- function(what, ok) {
    n_tests <<- n_tests + 1L
    if (!isTRUE(ok)) stop("FAILED: ", what, call. = FALSE)
}

## ---- text in mzTab-M notation -------------------------------------------------------
check("adducts in mzTab-M notation",
      identical(.adduct(c("[M + H]+", "(M-H)-", "[M ‒ H]‒", "[M+2H]2+", "[M + CH3COO]‒",
                          "[M+H+CH3OH]+", "[2M+Na]+", "792.6", "unknown", NA)),
                c("[M+H]1+", "[M-H]1-", "[M-H]1-", "[M+2H]2+", "[M+CH3COO]1-",
                  "[M+H+CH3OH]1+", "[2M+Na]1+", NA, NA, NA)))
check("formulas",
      identical(.formula2(c("C9 H15 N4 O8 P", "C40H80N1O8P1", "C36H61(D7)O5", "C23H39[2H]7NO7P", "C10H12", NA)),
                c("C9H15N4O8P", "C40H80NO8P", "C36H61[2H]7O5", "C23H39[2H]7NO7P", "C10H12", NA)))
check("quoting of parameters", identical(.quote(c("plain", "a, b", "say \"x\"")),
                                         c("plain", "\"a, b\"", "\"say \\\"x\\\"\"")))
check("numbers keep their digits", identical(.num15(c(624.58453167644, NA, 0.1)), c("624.58453167644", NA, "0.1")))
el <- .elements(c("PC 16:0", "Cer 30:1;2O|Cer 15:1;2", NA, "A||B", "|"))
check("name alternatives", identical(lengths(el), c(1L, 2L, 1L, 2L, 1L)) && identical(el[[2]], c("Cer 30:1;2O", "Cer 15:1;2")) &&
          is.na(el[[3]]) && is.na(el[[5]]))
check("a value per element", identical(.per_element(c("C2H6", NA, "X"), c(2L, 2L, 1L)), c("C2H6|C2H6", NA, "X")))

## ---- polarity -------------------------------------------------------------------------
check("polarity from adducts", identical(.polarities(c("[M+H]1+", NA, "[M-H]1-"), "T"),
                                         list(polarity = c("positive", "negative"), basis = "adduct ions")))
check("polarity from adducts, one sign", identical(.polarities(c("[M+H]1+", "[M+Na]1+"), "T")$polarity, "positive"))
check("polarity from the name", identical(.polarities(NA_character_, "MPST000044__Height_Neg"),
                                          list(polarity = "negative", basis = "name")))
check("no polarity", identical(.polarities(NA_character_, "MPST000044 positions"),
                               list(polarity = character(), basis = "none")))

## ---- file names -----------------------------------------------------------------------
check("file names", identical(.file_stem(c("MPST000001", "MPST000141__Copy#Height", "MPST000130#Rel (a/b): x?")),
                              c("MPST000001", "MPST000141__Copy__Height", "MPST000130__Rel (a_b)_ x_")))

## ---- a file with two tables ---------------------------------------------------------------
tmp <- tempfile("mbpost")
input <- file.path(tmp, "in")
output <- file.path(tmp, "out")
dir.create(input, recursive = TRUE)
writeLines(c(
    'generator = "x"', 'source_file = "MPST000999.xlsx"', 'mbpost_id = "MPST000999"', 'n_tables = 2', '',
    '[[table]]', 'id = "MPST000999#A"', 'mbpost_id = "MPST000999"', 'source_file = "MPST000999.xlsx"',
    'sheet = "A"', 'features_in = "rows"', 'n_features = 3', 'n_samples = 3', 'unit = "nmol/mg-protein"',
    'description = "A table"',
    '[[table.sample]]', 'assay = 1', 'name = "S1"', 'column = "B"',
    '[table.sample.attributes]', '"Sample (peak area, cell number)" = "x, y"', 'sample = "1"', 'group = "a|b"',
    '[[table.sample]]', 'assay = 2', 'name = "S2"', 'column = "C"',
    '[table.sample.attributes]', 'group = "b"',
    '[[table.sample]]', 'assay = 3', 'name = "S 3 µ"', 'column = "D"',
    '[table.sample.attributes]', 'group = "b"', '',
    '[[table]]', 'id = "MPST000999#B#Peak area"', 'mbpost_id = "MPST000999"', 'source_file = "MPST000999.xlsx"',
    'sheet = "B"', 'block = "Peak area"', 'features_in = "rows"', 'n_features = 2', 'n_samples = 2',
    '[[table.sample]]', 'assay = 1', 'name = "T1"', 'column = "B"',
    '[[table.sample]]', 'assay = 2', 'name = "T2"', 'column = "C"'),
    file.path(input, "MPST000999.toml"), useBytes = TRUE)
pq <- data.frame(
    table_id = c("MPST000999#A", "MPST000999#A", "MPST000999#A", "MPST000999#B#Peak area", "MPST000999#B#Peak area"),
    feature_index = c(1L, 2L, 3L, 1L, 2L), source_position = c(2L, 3L, 4L, 2L, 3L),
    chemical_name = c("PC 16:0", "Cer 30:1;2O|Cer 15:1;2", NA, "Glc", "Unknown"),
    feature_id = c(NA, NA, NA, "7", "8"), chemical_formula = c("C24 H50 N1 O7 P1", "C30H59NO3", NA, NA, NA),
    adduct_ions = c("[M + H]+", "(M-H)-", NA, NA, NA), smiles = NA_character_, inchikey = NA_character_,
    theoretical_neutral_mass = c(495.331, 481.4495, NA, NA, NA), exp_mass_to_charge = c(NA, NA, NA, 180.0634, 99.99),
    retention_time_min = c(NA, NA, NA, 5.1, 6.2), stringsAsFactors = FALSE, check.names = FALSE)
pq[["abundance_assay[1]"]] <- c(1.5, 0, NA, 10, 20)
pq[["abundance_assay[2]"]] <- c(2.25, 3, NA, 11, NA)
pq[["abundance_assay[3]"]] <- c(0.1 + 0.2, NA, NA, NA, NA)  # 0.30000000000000004; one missing in row 2
write_parquet(pq, file.path(input, "MPST000999.parquet"))
## a file without a table has only a TOML file
writeLines(c('source_file = "MPST000998.xlsx"', 'n_tables = 0'), file.path(input, "MPST000998.toml"))

report <- mbpost_to_mztabm(input, output)
check("one mzTab-M file per table", identical(sort(list.files(output, "\\.mztab$")),
                                              c("MPST000999__A.mztab", "MPST000999__B__Peak area.mztab")))
check("report", identical(report$status, c("ok", "ok")) && identical(report$n_rows, c(3L, 2L)) &&
          identical(report$polarity, c("positive+negative", "")))

a <- readLines(file.path(output, "MPST000999__A.mztab"), encoding = "UTF-8")
mtd <- function(key) sub("^MTD\t[^\t]*\t", "", grep(paste0("^MTD\t", key, "\t"), a, value = TRUE, fixed = FALSE))
check("study level fields", identical(mtd("mzTab-ID"), "MPST000999#A") && identical(mtd("mzTab-profile"), "M+S") &&
          grepl("MPST000999.xlsx, sheet \"A\": A table", mtd("description"), fixed = TRUE))
check("a known unit is an NCIT term",
      identical(mtd("small_molecule-quantification_unit"), "[NCIT, NCIT:C67433, Nanomole per Milligram of Protein, ]") &&
          any(grepl("^MTD\tcv\\[\\d+\\]-label\tNCIT$", a)))
check("sample names", identical(mtd("sample\\[\\d+\\]"), c("S1", "S2", "S 3 µ")))
check("attributes with commas are quoted, '|' is replaced",
      identical(mtd("sample\\[1\\]-custom\\[1\\]"), "[,,\"Sample (peak area, cell number)\", \"x, y\"]") &&
          "[,,group, a/b]" %in% mtd("sample\\[1\\]-custom\\[\\d+\\]"))
check("a reserved attribute name is renamed", "[,,sample (attribute), 1]" %in% mtd("sample\\[1\\]-custom\\[\\d+\\]"))
check("a missing attribute is null", "[,,sample (attribute), null]" %in% mtd("sample\\[2\\]-custom\\[\\d+\\]") ||
          "[,,\"Sample (peak area, cell number)\", null]" %in% mtd("sample\\[2\\]-custom\\[\\d+\\]"))
check("one assay and one run per sample, one study variable", identical(mtd("assay\\[\\d+\\]-ms_run_ref"), paste0("ms_run[", 1:3, "]")) &&
          identical(mtd("study_variable\\[1\\]-assay_refs"), "assay[1]|assay[2]|assay[3]"))
check("both polarities of the adducts", length(mtd("ms_run\\[3\\]-scan_polarity\\[\\d+\\]")) == 2L)
smh <- grep("^SMH", a)
col <- strsplit(a[smh], "\t")[[1L]]
row <- function(i) setNames(strsplit(a[smh + i], "\t")[[1L]], col)
check("list fields follow the names", identical(unname(row(2)[c("chemical_name", "database_identifier", "chemical_formula",
                                                              "theoretical_neutral_mass", "adduct_ions")]),
                                                c("Cer 30:1;2O|Cer 15:1;2", "null|null", "C30H59NO3|C30H59NO3",
                                                  "481.4495|481.4495", "[M-H]1-")))
check("formula and adduct in mzTab-M notation", identical(unname(row(1)[c("chemical_formula", "adduct_ions")]),
                                                          c("C24H50NO7P", "[M+H]1+")))
check("a row without name, formula or abundance", identical(unname(row(3)[c("chemical_name", "chemical_formula", "abundance_assay[1]")]),
                                                            c("null", "null", "null")))
check("exact abundances and zero", identical(unname(row(1)["abundance_assay[3]"]), "0.30000000000000004") &&
          identical(unname(row(2)["abundance_assay[1]"]), "0"))
stat <- c("abundance_study_variable[1]", "abundance_variation_study_variable[1]")
check("statistics are null if an assay is missing (RmzTabM would give the variation of the others)",
      identical(unname(row(2)[stat]), c("null", "null")) && identical(unname(row(3)[stat]), c("null", "null")))
full <- c(1.5, 2.25, 0.30000000000000004)
check("statistics are the mean and variation otherwise",
      abs(as.numeric(row(1)[stat[1L]]) - mean(full)) < 1e-12 && abs(as.numeric(row(1)[stat[2L]]) - sd(full) / mean(full)) < 1e-12)
check("no NA, NaN or Inf in the SML", !any(grepl("\t(NA|NaN|Inf)(\t|$)", a[startsWith(a, "SML")])))
check("optional columns only where there are values", !any(grepl("opt_global_feature_id", a[smh])) &&
          !any(grepl("opt_global_inchikey", a[smh])))

b <- readLines(file.path(output, "MPST000999__B__Peak area.mztab"), encoding = "UTF-8")
check("no unit: arbitrary quantification unit, no polarity, optional columns",
      any(grepl("\tsmall_molecule-quantification_unit\t\\[PRIDE, PRIDE:0000330, Arbitrary quantification unit, \\]$", b)) &&
          !any(grepl("scan_polarity", b)) && any(grepl("opt_global_feature_id", b[grep("^SMH", b)])) &&
          any(grepl("^MTD\tdescription\tMB-POST MPST000999, MPST000999.xlsx, sheet \"B\", Peak area$", b)))
check("a missing value of the last assay and the file reads back with RmzTabM", nrow(RmzTabM::sml(readMzTabM(file.path(output, "MPST000999__B__Peak area.mztab")))) == 2L)

## ---- a table that does not match its Parquet file is reported and leaves no file --------------
unlink(output, recursive = TRUE)
lines <- readLines(file.path(input, "MPST000999.toml"), encoding = "UTF-8")
writeLines(sub("n_features = 3", "n_features = 4", lines, fixed = TRUE), file.path(input, "MPST000999.toml"), useBytes = TRUE)
report <- mbpost_to_mztabm(input, output)
check("a mismatch is a failure without output file",
      grepl("^failed: Parquet file has 3 rows, TOML 4", report$status[1L]) && report$status[2L] == "ok" &&
          !file.exists(file.path(output, "MPST000999__A.mztab")))

unlink(tmp, recursive = TRUE)
message("All ", n_tests, " checks passed")
