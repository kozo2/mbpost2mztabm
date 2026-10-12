#!/usr/bin/env python3
"""Extract sample metadata and quantification tables from the MB-POST result files.

Reads every ``.xlsx`` / ``.csv`` / ``.txt`` file in ``mbpost_results/`` and writes, for each
file ``<name>.<ext>``, to ``--out-dir`` (default ``mbpost_extracted/``), the inputs for
generating mzTab-M files with RmzTabM:

* ``<name>.toml``: one ``[[table]]`` per quantification table of the file (a worksheet,
  or a block of columns of one), with its ``[[table.sample]]`` entries in assay order
  (name, source column or row, and the ``attributes`` taken from the sample header and
  from sample metadata sheets), and one ``[[skipped]]`` per worksheet that holds no
  quantification table, with the reason. Written for every file;
* ``<name>.parquet``: the tables of the file stacked, one row per metabolite, with the
  columns ``table_id``, ``feature_index``, ``source_position``, ``chemical_name``, the
  annotations the sheet has (``feature_id``, ``chemical_formula``, ``adduct_ions``,
  ``smiles``, ``inchikey``, ``theoretical_neutral_mass``, ``exp_mass_to_charge``,
  ``retention_time_min``) and ``abundance_assay[1]`` ... ``abundance_assay[N]``. Written
  only for files with at least one table.

``mbpost_extraction_report.tsv`` has one line per table or skipped sheet of all files.

Linking the files (as in the ``abundance_assay[i]`` columns of ``mbpost_sml.R``):
``table_id`` of a Parquet row is the ``id`` of a ``[[table]]`` of the TOML file of the same
name; ``abundance_assay[i]`` is the abundance in sample ``assay = i`` of that table (null
beyond its number of samples); ``source_position`` is the row of the sheet the metabolite
came from (the column if ``features_in = "columns"``) and ``column`` / ``row`` of a sample
is where it came from.

The result files have no common layout, so it is detected from the cell contents:

* the abundance block is the group of numeric columns whose header is not an annotation
  (m/z, RT, scores, ...) or a summary (Average, Stdev) column; the rows above it are the
  sample header (group labels in merged cells, replicates, ...) and the first text column
  holds the metabolite names; MS-DIAL alignment results are recognised by their columns;
* tables with the samples in rows (e.g. the MRM matrices) are transposed, so that the
  metabolites are always the rows: the metabolites are the axis along which the values
  differ most (in log scale), checked against the headers and data file names;
* a sheet that holds several quantities of the same samples (peak area and a normalised
  quantity next to each other) gives one table per quantity, and a sheet with a block of
  columns per compound gives one table per quantity of the block;
* a sheet without quantification that lists the same samples (e.g. their clinical data)
  adds its columns to the sample attributes;
* missing values (``N.D.``, ``NA``, ``null``, dashes) and empty cells become nulls.

``SKIP_SHEETS`` and ``COLUMN_RANGES`` below list the few sheets that need an explicit
decision; everything skipped is reported in the TOML files and in the report.

Usage:
    .venv/bin/python extract_mbpost_tables.py [--in-dir mbpost_results] [--out-dir mbpost_extracted]
    .venv/bin/python extract_mbpost_tables.py --include 'MPST000001*' 'MPST000012*'
"""

from __future__ import annotations

import argparse
import csv
import datetime
import fnmatch
import io
import math
import re
import sys
import warnings
import xml.etree.ElementTree as ET
import zipfile
from array import array
from collections import Counter
from dataclasses import dataclass, replace
from pathlib import Path

import openpyxl
import pyarrow as pa
import pyarrow.parquet as pq
import tomli_w

csv.field_size_limit(2**31 - 1)
warnings.filterwarnings("ignore", category=UserWarning, module="openpyxl")

NAN = math.nan
EMPTY, NUM, MISS, TEXT = 0, 1, 2, 3  # cell kinds

REPORT_TSV = "mbpost_extraction_report.tsv"

# Cell contents that mean "no value" (compared in lower case).
MISSING_TOKENS = frozenset({
    "n.d.", "nd", "n.d", "na", "n/a", "n.a.", "nan", "null", "none", "nq", "ns",
    "not detected", "<lod", "<loq",
    # a lone dash: hyphen, hyphen variants U+2010-2014, fullwidth hyphen, katakana long vowel mark.
    # (U+2212, the minus sign, is not here: some tables use it as the sign of a polarity.)
    "-", "--", "---", "\u2010", "\u2011", "\u2012", "\u2013", "\u2014", "\uff0d", "\u30fc",
})
NUMBER_RE = re.compile(r"^[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?$")
MINUS_SIGNS = "\u2212\u2012\u2013\u2014"  # a leading minus sign, as typeset in some tables

