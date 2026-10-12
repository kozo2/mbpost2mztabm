"""Tests of the layout detection in extract_mbpost_tables.py, on small synthetic sheets.

Each sheet mimics a layout found in the MB-POST result files.

    .venv/bin/python -m unittest test_extract_mbpost_tables -v
"""

import random
import tempfile
import tomllib
import unittest
from pathlib import Path

import pyarrow.parquet as pq

import extract_mbpost_tables as E

IDENT = {"table_id": "T", "mbpost_id": "MPST000000", "source_file": "T.xlsx", "sheet": "S"}
rng = random.Random(0)


def levels(n, spread=3.0):
    """Typical levels of n metabolites, over a few orders of magnitude."""
    return [10 ** rng.uniform(0, spread) for _ in range(n)]


def matrix(n_rows, n_cols, noise=0.05):
    """Rows are metabolites with their own level; samples vary little around it."""
    return [[round(lv * rng.uniform(1 - noise, 1 + noise), 4) for _ in range(n_cols)] for lv in levels(n_rows)]


def extract(grid, name="S"):
    result = E.extract_sheet(name, grid, IDENT)
    assert not isinstance(result, str), result
    return result


class Cells(unittest.TestCase):
    def test_kinds(self):
        self.assertEqual(E.classify("1.5e-3"), (E.NUM, 0.0015))
        self.assertEqual(E.classify("−3.5")[1], -3.5)
        for marker in ("N.D.", "NA", "null", "‒", "ー", "-"):
            self.assertEqual(E.classify(marker)[0], E.MISS, marker)
        self.assertEqual(E.classify("−")[0], E.TEXT)  # a lone minus sign is a polarity
        self.assertEqual(E.classify("2.83±0.01")[0], E.TEXT)
        self.assertEqual(E.classify(None)[0], E.EMPTY)

    def test_text_is_tidied(self):
        self.assertEqual(E.clean(" Peak\n  area\xa0"), "Peak area")
        self.assertIsNone(E.clean("  "))


