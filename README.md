# mbpost2mztabm

Convert lipidomics results deposited in MB-POST as Excel workbooks to
[mzTab-M 2.1](https://github.com/HUPO-PSI/mzTab) with
[RmzTabM](https://github.com/RforMassSpectrometry/RmzTabM).
The first converted data set is `MPST000001`: quantitative lipidomics
(DEA-SFC/MS/MS, MRM) of three Ba/F3 cell lines with five replicates each.

## Files

| Path | Content |
| --- | --- |
| `mbpost_results/MPST000001.xlsx` | Source workbook (sheet `Table 1`) |
| `mbpost_mtd.R` | Step 1: metadata (MTD) section |
| `mbpost_sml.R` | Step 2: small molecule summary (SML) as Parquet |
| `mbpost_mztab.R` | Step 3: adds the SML to the mzTab-M file |
| `mztabm_results/MPST000001.mztab` | mzTab-M file, MTD + SML (`mzTab-profile M+S`) |
| `mztabm_results/MPST000001_sml.parquet` | SML table (244 rows x 34 columns) |
| `extract_mbpost_samples.R`, `sample_metadata/` | Separate sample table extraction, see [Other files](#other-files) |

## Requirements

R >= 4.6 with RmzTabM (tested with 0.99.2), readxl and nanoparquet (0.5.2):

```r
remotes::install_github("RforMassSpectrometry/RmzTabM")
install.packages(c("readxl", "nanoparquet"))
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