# Header of a numeric column that is an annotation of the metabolite, not an abundance.
ANNOTATION_HEADER_RE = re.compile(
    r"m/z|\bmz\b|\bm\.z\b|mass|\brt\b|\bri\b|retention|cormt|\bmt\b|migration|\bfill\b|score|"
    r"similarity|\bid\b|index|\bno\.?$|charge|polarity|\bz\b|precursor|product|collision|bias|"
    r"voltage|\(v\)|\(ev\)|quant mass|tolerance|\bstd\b|standard|delta|ppm|\bmw\b|s/n|matched|"
    r"isotop|\btag\b|dot product|percentage|ontology|formula|smiles|inchi|kegg|hmdb|\bcas\b|"
    r"\bclass\b|adduct|method|comment|\u30b3\u30e1\u30f3\u30c8|spectrum|boundary|\bci\b|lower|upper|fitted|"
    r"^#\s|\bcounts?\b|best match|confidence|\((?:max|min)\.?\)|\bm_z\b|rt_min|^tr\b|^ri[a-z]?$|"
    r"fold ?chang|p-?value|q-?value|significan|^fdr$|welch|\u691c\u5b9a|[PQ]\u5024",
    re.I,
)
# A header cell of a summary column (statistics over the samples).
SUMMARY_HEADER_RE = re.compile(r"^(average|ave\.?|mean|median|stdev|std\.?|s\.?d\.?|sd|rsd|cv|sem)$", re.I)
# MS-DIAL alignment result columns; the sample columns follow the last of them.
MSDIAL_COLUMNS = frozenset(s.lower() for s in (
    "Alignment ID", "Average Rt(min)", "Average Mz", "Average RI", "Quant mass",
    "Metabolite name", "Adduct type", "Post curation result", "Fill %", "MS/MS assigned",
    "Reference RT", "Reference m/z", "Reference RI", "Formula", "Ontology", "INCHIKEY", "SMILES",
    "Annotation tag (VS1.0)", "RT matched", "m/z matched", "MS/MS matched", "Comment",
    "Manually modified for quantification", "Manually modified for annotation",
    "Isotope tracking parent ID", "Isotope tracking weight number", "Total score",
    "RT similarity", "RI similarity", "Dot product", "Reverse dot product",
    "Weighted dot product", "Matched peaks percentage", "S/N average",
    "Spectrum reference file name", "MS1 isotopic spectrum", "MS/MS spectrum",
))
# Text of the first data row cells that shows it is a sample header row, not a metabolite.
HEADER_LABEL_RE = re.compile(
    r"^(?:(?:sample|replicate|rep|time|day|week|age|sampling|cell number|cells?|number|group|"
    r"class|condition|batch|injection|file|type|origin|mutation|treatment|ave|average|weight|"
    r"tissue|volume|collection|genotype|strain)\b|no\.?$)",
    re.I,
)
# Header of the column holding the metabolite names, most specific first.
NAME_HEADER_RES = [
    re.compile(r"^(metabolite|compound|lipid|analyte)s?\s*[_ ]?names?\b", re.I),
    re.compile(r"^(metabolite|compound|lipid|analyte)s?\b", re.I),
    re.compile(r"^(annotation|name)\b", re.I),
    re.compile(r"(metabolite|compound|lipid)", re.I),
]
# Text columns that never hold the metabolite name.
NOT_NAME_HEADER_RE = re.compile(r"adduct|positive|negative|polarity|method|\bions?\b|mode|formula|class", re.I)
# A header-row label that names a column of annotations, not the row itself.
TITLE_LABEL_RE = re.compile(
    r"m/z|\bmz\b|mass|\brt\b|\bri\b|cormt|alignment|annotation|compound|metabolite|lipid|\bname\b|kegg|hmdb|"
    r"bias|voltage|\(v\)|collision|precursor|product|method|polarity|\u30b3\u30e1\u30f3\u30c8",
    re.I,
)
# A header-row label that is the caption of the table (units, quantity).
CAPTION_LABEL_RE = re.compile(r"^(?:raw |relative )?(?:concentration|amount|peak (?:area|height)|area|height|quantity)\b", re.I)
# A header text that names the quantity of a block of sample columns ("Peak area", "Relative peak area").
QUANTITY_RE = re.compile(
    r"area|height|intensity|concentration|amount|relative|ratio|normali[sz]ed|abundance|peak|quantit", re.I)
# Names of instrument data files; a column of them labels samples.
DATA_FILE_RE = re.compile(r"\.(?:mzml|mzxml|raw|d|wiff|cdf|lcd|abf)$", re.I)
# Header that says the left-hand labels are samples (used when the data cannot decide).
SAMPLE_WORD_RE = re.compile(r"s[au]mple|subject|mice\b|cohort|patient", re.I)
SAMPLE_NAME_LABEL_RE = re.compile(r"sample ?name|^sample ?id|^s[au]mple ?id|file ?name|\bname\b|\bid\b", re.I)
# Header texts about the amount of sample (protein, weight, ...), whose unit is not the abundance unit.
SAMPLE_AMOUNT_RE = re.compile(r"protein|weight|volume|number|injection|cells?\b", re.I)
UNIT_FULL_RE = re.compile(
    r"^(?:[afpnµμum]?mol|[nµμmpf]?g|[µμmnpf]M|ppm|ppb)(?:\s*/\s*[\w\-µμ.]+|\s+per\s+[\w\-µμ. ]+)?$"
)
# Annotation columns copied to the Parquet file: output column -> (header pattern, kind).
# Kinds: "id" (text or number, kept as text), "str" (text only: a numeric "Precursor ion" is an
# m/z, not an adduct), "num".
FEATURE_FIELDS = {
    "feature_id": (re.compile(r"^(alignment id|id|index|no\.?)$", re.I), "id"),
    "chemical_formula": (re.compile(r"^(molecular ?)?formula$", re.I), "str"),
    "theoretical_neutral_mass": (re.compile(r"^exact ?mass$", re.I), "num"),
    "exp_mass_to_charge": (re.compile(r"^(average mz|ave\.? m/z|m/z|mz|m_z)$", re.I), "num"),
    "adduct_ions": (re.compile(r"^(adduct( type| ions?)?|precursor[- ]?ion( \(q1\))?)$", re.I), "str"),
    "retention_time_min": (re.compile(r"^(average rt\(min\)|rt\*? ?\(min\)|rt_min_|rt \[min\])$", re.I), "num"),
    "smiles": (re.compile(r"^(isomeric )?smiles$", re.I), "str"),
    "inchikey": (re.compile(r"^inchi ?key$", re.I), "str"),
}
FEATURE_STR_FIELDS = [k for k, (_, kind) in FEATURE_FIELDS.items() if kind in ("id", "str")]
FEATURE_NUM_FIELDS = [k for k, (_, kind) in FEATURE_FIELDS.items() if kind == "num"]

# Overrides for worksheets the layout detection gets wrong. Both are reported in the output.
#
# Sheets whose abundance columns cannot be told from the numeric annotation columns next to them
# (logP, pKa, ... columns without a recognisable header): (file name, sheet) -> (first, last) column.
COLUMN_RANGES: dict[tuple[str, str], tuple[str, str]] = {
    ("MPST000130.xlsx", "Relative peak area"): ("H", "AN"),
    # samples, blank and QC; the columns after them are statistics (fold change, p- and q-values)
    ("MPST000197__Supplementary Table_Lipidomics.xlsx", "Molecules_Negative-ion mode"): ("I", "AB"),
    ("MPST000197__Supplementary Table_Lipidomics.xlsx", "Molecules_Positive ion mode"): ("I", "AB"),
    ("MPST000197__Supplementary Table_Metabolomics.xlsx", "GC-MS"): ("F", "X"),
    ("MPST000197__Supplementary Table_Metabolomics.xlsx", "IC-MS"): ("F", "X"),
}
# Worksheets that are not sample-by-metabolite quantification tables although they contain
# numbers: (file name, sheet name or None for all sheets) -> reason.
SKIP_SHEETS: dict[tuple[str, str | None], str] = {
    ("MPST000015.xlsx", "Identification and annotation"):
        "compound identification table with in silico descriptors, not sample abundances",
    ("MPST000191.xlsx", None): "metabolic flux estimates per reaction, not a sample quantification table",
    ("MPST000150__\u2460ASA.xlsx", "calibration curve"): "calibration curves of standards, not samples",
    ("MPST000150__\u2461ASA+inhibitor(L-MS).xlsx", "calibration curve"): "calibration curves of standards, not samples",
    ("MPST000150__\u2462ASA+inhibitor(V9302).xlsx", "calibration curve"): "calibration curves of standards, not samples",
}