class FeatureRows(unittest.TestCase):
    def test_simple_table(self):
        names = ["Ala", "Gly", "Ser", "Lys"]
        body = matrix(4, 3)
        grid = [["Metabolite", "S1", "S2", "S3"]] + [[n] + row for n, row in zip(names, body)]
        (t,) = extract(grid)
        self.assertEqual([s.name for s in t.samples], ["S1", "S2", "S3"])
        self.assertEqual([x["chemical_name"] for x in t.features], names)
        self.assertEqual(list(t.matrix[2]), body[2])
        self.assertFalse(t.transposed)

    def test_group_and_replicate_header_with_unit_and_annotations(self):
        """MPST000001: title, merged group labels, replicate numbers, annotation columns."""
        grid = [
            [None, "Supplementary Table 1. Quantitative lipidomics of cell lines"],
            [None, "Lipid name", "Exact Mass", "Amount of lipids (nmol/mg-protein)"] + [None] * 5,
            [None, None, None, "Ba/F3", "Ba/F3", "Ba/F3", "Tm63b", "Tm63b", "Tm63b"],
            [None, None, None, 1, 2, 3, 1, 2, 3],
        ]
        for i, row in enumerate(matrix(6, 6)):
            grid.append([None, f"PC({i})", 500.5 + i] + row)
        (t,) = extract(grid)
        self.assertEqual([s.name for s in t.samples],
                         ["Ba/F3_1", "Ba/F3_2", "Ba/F3_3", "Tm63b_1", "Tm63b_2", "Tm63b_3"])
        self.assertEqual(t.unit, "nmol/mg-protein")
        self.assertTrue(t.description.startswith("Supplementary Table 1."))
        self.assertEqual(t.features[0]["theoretical_neutral_mass"], 500.5)
        self.assertEqual(t.samples[4].attributes, {"header_1": "Tm63b", "header_2": "2"})

    def test_missing_values_and_empty_rows(self):
        grid = [["Name", "S1", "S2", "S3"],
                ["A", 1.5, "N.D.", 3.0],
                ["B", "N.D.", "N.D.", "N.D."],
                ["IS", None, None, None],  # an internal standard without abundances
                ["C", 2.0, "‒", 4.0]]
        (t,) = extract(grid)
        self.assertEqual([x["chemical_name"] for x in t.features], ["A", "B", "C"])
        nan = [[v != v for v in row] for row in t.matrix]
        self.assertEqual(nan, [[False, True, False], [True, True, True], [False, True, False]])

    def test_metabolite_that_is_not_detected_in_most_samples(self):
        """The first metabolite has too few numbers to look like a data row; its m/z is no abundance."""
        grid = [["Annotation", "Ave m/z", "TW-1", "TW-2", "TW-3", "TW-4", "TW-5"],
                ["Glycolate", 75.01, "N.D.", "N.D.", "N.D.", "N.D.", 2.0],
                ["Lactate", 89.02] + matrix(1, 5)[0]]
        (t,) = extract(grid)
        self.assertEqual([s.name for s in t.samples], ["TW-1", "TW-2", "TW-3", "TW-4", "TW-5"])
        self.assertEqual([x["chemical_name"] for x in t.features], ["Glycolate", "Lactate"])

    def test_sample_numbers_are_titles_not_a_metabolite(self):
        """MPST000218: the titles of the sample columns are numbers (with gaps) under a group row."""
        grid = [["Metabolite concentration (\u00b5M)", None, None, "Group", "Control", None, None, "Pf", None, None],
                ["KEGG ID", "Annotation", "Ave m/z", "Ave CorMT", 33, 34, 35, 36, 37, 38],
                ["C1", "Adenine", 136.06, 11.5] + matrix(1, 6)[0],
                ["C2", "Adenosine", 268.1, 14.9] + matrix(1, 6)[0],
                ["C3", "Agmatine", 131.1, 7.8] + matrix(1, 6)[0]]
        (t,) = extract(grid)
        self.assertEqual([s.name for s in t.samples], ["33", "34", "35", "36", "37", "38"])
        self.assertEqual([x["chemical_name"] for x in t.features], ["Adenine", "Adenosine", "Agmatine"])
        self.assertEqual(t.unit, "\u00b5M")

    def test_sample_numbers_restart_and_statistics_follow(self):
        """MPST000197: groups, then a title row with the sample numbers (QC numbers again from 1), statistics at the right."""
        titles = ["Polarity", "index", "m/z", "rt", "z", "Annotation", "Class"]
        groups = ["Control"] * 3 + ["HFpEF"] * 3 + ["QC"] * 2
        numbers = [1, 2, 3, 4, 5, 6, 1, 2]
        grid = [[None] * 7 + groups + [None, None],
                titles + numbers + ["Fold change", "P-value"]]
        for i, row in enumerate(matrix(8, 8)):
            grid.append(["Neg", 100 + i, 300.1 + i, 5.0 + i, -1, f"FA({i})", "FA"] + row + [1.2 + i / 100, 0.001 * (i + 1)])
        (t,) = extract(grid)
        self.assertEqual([s.name for s in t.samples],
                         ["Control_1", "Control_2", "Control_3", "HFpEF_4", "HFpEF_5", "HFpEF_6", "QC_1", "QC_2"])
        self.assertEqual([x["chemical_name"] for x in t.features], [f"FA({i})" for i in range(8)])  # no title row
        self.assertFalse(t.transposed)

    def test_group_label_written_once_goes_with_the_rows_below(self):
        """MPST000037: the lipid is named once above its isotopologues m0, m1, ..."""
        grid = [["No.", "TG", "Isotopologues", "Sample", None, None, None, None, None],
                [None, None, None, "sample name", None, 16, 17, 18, 19],
                [None, None, None, "Ave m/z", "Ave CorMT", None, None, None, None]]
        k = 0
        for lipid in ("46:3", "48:4"):
            for iso in ("m0", "m1", "m2"):
                k += 1
                grid.append([k, lipid if iso == "m0" else None, iso, 790.7 + k, 14.7] + matrix(1, 4)[0])
        (t,) = extract(grid)
        self.assertEqual([x["chemical_name"] for x in t.features],
                         ["46:3 m0", "46:3 m1", "46:3 m2", "48:4 m0", "48:4 m1", "48:4 m2"])

    def test_statistics_columns_are_no_samples_but_samples_named_fdr_are(self):
        grid = [["Metabolite", "FDR-1", "FDR-2", "FDR-3", "Q-value", "Fold change", "P-value"]]
        for i, row in enumerate(matrix(6, 3)):
            grid.append([f"M{i}"] + row + [0.01 * (i + 1), 1.5, 0.04])
        (t,) = extract(grid)
        self.assertEqual([s.name for s in t.samples], ["FDR-1", "FDR-2", "FDR-3"])

    def test_ms_dial(self):
        """MS-DIAL alignment result: sample classes above the titles, Average/Stdev at the end."""
        ann = ["Alignment ID", "Average Rt(min)", "Average Mz", "Metabolite name", "Adduct type",
               "Post curation result", "Fill %", "MS/MS assigned", "Formula", "MS/MS spectrum"]
        body = matrix(4, 3)
        grid = [[None] * 9 + ["Class", 1, 1, 2, "NA", "NA"],
                [None] * 9 + ["File type", "Blank", "Sample", "Sample", "NA", "NA"],
                [None] * 9 + ["Batch ID", 1, 1, 1, "Average", "Stdev"],
                ann + ["blank_1", "s_1", "s_2", 1, 1]]
        for i, row in enumerate(body):
            grid.append([i, 5.1 + i, 300.1 + i, "Unknown", "[M+H]+", None, 0.5, "False", "C2H6", None]
                        + row + [sum(row) / 3, 0.1])
        (t,) = extract(grid)
        self.assertEqual([s.name for s in t.samples], ["blank_1", "s_1", "s_2"])
        self.assertEqual(t.samples[0].attributes["File type"], "Blank")
        self.assertEqual(t.features[1]["feature_id"], "1")
        self.assertEqual(t.features[1]["adduct_ions"], "[M+H]+")
        self.assertEqual(t.features[2]["exp_mass_to_charge"], 302.1)

    def test_numeric_precursor_ion_is_not_an_adduct(self):
        """MRM tables: the precursor ion is an m/z. Only text is taken as the adduct; IDs may be numbers."""
        grid = [["ID", "Lipid", "Precursor ion", "Adduct ion", "S1", "S2", "S3"]]
        for i, row in enumerate(matrix(4, 3)):
            grid.append([i + 1, f"PC {i}", 700.5 + i, "[M + H]+", *row])
        (t,) = extract(grid)
        self.assertEqual([x["feature_id"] for x in t.features], ["1", "2", "3", "4"])
        self.assertEqual({x.get("adduct_ions") for x in t.features}, {"[M + H]+"})
        grid[0][2] = "Precursor-ion (Q1)"  # the MPST000001 spelling, with text values
        for row in grid[1:]:
            row[2] = "[M + NH4]+"
        (t,) = extract([row[:3] + row[4:] for row in grid])  # no separate adduct column
        self.assertEqual({x.get("adduct_ions") for x in t.features}, {"[M + NH4]+"})
        grid[0][2] = "Precursor ion"
        for i, row in enumerate(grid[1:]):
            row[2] = 700.5 + i
        grid = [row[:3] + row[4:] for row in grid]  # numeric precursor ion, no adduct column
        (t,) = extract(grid)
        self.assertNotIn("adduct_ions", t.features[0])

    def test_blocks_of_different_quantities(self):
        """MPST000111: peak areas and normalised values of the same samples next to each other."""
        n = 4
        area = matrix(6, n, noise=0.1)
        rel = [[v / 1e6 for v in row] for row in area]
        grid = [["Compound", "Peak area", None, None, None, "Relative peak area", None, None, None],
                [None] + ["S1", "S2", "S3", "S4"] * 2]
        grid += [[f"M{i}"] + a + r for i, (a, r) in enumerate(zip(area, rel))]
        tables = extract(grid)
        self.assertEqual([t.block for t in tables], ["Peak area", "Relative peak area"])
        self.assertEqual([s.name for s in tables[1].samples], ["S1", "S2", "S3", "S4"])
        self.assertEqual(list(tables[1].matrix[0]), rel[0])
        self.assertEqual(tables[1].table_id, "T#Relative peak area")


