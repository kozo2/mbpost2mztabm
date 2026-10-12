# mbpost2mztabm

Convert lipidomics results deposited in MB-POST as Excel workbooks to
[mzTab-M 2.1](https://github.com/HUPO-PSI/mzTab) with
[RmzTabM](https://github.com/RforMassSpectrometry/RmzTabM).
The first converted data set is `MPST000001`: quantitative lipidomics
(DEA-SFC/MS/MS, MRM) of three Ba/F3 cell lines with five replicates each.

## Files

| Path | Content |
| --- | --- |
| `mbpost_results/` | All `result`-tagged files of every public MB-POST project (150 files, 113 projects), see [Downloading MB-POST result files](#downloading-mb-post-result-files) |
| `mbpost_results/manifest.json`, `manifest.csv` | Project, original name, size and checksum of each downloaded file |
| `download_mbpost_results.py` | Downloader for the `result`-tagged files |
| `extract_mbpost_tables.py` | Exports the sample metadata (TOML) and the quantification tables (Parquet) of all result files, see [Extracting sample metadata and quantification tables](#extracting-sample-metadata-and-quantification-tables) |
| `mbpost_extracted/` | Its output: `<file>.toml` and `<file>.parquet` for each file of `mbpost_results/` (45 MB in all), and `mbpost_extraction_report.tsv` |
| `test_extract_mbpost_tables.py` | Tests of its layout detection (synthetic sheets, no data files needed) |
| `mbpost_to_mztabm.R` | Converts the TOML / Parquet files to mzTab-M (MTD + SML) with RmzTabM, see [Converting the extracted tables to mzTab-M](#converting-the-extracted-tables-to-mztab-m) |
| `mztabm_extracted/` | Its output: one `.mztab` per quantification table (215 files, 100 MB) and `mztabm_report.tsv` |
| `test_mbpost_to_mztabm.R` | Tests of the conversion (synthetic tables, no data files needed) |
| `mbpost_mtd.R` | Step 1: metadata (MTD) section |
| `mbpost_sml.R` | Step 2: small molecule summary (SML) as Parquet |
| `mbpost_mztab.R` | Step 3: adds the SML to the mzTab-M file |
| `mztabm_results/MPST000001.mztab` | mzTab-M file, MTD + SML (`mzTab-profile M+S`) |
| `mztabm_results/MPST000001_sml.parquet` | SML table (244 rows x 34 columns) |
| `extract_mbpost_samples.R`, `sample_metadata/` | Separate sample table extraction, see [Other files](#other-files) |

## Requirements

Python 3.9+ for the downloader (stdlib only, no packages needed). Python 3.11+
with openpyxl, pyarrow and tomli-w for the table extractor. Create the
environment with [uv](https://docs.astral.sh/uv/):

```sh
/home/knishida/.local/bin/uv venv .venv
uv pip install --python .venv/bin/python openpyxl pyarrow tomli-w   # extractor only
```

R >= 4.6 with RmzTabM (tested with 0.99.2), readxl and nanoparquet (0.5.2), and
RcppTOML (0.2.3) for `mbpost_to_mztabm.R`:

```r
remotes::install_github("RforMassSpectrometry/RmzTabM")
install.packages(c("readxl", "nanoparquet", "RcppTOML"))
```

## Usage

Run the scripts from the repository root:

```sh
Rscript mbpost_mtd.R    # -> mztabm_results/MPST000001.mztab (MTD only)
Rscript mbpost_sml.R    # -> mztabm_results/MPST000001_sml.parquet
Rscript mbpost_mztab.R  # -> mztabm_results/MPST000001.mztab (MTD + SML)
```

Each script takes optional paths:

```sh
Rscript mbpost_mtd.R   [workbook.xlsx] [output.mztab]
Rscript mbpost_sml.R   [workbook.xlsx] [mtd.mztab] [output.parquet]
Rscript mbpost_mztab.R [sml.parquet] [input.mztab] [output.mztab]
```

Step 1 overwrites the mzTab-M file with the MTD alone; run step 3 again
afterwards. Step 3 keeps only the MTD of its input, so it can be re-run.
The outputs are deterministic: a clean run reproduces the committed files
byte for byte.

## Downloading MB-POST result files

`download_mbpost_results.py` downloads every `result`-tagged file of every
public project at <https://repository.massbank.jp/> into `mbpost_results/`.
It lists projects via the public API (`/api/projects`), keeps each project's
files whose `type` is `result` (`/api/projects/<location>/files`), downloads
them (`/data/<location>/<name>`), and verifies each against the `size` and
`checksum` (MD5) reported by the API. Files that already verify are skipped,
so re-runs only fetch what is new or changed.

```sh
.venv/bin/python download_mbpost_results.py --dry-run   # list only (150 files, ~212 MB)
.venv/bin/python download_mbpost_results.py             # download all
.venv/bin/python download_mbpost_results.py --projects MPST000001,MPST000003
```

Useful options: `--out` (output directory, default `mbpost_results`),
`--workers` (parallel downloads, default 4), `--overwrite` (re-download
everything), `--manifest` (manifest path, default `<out>/manifest.json`,
plus a `.csv` copy). See `--help` for all options.

Local names keep the source traceable: a project with one result file is
stored as `<MBPOSTID><original extension>` (e.g. `MPST000001.xlsx`); a
project with several is stored as `<MBPOSTID>__<original file name>` (e.g.
`MPST000222__cecum_results.xlsx`). `manifest.json`/`manifest.csv` map each
local file back to its project, original name, size and checksum.

## Extracting sample metadata and quantification tables

`extract_mbpost_tables.py` reads every `.xlsx`, `.csv` and `.txt` file in
`mbpost_results/` and writes, for each file, the inputs for generating an mzTab-M
file with RmzTabM to `mbpost_extracted/`:

```sh
.venv/bin/python extract_mbpost_tables.py                       # all files, about 25 s
.venv/bin/python extract_mbpost_tables.py --include 'MPST000001*' 'MPST000012*'
.venv/bin/python -m unittest test_extract_mbpost_tables         # tests of the layout detection
```

| File | Content |
| --- | --- |
| `<name>.toml` | The sample metadata of `<name>.<ext>`: one `[[table]]` per quantification table of the file with its samples (`[[table.sample]]`, in assay order), and one `[[skipped]]` per worksheet without a quantification table, with the reason. Written for every file |
| `<name>.parquet` | The tables of the file stacked, one row per metabolite. Written for the files with at least one table |
| `mbpost_extraction_report.tsv` | One line per table or skipped sheet of all files: table id, orientation, size, unit, first sample names |

The 150 files give 150 TOML and 143 Parquet files: 215 tables (107 projects, 130,717
metabolite rows, 15,212 samples; 49 tables have the metabolites in the columns of the
source sheet) and 22 skipped worksheets. The 7 files without a table (`MPST000004`,
`14`, `92`, `109`, `148`, `191` and the annotation workbook of `213`) only have a TOML
file, which says why. A workbook with several sheets still gives one TOML and one
Parquet file, with a table per sheet.

### Sample metadata (TOML)

```toml
generator = "extract_mbpost_tables.py"
source_file = "MPST000001.xlsx"
mbpost_id = "MPST000001"
n_tables = 1                  # no [[table]] if 0

[[table]]
id = "MPST000001"             # file name, "<file>#<sheet>" for several sheets,
mbpost_id = "MPST000001"      # plus "#<quantity>" for a block of columns, e.g. "#Peak area"
source_file = "MPST000001.xlsx"
sheet = "Table 1"
features_in = "rows"          # "columns" if the sheet has the samples in rows
n_features = 254
n_samples = 15
unit = "nmol/mg-protein"      # only if the sheet states it
description = "Supplementary Table 1. ..."

[[table.sample]]
assay = 1                     # position of the sample: column abundance_assay[1]
name = "Ba/F3_1"
column = "L"                  # "row = 5" if features_in = "columns"

[table.sample.attributes]     # the header rows above the samples, with their labels
header_1 = "Ba/F3"            # (unlabelled rows are called header_<n>)
header_2 = "1"
```

Entries without attributes may be written inline (`{ assay = 1, name = "S1", column = "B" }`),
which is the same TOML.

Sample names are the sample header of the sheet: the row that names the samples, or
group and replicate joined with `_` (`Ba/F3_1`). All values are strings. Sheets that
only describe the samples (clinical data, data file names) are matched to the
samples by name and their columns are added to the attributes (`MPST000036`,
`metadata` sheet). A `metadata_sheet` or `block` key records this.

### Quantification (Parquet)

| Column | Content |
| --- | --- |
| `table_id` | The `id` of the `[[table]]` of the TOML file with the same name |
| `feature_index`, `source_position` | Row order in the table; the row of the source sheet (its column if `features_in = "columns"`) |
| `chemical_name` | Name of the metabolite, unchanged |
| `feature_id`, `chemical_formula`, `adduct_ions`, `smiles`, `inchikey` | If the sheet has them (e.g. MS-DIAL `Alignment ID`). Adducts are copied as text (`[M+H]+`): a numeric "Precursor ion" is an m/z, not an adduct |
| `theoretical_neutral_mass`, `exp_mass_to_charge`, `retention_time_min` | Exact mass, m/z and retention time, if the sheet has them |
| `abundance_assay[1]` ... `abundance_assay[N]` | Abundance in sample `assay = i` of the table, as a double; null for `N.D.`, `NA`, dashes and empty cells. `N` is the number of samples of the widest table of the file (15 for `MPST000001`, 2,584 for `MPST000136`); a narrower table has nulls beyond its samples |

This is the `abundance_assay[i]` convention of `mbpost_sml.R`, so one table is
```r
library(nanoparquet)
q <- read_parquet("mbpost_extracted/MPST000001.parquet")
m <- q[q$table_id == "MPST000001", ]     # needed if the file has several tables
x <- as.matrix(m[, paste0("abundance_assay[", 1:15, "]")])  # 15 = n_samples in MPST000001.toml
```
and `x`, `m$chemical_name`, ... go to `RmzTabM::smlCreate()`. The Parquet file records
the name of its TOML file in its metadata (`mbpost-samples-toml`).

### How the layouts are handled

The files have no common layout (MS-DIAL alignment results, workbooks with merged
group headers, several sheets, samples in rows, ...), so nothing is read from fixed
cells:

- The abundance columns are the numeric columns whose header is not an annotation
  (m/z, RT, score, ...) or a summary (`Average`, `Stdev`, `Mean`) column; the rows
  above them form the sample header and merged header cells are filled across their
  range. MS-DIAL results are recognised by their column titles.
- Tables with the samples in rows (the MRM matrices, `MPST000154`, the faecal
  metabolome tables, ...) are transposed. The metabolite axis is the one along which
  values differ most (log scale); data file names and `Sample` / `Subject` column
  titles settle the small and unclear cases. Metabolites are always the rows.
- A sheet with two quantities of the same samples side by side (peak area and a
  normalised value, `MPST000083`, `111`, `112`, `130`) gives one table per quantity,
  and a sheet with a block of columns per compound (`MPST000150`) one per quantity of
  the block.
- Text is decoded as UTF-8 or Shift-JIS (`MPST000011`), whitespace is tidied.

Skipped worksheets (listed in the TOML file) are lists of compounds or annotations
without abundances (`MPST000004`, `14`, `92`, `109`, `213`), an empty sheet
(`MPST000148`), sample index sheets (`MPST000141`), and by decision `SKIP_SHEETS` in
the script: flux estimates (`MPST000191`), calibration curves (`MPST000150`) and a
descriptor table (`MPST000015`). `COLUMN_RANGES` fixes the abundance columns of five
sheets (`MPST000130`, and the lipidomics and metabolomics sheets of `MPST000197`) that
are followed by statistics or annotation columns without a recognisable header.

### Checks and caveats

- 5,375 randomly chosen values (25 per table, all 215 tables) were compared with the raw cells at
  the recorded positions: no differences. `MPST000001` equals the SML table of the
  R pipeline above (the same 244 lipids, largest difference 1.4e-14) plus the 10
  class totals (`PC total`, ...) that the pipeline leaves out. The output is
  identical between runs and each Parquet file is read by `nanoparquet` in well under
  a second (`MPST000136`, the widest, in 0.02 s).
- The layout detection is heuristic. The shape, orientation and sample names of every
  table were reviewed in the report and each layout family was compared with its
  source sheets, but check `mbpost_extraction_report.tsv` (and the sheet) for the
  tables you convert.
- `chemical_name` is not changed. MS-DIAL names such as `Cer 30:1;2O|Cer 15:1;2`
  contain `|`, which `RmzTabM::smlCreate()` takes as a list separator and rejects
  (76 of 1,128 names in `MPST000012__Height_DDA_neg`), so replace or split it before
  the conversion. Unannotated MS-DIAL features are called `Unknown`; `feature_id`,
  `exp_mass_to_charge` and `retention_time_min` identify them.
- A table holds what the sheet holds: class totals and internal standards where
  they are listed, and sheets of one workbook that are the same data processed
  differently (`MPST000141`: Height, Normalized, blank filter, PCA matrices) are all
  kept, with the sheet in the `id`.
- `unit` is only set where the sheet states one (32 tables); peak area and relative
  area tables have none.
- The largest Parquet file is 6.5 MB and the whole directory 45 MB. It is derived data
  that takes 25 s to regenerate, so you may not want to commit it.

## Converting the extracted tables to mzTab-M

`mbpost_to_mztabm.R` turns the TOML / Parquet files of `mbpost_extracted/` into
mzTab-M 2.1 files (MTD + SML) with RmzTabM, one file per quantification table:

```sh
Rscript mbpost_to_mztabm.R                                  # all tables, about 20 s
Rscript mbpost_to_mztabm.R mbpost_extracted mztabm_extracted 'MPST0000(01|12)'   # only these files
Rscript test_mbpost_to_mztabm.R                             # tests
```

A mzTab-M file has one set of assays, one unit and one quantification method, so a file
with several tables (sheets, or peak area next to a normalised quantity) gives one
mzTab-M file per table: 215 files from the 143 files with data. The name is the table
id with `#` written `__` (`MPST000012__Height_DDA_neg.mztab`,
`MPST000034__EVs.mztab`, `MPST000150__①ASA__result__Area.mztab`). The existing
`mztabm_results/MPST000001.mztab` (with species and cell type) is not touched. `mztabm_report.tsv`
lists the table, file, unit and polarity of each file. Each file is read back with
`readMzTabM()` and its abundances are compared with the Parquet file before the
script goes on; a table that fails is reported and leaves no file.

| Part | Content |
| --- | --- |
| MTD | `mzTab-ID` = table id; `description` = project, file, sheet, quantity and the description of the TOML file; one `sample`, `assay` and `ms_run` (`location` null) per sample; the attributes of the TOML file as `sample[i]-custom[j]` (`[,,name, value]`, quoted if they have a comma, `null` if a sample lacks one) |
| study design | One study variable, `undefined`, with all assays: the files state none. The attributes are in the samples |
| unit | The `unit` of the TOML file: `nmol/mg-protein` as the NCIT term of the first conversion, other units as text (`[,, fmol/cell, ]`); without a unit "Arbitrary quantification unit" (peak areas) |
| method | The RmzTabM default, LC-MS label-free quantitation: the tables do not say how they were quantified |
| `scan_polarity` | Only where the table shows it (62 tables): from the sign of its adduct ions (both polarities if both occur) or `pos` / `neg` in its name. The other 153 have no `scan_polarity`, which RmzTabM cannot write as unknown, and mzTab-M asks for |
| SML | One row per metabolite: `chemical_name`, `chemical_formula` (`C9 H15 N4 O8 P` -> `C9H15N4O8P`, `(D7)` -> `[2H]7`), `theoretical_neutral_mass`, `adduct_ions` (`[M + H]+` -> `[M+H]1+`; text that is no adduct is `null`), abundances, and `abundance_study_variable[1]` / `abundance_variation_study_variable[1]` |
| optional SML columns | `opt_global_feature_id`, `opt_global_exp_mass_to_charge`, `opt_global_retention_time_min` and `opt_global_inchikey` where the table has them (85, 63, 93 and 44 files), as there is no SMF section |

- **Names with `|`.** MS-DIAL names such as `Cer 30:1;2O|Cer 15:1;2` are alternatives
  and stay as they are. mzTab-M lists the fields of the alternatives in step, so those
  rows get `null|null` as `database_identifier` and the formula (and the other list
  fields) once per alternative.
- **Missing values** are `null`. The mean over the assays of the study variable is `null`
  if any assay is missing; so is its variation (RmzTabM would give the variation of the
  other assays and no mean).
- **Numbers.** Abundances have 17 significant digits, so they read back as the same
  doubles. RmzTabM itself rounds to 7 digits when it converts a table it has read, so the
  files are compared as text.
- **UTF-8.** `writeMzTabM()` cuts non-ASCII text (`µM`, `O₂`, `①`) outside a UTF-8 locale,
  so the script switches to one and stops if it cannot.

Checks: an independent script (Python, plain text parsing) compared all 215 files with the
TOML and Parquet files: the samples, assays and runs, the polarity, the unit, the list
lengths of every row, the SML rows and 8.2 million abundance cells (exactly), the mean and
variation, and no `NA`, `NaN` or `Inf` anywhere: no differences. Deliberately damaged
copies (one digit, a sample name, a polarity, a `NA`, a list element, a statistic with a
missing assay) were all detected. Two runs give identical files. No mzTab-M validator was
run (there is none for 2.1 yet), so a file may still fail one that is stricter than
RmzTabM, for example on the missing `scan_polarity`.

## What is extracted

The workbook layout is located by content (the `Amount of ... (unit)`
header, the group and replicate rows below it, and the `Lipid name`,
`Formula`, `Exact Mass` and `Precursor-ion` columns), not by fixed cell
addresses.

### MTD

| Field | Value | Source |
| --- | --- | --- |
| `mzTab-ID` | `MPST000001` | file name |
| `description` | table caption | cell B2 |
| `sample[1-15]`, `assay[1-15]`, `ms_run[1-15]` | `Ba/F3_1` ... `Tm63bnull-mTMEM63B_5` | group (row 4) and replicate (row 5) of each abundance column L-Z |
| `study_variable_group[1]` | `cell_line` | |
| `study_variable[1-3]` | `Ba/F3`, `Tm63bnull`, `Tm63bnull-mTMEM63B`; mean and coefficient of variation | abundance column groups |
| `ms_run[i]-scan_polarity[1-2]` | positive, negative | precursor ions (`[M + H]+`, `[M - H]-`, ...) |
| `ms_run[i]-fragmentation_method[1]` | collision-induced dissociation | `Collision energy (V)` |
| `quantification_method` | `MS:1001838` SRM quantitation analysis | MRM |
| `small_molecule(_feature)-quantification_unit` | `NCIT:C67433` Nanomole per Milligram of Protein | `nmol/mg-protein` in the header |
| `sample[i]-species[1]`, `-cell_type[1]` | `NCBITaxon:10090` Mus musculus, `CL:0000826` pro-B cell | **not in the workbook**, see [Assumptions](#assumptions) |
| `ms_run[i]-location` | `null` | no data files are known |
| `software[1]` | RmzTabM | |

### SML

One row per lipid species (244). The 10 class totals (`PC total`, ...) and
the 11 internal standards (`IS_...`, which have no abundances) are left out.

| Column | Source |
| --- | --- |
| `chemical_name` | `Lipid name`, unchanged (e.g. `PC(16:0)(16:1)`) |
| `chemical_formula` | `Formula`, without explicit 1s (`C40H80N1O8P1` -> `C40H80NO8P`) |
| `theoretical_neutral_mass` | `Exact Mass` |
| `adduct_ions` | `Precursor-ion (Q1)` in mzTab-M notation (`[M + NH4]+` -> `[M+NH4]1+`) |
| `abundance_assay[1-15]` | abundance columns L-Z, in nmol/mg-protein |
| `abundance_study_variable[1-3]`, `abundance_variation_study_variable[1-3]` | computed by RmzTabM from the MTD study variables (mean, sd/mean) |
| other columns | `null` |

`Cholesterol` has no formula, mass or adduct in the workbook; these are `null`.

### Linking the Parquet SML to the MTD

- The column names are the mzTab-M ones: `abundance_assay[i]` holds the
  abundances of `assay[i]` and `abundance_(variation_)study_variable[j]` those
  of `study_variable[j]` in the MTD.
- Both scripts take the column-to-assay mapping from the same function
  (`mbpost_sample_data()`), and `mbpost_sml.R` stops if the assays or the
  `mzTab-ID` of the MTD file do not match the workbook.
- The Parquet key-value metadata records `mzTab-version`, `mzTab-ID`,
  `mzTab-section` (`SML`), `mzTab-MTD` (the MTD file, relative to the Parquet
  file) and the assay and study variable names in index order (`mzTab-assay`,
  `mzTab-study_variable`). `mbpost_mztab.R` checks these and the abundance
  columns against the MTD before writing.
- mzTab `null` is stored as a Parquet null; numbers are stored as doubles.

## Assumptions

The workbook does not state the following; check them before reuse.

- **Species and cell type**: Ba/F3 is a murine pro-B cell line and the other
  two lines are derived from it. Set by `.SPECIES` and `.CELL_TYPE` in
  `mbpost_mtd.R`.
- **One run per sample with both polarities** (polarity switching). Positive
  (CE, DG, TG, SM; 1.1-8.1 min) and negative ions (PA, PC, PS, PE, PI, PG;
  7.2-17.4 min) overlap in retention time, which fits one run, but separate
  runs per polarity are also possible.
- **Each replicate is a separate sample**; the workbook does not say whether
  replicates are biological or technical.

## RmzTabM 0.99.2 issues worked around

- `mtdSample()`, `mtdAssay()` and `mtdMsRun()` misorder fields when there are
  10 or more entries (`sample[10]` before `sample[2]`); `.sort_index()` in
  `mbpost_mtd.R` reorders them.
- `mtdMsRun()` only writes `scan_polarity[1]`; `.add_scan_polarity()` adds
  `scan_polarity[2]`.
- `writeMzTabM()` writes missing values as `NA` and numbers with 15
  significant digits; `mbpost_mztab.R` writes `null` and 17 significant
  digits, so every value parses back to the Parquet double with a correctly
  rounded parser. (R builds without long double, such as the one used here,
  read about 5% of these values 1 ulp off, at most 3.6e-15.)
- Not worked around: `mtdToSampleData()` fails with duplicate row names when
  all `ms_run` locations are `null`.

## Not done yet

- Lipid names are not normalized to shorthand nomenclature and have no
  database identifiers; `reliability` is `null`.
- No SMF or SME sections (retention times and MRM transitions are not
  exported).
- Title, contacts, publication, instrument and the MB-POST URI are not in the
  MTD.
- The file is not validated: there is no mzTab-M 2.1 validator yet.

## Other files

`extract_mbpost_samples.R` and `sample_metadata/` are a separate extraction
of the sample table without biological annotations (no species, cell type or
scan polarity); the pipeline above does not use them. Their Excel cell
references are one row and one column off, because readxl drops the empty
first row and column A: the abundance header is L3 and the abundance columns
are L-Z, with group labels in row 4 and replicates in row 5.