# --------------------------------------------------------------------------- cells


def clean(v):
    """Tidy text cells (one space between words, no line breaks); empty text becomes None."""
    if isinstance(v, str):
        return " ".join(v.split()) or None  # also folds line breaks and no-break spaces
    return v


def parse_number(s: str) -> float | None:
    if s and s[0] in MINUS_SIGNS:
        s = "-" + s[1:]
    return float(s) if NUMBER_RE.match(s) else None


def classify(v) -> tuple[int, float]:
    if v is None:
        return EMPTY, NAN
    t = type(v)
    if t is float or t is int:
        return (MISS, NAN) if v != v else (NUM, float(v))
    if t is str:
        if v.lower() in MISSING_TOKENS:
            return MISS, NAN
        x = parse_number(v)
        return (NUM, x) if x is not None else (TEXT, NAN)
    return TEXT, NAN  # dates, booleans


def text_of(v) -> str | None:
    """Cell content as it is shown in a header (1.0 -> '1', dates as ISO dates)."""
    if v is None:
        return None
    if isinstance(v, float):
        return str(int(v)) if v == int(v) and abs(v) < 1e15 else repr(v)
    if isinstance(v, datetime.datetime):
        return v.date().isoformat() if v.time() == datetime.time(0) else v.isoformat(sep=" ")
    return str(v)


def col_letter(i: int) -> str:
    """0-based column index -> Excel column letters."""
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def col_index(letters: str) -> int:
    n = 0
    for ch in letters:
        n = n * 26 + ord(ch) - 64
    return n - 1


class Frame:
    """A rectangular sheet: cleaned values plus the kind and numeric value of each cell."""

    def __init__(self, rows):
        rows = [[clean(v) for v in r] for r in rows]
        self.ncols = max((len(r) for r in rows), default=0)
        self.grid = [r + [None] * (self.ncols - len(r)) for r in rows]
        self.nrows = len(self.grid)
        self.kind: list[bytearray] = []
        self.num: list[array] = []
        for row in self.grid:
            kinds = bytearray(self.ncols)
            nums = array("d", [NAN]) * self.ncols
            for j, v in enumerate(row):
                if v is not None:
                    kinds[j], nums[j] = classify(v)
            self.kind.append(kinds)
            self.num.append(nums)

    def transposed(self) -> "Frame":
        return Frame([list(c) for c in zip(*self.grid)])


# --------------------------------------------------------------------------- readers