class Transposed(unittest.TestCase):
    def test_samples_in_rows(self):
        """MRM matrix: one row per sample, one column per metabolite."""
        lv = levels(12)
        grid = [["SampleName"] + [f"t1MRM{i:03d}" for i in range(12)]]
        for s in range(30):
            grid.append([f"Sample_{s + 1:03d}"] + [round(v * rng.uniform(0.9, 1.1), 3) for v in lv])
        (t,) = extract(grid)
        self.assertTrue(t.transposed)
        self.assertEqual(len(t.features), 12)
        self.assertEqual(t.features[0]["chemical_name"], "t1MRM000")
        self.assertEqual(len(t.samples), 30)
        self.assertEqual((t.samples[0].name, t.samples[0].source), ("Sample_001", "2"))
        self.assertEqual(t.matrix[3][5], grid[6][4])

    def test_sample_attributes_from_label_columns(self):
        lv = levels(8)
        grid = [["Subject ID", "Pre/Post*"] + [f"AA{i}" for i in range(8)]]
        for s, when in enumerate(["Pre", "Post", "Pre", "Post", "Pre", "Post"]):
            grid.append([f"Feces{s}", when] + [round(v * rng.uniform(0.9, 1.1)) for v in lv])
        (t,) = extract(grid)
        self.assertTrue(t.transposed)
        self.assertEqual(t.samples[1].name, "Feces1")
        self.assertEqual(t.samples[1].attributes, {"Pre/Post*": "Post"})

    def test_data_file_names_label_samples(self):
        """A calibration series varies more across samples than across metabolites."""
        grid = [["", "glucose", "G6P", "FBP"]]
        for i, conc in enumerate([10, 50, 100, 10, 50, 100]):
            grid.append([f"mix{conc:03d}_{i}.mzML", conc * 5, conc * 7, conc * 6])
        (t,) = extract(grid)
        self.assertTrue(t.transposed)
        self.assertEqual([x["chemical_name"] for x in t.features], ["glucose", "G6P", "FBP"])


class CompoundBlocks(unittest.TestCase):
    def test_block_of_columns_per_compound(self):
        """MPST000150: Area, Concentration, Average, S.D. per compound; labels once per group."""
        head = ["Cell", "Condition", "", "Area", "Concentration (pmol)", "Average", "S.D."] + \
               ["Area", "Concentration (pmol)", "Average", "S.D."] * 2
        grid = [[None] * 3 + ["Fumalic acid", None, None, None, "Succinic acid", None, None, None,
                              "Malic acid", None, None, None],
                head]
        for i in range(6):
            first = i % 3 == 0
            grid.append([("HCT116" if i == 0 else None), ("DMSO" if i == 0 else "ASA" if i == 3 else None),
                         ("control" if i == 0 else None)]
                        + [x for _ in range(3) for x in (1000 + i, 20.5 + i, 21.0 if first else None,
                                                         0.5 if first else None)])
        tables = extract(grid)
        self.assertEqual([t.block for t in tables], ["Area", "Concentration (pmol)"])
        conc = tables[1]
        self.assertTrue(conc.transposed)
        self.assertEqual(conc.unit, "pmol")
        self.assertEqual([x["chemical_name"] for x in conc.features], ["Fumalic acid", "Succinic acid", "Malic acid"])
        self.assertEqual(list(conc.matrix[0]), [20.5 + i for i in range(6)])
        self.assertEqual([s.name for s in conc.samples][:2], ["HCT116_DMSO_control_1", "HCT116_DMSO_control_2"])
        self.assertEqual(conc.samples[3].attributes["Condition"], "ASA")