def decode_text(raw: bytes) -> str:
    for enc in ("utf-8-sig", "cp932"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1")


def read_delimited(path: Path) -> list[list]:
    text = decode_text(path.read_bytes())
    delimiter = "\t" if path.suffix.lower() == ".txt" else ","
    return list(csv.reader(io.StringIO(text, newline=""), delimiter=delimiter))


def merged_ranges(path: Path) -> dict[str, list[tuple[int, int, int, int]]]:
    """Single-row merged ranges (r, c0, c1) of each sheet, 0-based.

    openpyxl does not report merged cells in read-only mode, so they are read from the
    sheet XML (the ``mergeCells`` element is near the end of the part).
    """
    out: dict[str, list] = {}
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
          "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
    with zipfile.ZipFile(path) as zf:
        wb = ET.fromstring(zf.read("xl/workbook.xml"))
        rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
        target = {r.get("Id"): r.get("Target") for r in rels}
        for sheet in wb.find("m:sheets", ns):
            rid = sheet.get("{%s}id" % ns["r"])
            part = target.get(rid, "")
            part = part.lstrip("/") if part.startswith("/") else "xl/" + part
            if part not in zf.namelist():
                continue
            tail = b""
            with zf.open(part) as fh:
                while True:
                    chunk = fh.read(1 << 22)
                    if not chunk:
                        break
                    tail = (tail + chunk)[-(4 << 20):]
            found = []
            for c0, r0, c1, r1 in re.findall(rb'<mergeCell ref="([A-Z]+)(\d+):([A-Z]+)(\d+)"', tail):
                if r0 == r1:
                    found.append((int(r0) - 1, col_index(c0.decode()), col_index(c1.decode())))
            out[sheet.get("name")] = found
    return out


def read_xlsx(path: Path) -> list[tuple[str, list[list]]]:
    try:
        merges = merged_ranges(path)
    except (KeyError, ET.ParseError, TypeError, zipfile.BadZipFile):
        merges = {}  # unusual workbook structure: read the cells without the merged-cell labels
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    sheets = []
    for ws in wb.worksheets:
        grid: list = []
        for row in ws.iter_rows(values_only=True):
            if all(v is None or v == "" for v in row):
                grid.append(None)
            else:
                grid.append(list(row))
        while grid and grid[-1] is None:
            grid.pop()
        grid = [r if r is not None else [] for r in grid]
        for r, c0, c1 in merges.get(ws.title, []):
            if r < len(grid) and c0 < len(grid[r]) and grid[r][c0] not in (None, ""):
                row = grid[r]
                row.extend([None] * (c1 + 1 - len(row)))
                for c in range(c0 + 1, c1 + 1):
                    if row[c] in (None, ""):
                        row[c] = row[c0]
        sheets.append((ws.title, grid))
    wb.close()
    return sheets


# --------------------------------------------------------------------------- layout


@dataclass
class Layout:
    first: int  # first data row
    rows: list[int]  # data rows
    cols: list[int]  # abundance columns
    name_col: int
    header_rows: list[int]  # rows above the data with content in the abundance columns
    hdr: list  # per column: nearest non-empty header text above the data
    msdial: bool = False  # an MS-DIAL alignment result: metabolites are always the rows
    prefix_col: int | None = None  # a column of group labels written once per group, left of the names


def find_layout(f: Frame, col_range: tuple[int, int] | None = None) -> Layout | str:
    """Locate the abundance block of a sheet; returns the reason if there is none."""
    nr, nc = f.nrows, f.ncols
    if nr == 0 or nc == 0:
        return "empty sheet"
    nnum = [f.kind[r].count(NUM) for r in range(nr)]
    counts = sorted(n for n in nnum if n)
    if not counts:
        return "no numeric cells"
    ref = counts[(len(counts) - 1) * 9 // 10]
    thr = max(1, (3 * ref + 9) // 10)
    prov = [r for r in range(nr) if nnum[r] >= thr]

    textcol: list[int] = []
    numcol: list[int] = []
    covered: set[int] = set()  # text columns with text in at least half of the data rows
    for c in range(nc):
        k = bytes(f.kind[r][c] for r in prov)
        n_num, n_miss, n_text = k.count(NUM), k.count(MISS), k.count(TEXT)
        if n_text > n_num + n_miss:
            textcol.append(c)
            if n_text * 2 >= len(prov):
                covered.add(c)
        elif n_num + n_miss > 0 and (n_num + n_miss) * 5 >= len(prov):
            numcol.append(c)

    def bottom_headers(first: int) -> tuple[list, list, set]:
        """Nearest header text above the data of each column.

        Returns that text, the nearest one that is not repeated across the row (merged
        titles and category rows are, column titles are not), and the summary columns.
        """
        hdr = [None] * nc
        title = [None] * nc
        summary = set()
        for r in range(max(first - 13, 0), first):
            repeated = {v for v, n in Counter(x for x in f.grid[r] if x is not None).items() if n >= 3}
            for c in range(nc):
                v = f.grid[r][c]
                if v is None:
                    continue
                hdr[c] = text_of(v)  # later rows overwrite: ends as the nearest
                if v not in repeated:
                    title[c] = text_of(v)
                if isinstance(v, str) and SUMMARY_HEADER_RE.match(v):
                    summary.add(c)
        return hdr, [t or h for t, h in zip(title, hdr)], summary

    def abundance(first: int):
        hdr, title, summary = bottom_headers(first)
        cols = [c for c in numcol
                if c not in summary and not (title[c] and ANNOTATION_HEADER_RE.search(title[c]))
                and (col_range is None or col_range[0] <= c <= col_range[1])]
        fixed = [c for c in range(nc) if hdr[c] and hdr[c].lower() in MSDIAL_COLUMNS]
        msdial = len(fixed) >= 5
        if msdial:
            cols = [c for c in cols if c > max(fixed)]
            meta = [c for c in cols if any(f.grid[r][c] is not None for r in range(max(first - 6, 0), first - 1))]
            if len(meta) * 2 >= len(cols):  # columns without them are other data pasted next to the table
                cols = meta
        return cols, hdr, msdial

    def header_ish(r: int, cols: list[int]) -> bool:
        """A row of numbers that labels the samples (replicate, cell number, ...) rather than a metabolite."""
        span = set(cols)
        label = next((f.grid[r][c] for c in range(nc) if c not in span and f.grid[r][c] is not None), None)
        if label is None or (isinstance(label, str) and HEADER_LABEL_RE.search(label)):
            return True
        # a title row with numbers as sample titles: it also holds column titles (index, m/z, rt, ...)
        words = [v for c, v in enumerate(f.grid[r]) if f.kind[r][c] == TEXT and isinstance(v, str) and len(v) <= 20]
        if sum(1 for v in words if ANNOTATION_HEADER_RE.search(v)) >= 2:
            return True
        # sample numbers 1, 2, 3 or 1, 1, 2, 2, 5; the cells left of them are titles, not numbers
        v = [f.num[r][c] for c in cols if f.kind[r][c] == NUM]
        titles_only = all(f.kind[r][c] != NUM for c in range(min(cols)))
        return (titles_only and len(v) >= 5 and all(x == int(x) for x in v)
                and all(b >= a for a, b in zip(v, v[1:])) and len(set(v)) >= 4)

    first = prov[0]
    cols, hdr, msdial = abundance(first)
    if not cols:
        return "no abundance columns (only annotation columns)"
    # Data rows with few numbers (e.g. a metabolite that is N.D. in most samples) may precede the dense rows.
    while first > 0 and sum(1 for c in cols if f.kind[first - 1][c] in (NUM, MISS)) * 2 >= len(cols):
        first -= 1
    cols, hdr, msdial = abundance(first)
    if not cols:
        return "no abundance columns (only annotation columns)"
    # Skip header rows that are made of text in the abundance columns (sample names, groups).
    start = first
    for r in range(min(nr, first + 12)):
        if sum(1 for c in cols if f.kind[r][c] == TEXT) * 2 >= len(cols):
            start = max(start, r + 1)
    first = start
    while True:
        cols, hdr, msdial = abundance(first)
        if not cols:
            return "no abundance columns (only annotation columns)"
        if first >= nr:
            return "no data rows below the header"
        if not header_ish(first, cols):
            break
        first += 1

    other_text = [c for c in textcol if c not in set(cols)]
    text_candidates = [c for c in other_text if not (hdr[c] and NOT_NAME_HEADER_RE.search(hdr[c]))]
    text_candidates = [c for c in text_candidates if c < min(cols)] or text_candidates
    name_col = None
    for pattern in NAME_HEADER_RES:
        for c in text_candidates:
            if hdr[c] and pattern.search(hdr[c]):
                name_col = c
                break
        if name_col is not None:
            break
    prefix_col = None
    if name_col is None:  # no header says it: the first column of text, or the one with the most names
        name_col = next((c for c in text_candidates if c in covered), None)
        if name_col is not None and name_col - 1 in textcol and name_col - 1 not in covered:
            prefix_col = name_col - 1  # e.g. a lipid written once above its isotopologues m0, m1, ...
    if name_col is None and any(c in covered for c in other_text):  # e.g. only "Polarity" and "Class"
        name_col = max((c for c in other_text if c in covered),
                       key=lambda c: len({f.grid[r][c] for r in range(first, nr)}))
    if name_col is not None:
        # numeric columns left of the names are IDs, not abundances
        cols = [c for c in cols if c > name_col] or cols
    else:  # e.g. a matrix of m/z rows: use the first numeric annotation column
        others = [c for c in numcol if c not in set(cols)]
        if others:
            name_col = others[0]
    if name_col is None:
        return "no column with metabolite names"
    cols = [c for c in cols if hdr[c]]  # an abundance column has a sample header
    if not cols:
        return "no sample header above the abundance columns"

    rows = [r for r in range(first, nr)
            if any(f.kind[r][c] == NUM for c in cols)
            or (f.kind[r][name_col] != EMPTY and any(f.kind[r][c] == MISS for c in cols))]
    if msdial:  # MS-DIAL names every feature ("Unknown" at least); other rows are calculations
        rows = [r for r in rows if f.kind[r][name_col] != EMPTY]
    if not rows:
        return "no data rows below the header"
    header_rows = [r for r in range(first) if any(f.grid[r][c] is not None for c in cols)]
    return Layout(first, rows, cols, name_col, header_rows, hdr, msdial, prefix_col)


def spread(vectors) -> float | None:
    """Mean standard deviation of the vectors with at least 3 valid values."""
    total, n = 0.0, 0
    for v in vectors:
        v = [x for x in v if x == x]
        if len(v) < 3:
            continue
        m = sum(v) / len(v)
        total += math.sqrt(sum((x - m) ** 2 for x in v) / len(v))
        n += 1
    return total / n if n else None


def features_in_columns(f: Frame, lay: Layout) -> tuple[bool, str]:
    """Decide whether the metabolites are the columns (samples in rows) of the abundance block.

    Within a metabolite the values vary less across samples than within a sample across
    metabolites, so the axis with the smaller spread (in log scale) is the sample axis.
    Falls back to the column headers when the block is too small to tell.
    """
    if lay.msdial:
        return False, "MS-DIAL alignment result"
    labels = [f.grid[r][lay.name_col] for r in lay.rows]
    if sum(1 for v in labels if isinstance(v, str) and DATA_FILE_RE.search(v)) * 5 >= len(labels) * 4:
        return True, "data file names as row labels"
    step_r = max(1, len(lay.rows) // 300)
    step_c = max(1, len(lay.cols) // 300)
    rows = lay.rows[::step_r]
    cols = lay.cols[::step_c]
    block = [[f.num[r][c] for c in cols] for r in rows]
    flat = [x for row in block for x in row if x == x]
    if flat and sum(1 for x in flat if x < 0) > 0.02 * len(flat):
        def tf(x):
            return x
    else:
        def tf(x):
            return math.log10(x) if x > 0 else NAN
    block = [[tf(x) if x == x else NAN for x in row] for row in block]
    by_row = spread(block)  # variation across the columns of a row
    by_col = spread(zip(*block))  # variation across the rows of a column
    sample_title = any(SAMPLE_WORD_RE.search(t) for t in
                       [lay.hdr[c] for c in range(f.ncols) if c not in set(lay.cols) and lay.hdr[c]])
    if by_row is not None and by_col:
        ratio = by_row / by_col
        basis = f"spread ratio {ratio:.2f}"
        # With few rows (metabolites) the spread across samples is noisy: ask for more evidence.
        if ratio > (0.8 if sample_title else 1.25 if len(lay.rows) >= 12 else 3.0):
            return True, basis + (", sample column title" if sample_title else "")
        if ratio < 0.8 or not sample_title:
            return False, basis
    elif sample_title:
        return True, "sample column title"
    return False, "default"


# --------------------------------------------------------------------------- tables


@dataclass
class Sample:
    name: str
    source: str  # column letters, or the row number when the sheet is transposed
    attributes: dict[str, str]


@dataclass
class Table:
    table_id: str
    mbpost_id: str
    source_file: str
    sheet: str
    transposed: bool
    basis: str
    description: str | None
    unit: str | None
    samples: list[Sample]
    features: list[dict]
    matrix: list[array]
    metadata_sheet: str | None = None  # sheet whose columns were added to the sample attributes
    block: str | None = None  # title of the block of columns when a sheet holds several quantities


def dedupe(names: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    out = []
    totals = {n: names.count(n) for n in set(names)}
    for n in names:
        if totals[n] > 1:
            seen[n] = seen.get(n, 0) + 1
            out.append(f"{n}_{seen[n]}")
        else:
            out.append(n)
    return out


def is_bare_unit(text: str) -> bool:
    """A text that is only a unit: nmol/L, (nmol/L), [fmol / cell]."""
    inner = re.sub(r"\s*/\s*", "/", text.strip().strip("()[]").strip())
    return bool(UNIT_FULL_RE.match(inner))


def find_unit(texts: list[str]) -> str | None:
    for s in texts:
        s = re.sub(r"\s+", " ", s).strip()
        if UNIT_FULL_RE.match(s):
            return s.replace(" / ", "/").replace(" ", "") if "/" in s else s
        if SAMPLE_AMOUNT_RE.search(re.sub(r"[(\[].*?[)\]]", "", s)):
            continue
        for inner in re.findall(r"[(\[]\s*([^()\[\]]+?)\s*[)\]]", s):
            inner = inner.replace(" / ", "/").replace(" /", "/").replace("/ ", "/")
            if UNIT_FULL_RE.match(inner):
                return inner
    return None


def column_values(f: Frame, lay: Layout, pattern: re.Pattern, kind: str) -> list | None:
    for c in range(f.ncols):
        if c in lay.cols or not lay.hdr[c] or not pattern.match(lay.hdr[c].strip()):
            continue
        out = []
        for r in lay.rows:
            if kind == "num":
                x = f.num[r][c]
                if x != x and f.kind[r][c] == TEXT:  # "2.83±0.02"
                    m = re.match(r"^\s*([+-]?\d+\.?\d*)", f.grid[r][c])
                    x = float(m.group(1)) if m else NAN
                out.append(x if x == x else None)
            else:
                v = f.grid[r][c]
                out.append(text_of(v) if f.kind[r][c] == TEXT or (kind == "id" and f.kind[r][c] == NUM) else None)
        if any(v is not None for v in out):
            return out
    return None


@dataclass
class HeaderRow:
    label: str | None
    values: list  # text of each abundance column, None where empty
    kind: str  # "text", "int" or "float": what the values are


def unique_names(names: list) -> bool:
    return all(names) and len(set(names)) == len(names)


def join_rows(rows: list[HeaderRow]) -> list[str]:
    return ["_".join(v for v in vals if v) for vals in zip(*[r.values for r in rows])]


def choose_name_rows(rows: list[HeaderRow]) -> list[HeaderRow]:
    """The header rows that make up the sample names (empty if there is none)."""
    named = [r for r in rows if r.kind != "float"]  # rows of weights, volumes, ... do not name samples
    for r in reversed(named):
        if r.label and SAMPLE_NAME_LABEL_RE.search(r.label) and unique_names(r.values):
            return [r]
    for kind in ("text", "int"):
        for r in reversed(named):
            if r.kind == kind and unique_names(r.values):
                return [r]
    for k in range(2, len(named) + 1):  # e.g. group + replicate
        if unique_names(join_rows(named[-k:])):
            return named[-k:]
    return named


def build_samples(f: Frame, lay: Layout, transposed: bool) -> tuple[list[Sample], list[str]]:
    """Sample names and header attributes; also the table-level header texts (caption, unit)."""
    cols = lay.cols
    first_col = min(cols)
    rows: list[HeaderRow] = []  # the header rows that differ between samples
    table_texts: list[str] = []
    carried = None  # text alone in the first abundance column labels the row below it
    for r in lay.header_rows:
        values = [text_of(f.grid[r][c]) for c in cols]
        kinds = [f.kind[r][c] for c in cols if f.kind[r][c] != EMPTY]
        label = None
        for c in range(first_col - 1, -1, -1):
            if f.grid[r][c] is not None:
                label = text_of(f.grid[r][c])
                break
        label = label or carried
        carried = None
        distinct = {v for v in values if v}
        if len(distinct) == 1 and sum(1 for v in values if v) == 1 and f.kind[r][cols[0]] == TEXT:
            carried = values[0]
        # text left of the abundance columns that describes the quantity: "Concentration in ... (uM)"
        table_texts.extend(v for v in f.grid[r][:first_col]
                           if isinstance(v, str) and (QUANTITY_RE.search(v) or "mol" in v.lower() or is_bare_unit(v)))
        if len(distinct) < 2:
            table_texts.extend(distinct)
            continue
        if TEXT in kinds:
            kind = "text"
        elif all(f.num[r][c] == int(f.num[r][c]) for c in cols if f.kind[r][c] == NUM):
            kind = "int"
        else:
            kind = "float"
        if label and (TITLE_LABEL_RE.search(label) or CAPTION_LABEL_RE.search(label)):
            label = None  # a column title or the caption of the table, not the name of this row
        if kind == "text" and all(is_bare_unit(v) for v in distinct):
            label = "unit"
        rows.append(HeaderRow(label, values, kind))

    chosen = choose_name_rows(rows)
    if chosen:
        names = [n or f"sample_{i + 1}" for i, n in enumerate(join_rows(chosen))]
    else:
        names = [lay.hdr[c] or f"sample_{i + 1}" for i, c in enumerate(cols)]
    names = dedupe(names)

    attrs: list[dict[str, str]] = [{} for _ in cols]
    keys_used: set[str] = set()
    for i, row in enumerate(rows, 1):
        if len(chosen) == 1 and row is chosen[0]:
            continue  # the sample name itself
        key = row.label or f"header_{i}"
        while key in keys_used:
            key += "_2"
        keys_used.add(key)
        for a, v in zip(attrs, row.values):
            if v:
                a[key] = v
    samples = [Sample(n, str(c + 1) if transposed else col_letter(c), a)
               for n, c, a in zip(names, cols, attrs)]
    return samples, table_texts


def build_table(f: Frame, lay: Layout, ident: dict, transposed: bool, basis: str) -> Table:
    samples, texts = build_samples(f, lay, transposed)
    caption = None  # a title line above the table: a row with a single cell
    for r in range(lay.first):
        cells = [v for v in f.grid[r] if v is not None]
        if len(cells) == 1 and isinstance(cells[0], str) and len(cells[0]) >= 12 and " " in cells[0]:
            caption = cells[0]
            break
    above = [v for r in range(lay.first) if r not in lay.header_rows for v in f.grid[r]
             if isinstance(v, str) and (QUANTITY_RE.search(v) or "mol" in v.lower() or is_bare_unit(v))]
    unit = find_unit(([caption] if caption else []) + texts + above)

    fields: dict[str, list | None] = {}
    for key, (pattern, kind) in FEATURE_FIELDS.items():
        fields[key] = column_values(f, lay, pattern, kind)
    names = {r: text_of(f.grid[r][lay.name_col]) for r in lay.rows}
    if lay.prefix_col is not None:  # the group label is written once: it goes with the rows below it
        group = None
        for r in range(lay.first, f.nrows):
            if f.grid[r][lay.prefix_col] is not None:
                group = text_of(f.grid[r][lay.prefix_col])
            if r in names:
                names[r] = " ".join(x for x in (group, names[r]) if x) or None
    features = []
    for i, r in enumerate(lay.rows):
        row: dict = {"feature_index": i + 1,
                     "source_position": r + 1,  # row, or column if transposed
                     "chemical_name": names[r]}
        for key, values in fields.items():
            if values is not None:
                row[key] = values[i]
        features.append(row)
    matrix = [array("d", (f.num[r][c] for c in lay.cols)) for r in lay.rows]
    return Table(ident["table_id"], ident["mbpost_id"], ident["source_file"], ident["sheet"],
                 transposed, basis, caption, unit, samples, features, matrix)


def attach_sample_metadata(table: Table, sheet: str, grid: list[list]) -> bool:
    """Add the columns of a sample metadata sheet to the attributes of the samples of a table.

    The sheet has a header row; its column that holds the sample names of the table (at least
    half of them, e.g. the data file names) selects the row of each sample.
    """
    rows = [[clean(v) for v in r] for r in grid]
    rows = [r for r in rows if any(v is not None for v in r)]
    if len(rows) < 3:
        return False
    header = rows[0]
    if sum(v is not None for v in header) < 2 or any(v is not None and not isinstance(v, str) for v in header):
        return False
    names = {s.name for s in table.samples}
    best, best_hits = None, 0
    for j, h in enumerate(header):
        if h is None:
            continue
        hits = sum(1 for r in rows[1:] if j < len(r) and text_of(r[j]) in names)
        if hits > best_hits:
            best, best_hits = j, hits
    if best is None or best_hits * 2 < len(names):
        return False
    by_name = {text_of(r[best]): r for r in rows[1:] if best < len(r) and r[best] is not None}
    for sample in table.samples:
        row = by_name.get(sample.name)
        if row is None:
            continue
        for j, h in enumerate(header):
            if j == best or h is None or j >= len(row):
                continue
            v = text_of(row[j])
            if v is None or v.lower() in MISSING_TOKENS:
                continue
            key = h
            while key in sample.attributes:
                key += "_2"
            sample.attributes[key] = v
    table.metadata_sheet = sheet
    return True


def split_blocks(f: Frame, lay: Layout) -> list[tuple[str | None, list[int]]]:
    """Blocks of abundance columns that hold different quantities of the same samples.

    A header row names them when it has at least two different titles, each naming a
    quantity ("Peak area", "Relative peak area"); a title extends to the next one.
    """
    for r in reversed(lay.header_rows):
        titles: list[str | None] = []
        current = None
        for c in lay.cols:
            v = f.grid[r][c]
            if isinstance(v, str) and f.kind[r][c] == TEXT:
                current = v
            titles.append(current)
        distinct = {t for t in titles if t}
        if len(distinct) >= 2 and all(QUANTITY_RE.search(t) for t in distinct):
            blocks: dict[str, list[int]] = {}
            for t, c in zip(titles, lay.cols):
                if t:
                    blocks.setdefault(t, []).append(c)
            if all(len(c) >= 3 for c in blocks.values()):  # one title per column names the metabolites instead
                return list(blocks.items())
    return [(None, lay.cols)]


def repeated_titles(titles: list[str]) -> tuple[int, int, int] | None:
    """(start, period, repeats) if the list ends with a set of distinct quantity titles repeated.

    E.g. ... Area, Concentration (pmol), Average, S.D., Area, Concentration (pmol), Average, S.D., ...
    """
    for start in range(len(titles)):
        for period in range(2, 9):
            pattern = titles[start:start + period]
            repeats = (len(titles) - start) // period
            if (len(set(pattern)) == period and repeats >= 3 and titles[start:] == pattern * repeats
                    and any(QUANTITY_RE.search(t) for t in pattern)):
                return start, period, repeats
    return None


def compound_blocks(f: Frame, ident: dict) -> list[Table] | None:
    """Tables of a sheet with one block of columns per compound and the samples in rows.

    The block is a repeated set of column titles, e.g. Area, Concentration (pmol), Average, S.D.;
    the compound name is above the first column of its block and the sample labels (cell,
    condition, ...) are written once per group of replicate rows. Each quantity of the block
    (Area, Concentration) becomes a table whose features are the compounds.
    """
    for r in range(min(f.nrows, 12)):
        cells = [(c, text_of(f.grid[r][c])) for c in range(f.ncols) if f.kind[r][c] == TEXT]
        found = repeated_titles([t for _, t in cells])
        if found:
            start, period, repeats = found
            break
    else:
        return None
    pattern = [t for _, t in cells[start:start + period]]
    blocks = [[cells[start + k * period + j][0] for j in range(period)] for k in range(repeats)]
    quantities = [(j, t) for j, t in enumerate(pattern) if not SUMMARY_HEADER_RE.match(t)]
    label_cols = [c for c in range(blocks[0][0]) if any(f.grid[i][c] is not None for i in range(r + 1, f.nrows))]
    rows = [i for i in range(r + 1, f.nrows)
            if any(f.kind[i][b[j]] == NUM for b in blocks for j, _ in quantities)]
    if not rows or not label_cols:
        return None
    compounds = []
    for b in blocks:
        name = next((text_of(f.grid[i][c]) for i in range(r - 1, -1, -1) for c in range(b[0], b[-1] + 1)
                     if f.kind[i][c] == TEXT), None)
        compounds.append(name)
    labels, current = [], [None] * len(label_cols)  # labels are written once per group of rows
    for i in rows:
        for k, c in enumerate(label_cols):
            if f.grid[i][c] is not None:
                current[k:] = [text_of(f.grid[i][c])] + [None] * (len(label_cols) - k - 1)
        labels.append(list(current))
    names = dedupe(["_".join(v for v in lab if v) or f"sample_{n + 1}" for n, lab in enumerate(labels)])
    keys = [text_of(f.grid[r][c]) or f"header_{k + 1}" for k, c in enumerate(label_cols)]
    tables = []
    for j, quantity in quantities:
        samples = [Sample(n, str(i + 1), {k: v for k, v in zip(keys, lab) if v})
                   for n, i, lab in zip(names, rows, labels)]
        features, matrix = [], []
        for b, compound in zip(blocks, compounds):
            if compound is None:
                continue
            features.append({"feature_index": len(features) + 1, "source_position": b[j] + 1,
                             "chemical_name": compound})
            matrix.append(array("d", (f.num[i][b[j]] for i in rows)))
        tables.append(Table(f"{ident['table_id']}#{quantity}", ident["mbpost_id"], ident["source_file"],
                            ident["sheet"], True, "compound blocks", None, find_unit([quantity]),
                            samples, features, matrix, block=quantity))
    return tables


def extract_sheet(name: str, grid: list[list], ident: dict) -> list[Table] | str:
    f = Frame(grid)
    tables = compound_blocks(f, ident)
    if tables:
        return tables
    letters = COLUMN_RANGES.get((ident["source_file"], name))
    lay = find_layout(f, (col_index(letters[0]), col_index(letters[1])) if letters else None)
    if isinstance(lay, str):
        return lay
    blocks = split_blocks(f, lay)
    transposed, basis = features_in_columns(f, replace(lay, cols=blocks[0][1]))
    if transposed:
        f = f.transposed()
        lay = find_layout(f)
        if isinstance(lay, str):
            return f"transposed sheet: {lay}"
        return [build_table(f, lay, ident, True, basis)]
    tables = []
    for title, cols in blocks:
        sub = replace(lay, cols=cols, rows=[
            r for r in lay.rows
            if any(f.kind[r][c] == NUM for c in cols) or any(f.kind[r][c] == MISS for c in cols)])
        if not sub.rows:
            continue
        block_ident = ident if title is None else {**ident, "table_id": f"{ident['table_id']}#{title}"}
        table = build_table(f, sub, block_ident, False, basis)
        table.block = title
        tables.append(table)
    return tables or "no data rows in any block"


# --------------------------------------------------------------------------- files


def input_files(in_dir: Path, patterns: list[str] | None) -> list[Path]:
    files = [p for p in sorted(in_dir.iterdir())
             if p.suffix.lower() in (".xlsx", ".csv", ".txt") and not p.name.startswith("manifest.")]
    if patterns:
        files = [p for p in files if any(fnmatch.fnmatch(p.name, pat) for pat in patterns)]
    return files


def mbpost_id_of(path: Path) -> str:
    m = re.match(r"(MPST\d+)", path.name)
    return m.group(1) if m else path.stem


def extract_file(path: Path) -> tuple[list[Table], list[dict]]:
    """All quantification tables of a file and the sheets that were skipped."""
    mbpost_id = mbpost_id_of(path)
    suffix = path.suffix.lower()
    tables: list[Table] = []
    skipped: list[dict] = []
    unused: dict[str, list[list]] = {}
    try:
        sheets = read_xlsx(path) if suffix == ".xlsx" else [("", read_delimited(path))]
    except Exception as exc:  # noqa: BLE001 - report the file and go on
        return [], [{"sheet": "", "reason": f"unreadable file: {type(exc).__name__}: {exc}"}]
    for name, grid in sheets:
        key = (path.name, name)
        reason = SKIP_SHEETS.get(key) or SKIP_SHEETS.get((path.name, None))
        result: list[Table] | str
        if reason:
            result = reason
        else:
            table_id = path.stem if len(sheets) == 1 else f"{path.stem}#{name}"
            ident = {"table_id": table_id, "mbpost_id": mbpost_id,
                     "source_file": path.name, "sheet": name}
            try:
                result = extract_sheet(name, grid, ident)
            except Exception as exc:  # noqa: BLE001 - report the sheet and go on
                result = f"error: {type(exc).__name__}: {exc}"
        if isinstance(result, str):
            skipped.append({"sheet": name, "reason": result})
            unused[name] = grid
        else:
            tables.extend(result)
    for entry in list(skipped):
        grid = unused[entry["sheet"]]
        linked = [t for t in tables if attach_sample_metadata(t, entry["sheet"], grid)]
        if linked:
            skipped.remove(entry)
    return tables, skipped


# --------------------------------------------------------------------------- output


def toml_document(path: Path, tables: list[Table], skipped: list[dict]) -> dict:
    """The sample metadata of one result file."""
    doc: dict = {"generator": Path(__file__).name, "source_file": path.name,
                 "mbpost_id": mbpost_id_of(path), "n_tables": len(tables)}
    out = []
    for t in tables:
        entry = {
            "id": t.table_id,
            "mbpost_id": t.mbpost_id,
            "source_file": t.source_file,
        }
        if t.sheet:
            entry["sheet"] = t.sheet
        entry["features_in"] = "columns" if t.transposed else "rows"
        entry["n_features"] = len(t.features)
        entry["n_samples"] = len(t.samples)
        if t.unit:
            entry["unit"] = t.unit
        if t.description:
            entry["description"] = t.description
        if t.block:
            entry["block"] = t.block
        if t.metadata_sheet:
            entry["metadata_sheet"] = t.metadata_sheet
        entry["sample"] = []
        for i, s in enumerate(t.samples, 1):
            e = {"assay": i, "name": s.name}
            if t.transposed:  # the sample is a row of the sheet
                e["row"] = int(s.source)
            else:
                e["column"] = s.source
            if s.attributes:
                e["attributes"] = s.attributes
            entry["sample"].append(e)
        out.append(entry)
    if out:
        doc["table"] = out
    if skipped:
        doc["skipped"] = [{k: v for k, v in x.items() if v} for x in skipped]  # no empty sheet name
    return doc


def write_parquet(path: Path, tables: list[Table], toml_name: str) -> int:
    """The tables of one result file stacked, one row per metabolite; returns the number of assay columns."""
    width = max(len(t.samples) for t in tables)
    fields = [pa.field("table_id", pa.string()), pa.field("feature_index", pa.int32()),
              pa.field("source_position", pa.int32()), pa.field("chemical_name", pa.string())]
    fields += [pa.field(k, pa.string()) for k in FEATURE_STR_FIELDS]
    fields += [pa.field(k, pa.float64()) for k in FEATURE_NUM_FIELDS]
    fields += [pa.field(f"abundance_assay[{i}]", pa.float64()) for i in range(1, width + 1)]
    schema = pa.schema(fields, metadata={
        "mbpost-samples-toml": toml_name,
        "mbpost-note": "abundance_assay[i] is sample assay=i of the [[table]] whose id is table_id",
    })
    # Abundances are mostly integer-valued peak heights: byte-stream-split compresses them better.
    floats = [f.name for f in fields if pa.types.is_floating(f.type)]
    with pq.ParquetWriter(path, schema, compression="zstd", compression_level=9,
                          use_dictionary=[f.name for f in fields if f.name not in floats],
                          column_encoding={name: "BYTE_STREAM_SPLIT" for name in floats}) as writer:
        for t in tables:
            n = len(t.features)
            cols = [pa.array([t.table_id] * n, pa.string()),
                    pa.array([x["feature_index"] for x in t.features], pa.int32()),
                    pa.array([x["source_position"] for x in t.features], pa.int32()),
                    pa.array([x["chemical_name"] for x in t.features], pa.string())]
            for k in FEATURE_STR_FIELDS:
                cols.append(pa.array([x.get(k) for x in t.features], pa.string()))
            for k in FEATURE_NUM_FIELDS:
                cols.append(pa.array([x.get(k) for x in t.features], pa.float64()))
            for j in range(width):
                if j < len(t.samples):
                    cols.append(pa.array([row[j] for row in t.matrix], pa.float64(), from_pandas=True))
                else:
                    cols.append(pa.nulls(n, pa.float64()))
            writer.write_table(pa.Table.from_arrays(cols, schema=schema))
    return width


def write_outputs(out_dir: Path, path: Path, tables: list[Table], skipped: list[dict]) -> list[dict]:
    """Write <stem>.toml (always) and <stem>.parquet (if the file has tables); returns its report rows."""
    ids = [t.table_id for t in tables]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:  # the ids link the TOML and the Parquet file
        raise ValueError(f"duplicate table ids in {path.name}: {duplicates}")
    toml_name, parquet_name = f"{path.stem}.toml", f"{path.stem}.parquet"
    with open(out_dir / toml_name, "wb") as fh:
        tomli_w.dump(toml_document(path, tables, skipped), fh)
    if tables:
        write_parquet(out_dir / parquet_name, tables, toml_name)
    rows = [{"file": path.name, "sheet": t.sheet, "table_id": t.table_id, "status": "extracted",
             "features_in": "columns" if t.transposed else "rows", "n_features": len(t.features),
             "n_samples": len(t.samples), "unit": t.unit or "", "orientation_basis": t.basis,
             "first_samples": "; ".join(s.name for s in t.samples[:4]), "reason": ""} for t in tables]
    rows += [{"file": path.name, "sheet": s["sheet"], "table_id": "", "status": "skipped", "features_in": "",
              "n_features": "", "n_samples": "", "unit": "", "orientation_basis": "", "first_samples": "",
              "reason": s["reason"]} for s in skipped]
    return rows


REPORT_COLUMNS = ["file", "sheet", "table_id", "status", "features_in", "n_features", "n_samples",
                  "unit", "orientation_basis", "first_samples", "reason"]


def main(argv: list | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--in-dir", default="mbpost_results", help="directory with the result files (default: mbpost_results)")
    ap.add_argument("--out-dir", default="mbpost_extracted", help="output directory (default: mbpost_extracted)")
    ap.add_argument("--include", nargs="+", metavar="GLOB", help="only the files whose name matches one of these patterns")
    ap.add_argument("--quiet", action="store_true", help="do not print one line per file")
    args = ap.parse_args(argv)

    in_dir, out_dir = Path(args.in_dir), Path(args.out_dir)
    files = input_files(in_dir, args.include)
    if not files:
        print(f"No result files found in {in_dir}", file=sys.stderr)
        return 1
    stems = Counter(p.stem for p in files)
    clashes = sorted(stem for stem, n in stems.items() if n > 1)
    if clashes:  # the outputs are named after the file name without its extension
        print(f"Result files with the same name apart from the extension: {clashes}", file=sys.stderr)
        return 1
    out_dir.mkdir(parents=True, exist_ok=True)

    report: list[dict] = []
    n_tables = n_rows = 0
    for i, path in enumerate(files, 1):
        tables, skipped = extract_file(path)
        report.extend(write_outputs(out_dir, path, tables, skipped))
        n_tables += len(tables)
        n_rows += sum(len(t.features) for t in tables)
        if not args.quiet:
            shapes = ", ".join(f"{len(t.features)}x{len(t.samples)}" for t in tables) or "-"
            print(f"[{i}/{len(files)}] {path.name}: {len(tables)} table(s) ({shapes}), {len(skipped)} skipped", flush=True)

    with open(out_dir / REPORT_TSV, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=REPORT_COLUMNS, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(report)
    print(f"Wrote {len(files)} TOML files and {len({r['file'] for r in report if r['status'] == 'extracted'})} "
          f"Parquet files ({n_tables} tables, {n_rows} metabolite rows) to {out_dir}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