class Metadata(unittest.TestCase):
    def test_sample_metadata_sheet(self):
        grid = [["Name", "f1", "f2", "f3"]] + [[f"M{i}"] + row for i, row in enumerate(matrix(4, 3))]
        (t,) = extract(grid)
        meta = [["File", "Group", "Age"], ["f1", "case", 61], ["f2", "control", "null"], ["f3", "case", 58]]
        self.assertTrue(E.attach_sample_metadata(t, "metadata", meta))
        self.assertEqual(t.samples[0].attributes, {"Group": "case", "Age": "61"})
        self.assertEqual(t.samples[1].attributes, {"Group": "control"})  # "null" is not a value
        self.assertFalse(E.attach_sample_metadata(t, "other", [["a", "b"], ["x", 1], ["y", 2]]))


class Outputs(unittest.TestCase):
    """One TOML and one Parquet file per result file."""

    def test_files_are_named_after_the_result_file(self):
        grid = [["Name", "S1", "S2"]] + [[f"M{i}"] + row for i, row in enumerate(matrix(4, 2))]
        wide = [["Name"] + [f"W{j}" for j in range(5)]] + [[f"M{i}"] + row for i, row in enumerate(matrix(3, 5))]
        tables = extract(grid) + E.extract_sheet("S2", wide, {**IDENT, "table_id": "T#S2", "sheet": "S2"})
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            rows = E.write_outputs(out, Path("MPST000042.xlsx"), tables, [{"sheet": "Notes", "reason": "no numeric cells"}])
            E.write_outputs(out, Path("MPST000043.csv"), [], [{"sheet": "", "reason": "empty sheet"}])
            self.assertEqual(sorted(p.name for p in out.iterdir()),
                             ["MPST000042.parquet", "MPST000042.toml", "MPST000043.toml"])  # no Parquet without tables
            toml = tomllib.loads((out / "MPST000042.toml").read_text(encoding="utf-8"))
            self.assertEqual((toml["source_file"], toml["mbpost_id"], toml["n_tables"]), ("MPST000042.xlsx", "MPST000042", 2))
            self.assertEqual([t["id"] for t in toml["table"]], ["T", "T#S2"])
            self.assertEqual(toml["skipped"], [{"sheet": "Notes", "reason": "no numeric cells"}])
            pf = pq.ParquetFile(out / "MPST000042.parquet")
            self.assertEqual(pf.schema_arrow.metadata[b"mbpost-samples-toml"], b"MPST000042.toml")
            assays = [n for n in pf.schema_arrow.names if n.startswith("abundance_assay[")]
            self.assertEqual(len(assays), 5)  # the widest table of this file, not of all files
            first = pf.read_row_group(0).to_pylist()
            self.assertEqual([r["table_id"] for r in first], ["T"] * 4)
            self.assertIsNone(first[0]["abundance_assay[3]"])  # beyond the 2 samples of the table
            self.assertEqual(first[0]["abundance_assay[2]"], tables[0].matrix[0][1])
            none = tomllib.loads((out / "MPST000043.toml").read_text(encoding="utf-8"))
            self.assertEqual((none["n_tables"], none["skipped"]), (0, [{"reason": "empty sheet"}]))
            self.assertEqual([r["status"] for r in rows], ["extracted", "extracted", "skipped"])

    def test_duplicate_table_ids_are_refused(self):
        grid = [["Name", "S1", "S2"]] + [[f"M{i}"] + row for i, row in enumerate(matrix(4, 2))]
        tables = extract(grid) * 2
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                E.write_outputs(Path(tmp), Path("MPST000044.xlsx"), tables, [])


class NoTable(unittest.TestCase):
    def test_reasons(self):
        for grid, reason in [
            ([["a", "b"], ["x", "y"], ["z", "w"]], "no numeric cells"),
            ([["Lipid", "m/z", "RT (min)"], ["PC 16:0", 760.6, 5.1], ["PC 18:1", 786.6, 5.9]],
             "no abundance columns (only annotation columns)"),
            ([], "empty sheet"),
        ]:
            self.assertEqual(E.extract_sheet("S", grid, IDENT), reason)


if __name__ == "__main__":
    unittest.main()
