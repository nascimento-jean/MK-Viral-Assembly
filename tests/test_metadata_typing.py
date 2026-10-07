import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "bin" / "make_metadata_xlsx.py"
GISAID_SCRIPT = REPO / "bin" / "make_gisaid_submission.py"
spec = importlib.util.spec_from_file_location("metadata", SCRIPT)
metadata = importlib.util.module_from_spec(spec)
spec.loader.exec_module(metadata)
gisaid_spec = importlib.util.spec_from_file_location("gisaid", GISAID_SCRIPT)
gisaid = importlib.util.module_from_spec(gisaid_spec)
gisaid_spec.loader.exec_module(gisaid)


class TypingResolutionTests(unittest.TestCase):
    def test_dengue_normalization_variants(self):
        for raw in ("DENV-2", "denv2", "Dengue virus 2", "Sorotipo 2", "2"):
            with self.subTest(raw=raw):
                self.assertEqual(metadata.normalize_dengue_serotype(raw), "DENV2")

    def test_rsv_detailed_lineage_maps_to_subtype(self):
        for raw in ("A", "A.D.1", "RSV-A", "VSR A"):
            with self.subTest(raw=raw):
                self.assertEqual(metadata.normalize_rsv_subtype(raw), "A")

    def test_analytic_dengue_call_is_used_when_declared_value_agrees(self):
        value, source, alert = metadata.resolve_typing(
            "dengue", {"Sorotipo": "DENV-2"}, {},
            [{"best_hit_species": "Dengue virus 2"}],
        )
        self.assertEqual((value, source, alert), ("DENV2", "BLAST", ""))

    def test_rsv_subtype_is_derived_but_detailed_lineage_is_preserved(self):
        row = {"lineage": "A.D.1"}
        value, source, alert = metadata.resolve_typing("vsr", {"Subtipo": "A"}, row, [])
        self.assertEqual((value, source, alert), ("A", "Nextclade", ""))
        self.assertEqual(metadata.fmt_lineage(row), "A.D.1")

    def test_declared_value_is_fallback_without_analytic_call(self):
        value, source, alert = metadata.resolve_typing("dengue", {"Sorotipo": "DENV3"}, {}, [])
        self.assertEqual(value, "DENV3")
        self.assertEqual(source, "Metadados/identificação da análise")
        self.assertEqual(alert, "")

    def test_metadata_vs_analysis_conflict_is_not_autofilled(self):
        value, source, alert = metadata.resolve_typing(
            "dengue", {"Sorotipo": "DENV3"}, {},
            [{"best_hit_species": "Dengue virus 2"}],
        )
        self.assertEqual(value, "")
        self.assertEqual(source, "")
        self.assertIn("Conflito", alert)
        self.assertIn("DENV2", alert)
        self.assertIn("DENV3", alert)

    def test_nextclade_vs_blast_conflict_is_not_autofilled(self):
        value, source, alert = metadata.resolve_typing(
            "vsr", {}, {"lineage": "A.D.1"}, [{"best_hit_species": "RSV B"}],
        )
        self.assertEqual(value, "")
        self.assertEqual(source, "")
        self.assertIn("Conflito analítico", alert)

    def test_metadata_headers_keep_only_sequence_name_after_typing(self):
        for kind in ("sarscov2", "chikungunya", "oropouche", "dengue", "vsr"):
            with self.subTest(kind=kind):
                headers = metadata.output_headers(kind)
                self.assertNotIn("Origem da Tipagem", headers)
                self.assertNotIn("Alerta de Tipagem", headers)
                self.assertEqual(headers[-1], "Nome da Sequencia")

    def test_sequence_name_matches_gisaid_virus_name_for_all_supported_viruses(self):
        cases = [
            ("SARS-CoV-2", "sarscov2", {}),
            ("Chikungunya", "chikungunya", {}),
            ("Oropouche", "oropouche", {}),
            ("Dengue", "dengue", {"Sorotipo": "DENV2"}),
            ("VSR", "vsr", {"Subtipo": "A", "Genótipo": "A.D.1"}),
        ]
        for virus, kind, extra in cases:
            with self.subTest(virus=virus):
                row = {
                    "Vírus": virus,
                    "Data Coleta": "2026-10-07",
                    "Código da Região": "AL-LACENAL",
                    **extra,
                }
                warnings = []
                expected = gisaid.build_virus_name(kind, row, "SAMPLE01", "2026", warnings)
                self.assertEqual(warnings, [])
                self.assertEqual(
                    metadata.build_sequence_name(metadata.virus_kind(virus), row, "SAMPLE01"),
                    expected,
                )

    def test_generated_workbook_populates_sequence_name_for_all_supported_viruses(self):
        cases = [
            ("sarscov2", "SARS-CoV-2", "", "", "", "hCoV-19/Brazil/AL-LACENAL-SAMPLE01/2026"),
            ("chikv", "Chikungunya", "", "", "", "ChikV/Brazil/AL-LACENAL-SAMPLE01/2026"),
            ("orov", "Oropouche", "", "", "", "hOROV/Brazil/AL-LACENAL-SAMPLE01/2026"),
            ("denv2", "Dengue", "DENV2", "", "", "hDenV2/Brazil/AL-LACENAL-SAMPLE01/2026"),
            ("vsr", "VSR", "", "A", "A.D.1", "hRSV/A/Brazil/AL-LACENAL-SAMPLE01/2026"),
        ]
        for virus_arg, virus, serotype, subtype, genotype, expected in cases:
            with self.subTest(virus=virus), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                source = root / "source.xlsx"
                metadata.write_xlsx(
                    source,
                    ["Código Amostra", "Vírus", "Data Coleta", "Código da Região", "Sorotipo", "Subtipo", "Genótipo"],
                    [["SAMPLE01", virus, "2026-10-07", "AL-LACENAL", serotype, subtype, genotype]],
                )
                qc_dir = root / "qc"
                qc_dir.mkdir()
                (qc_dir / "sample.tsv").write_text(
                    "sample\tsegment\tcompleteness\tbreadth_ge_20x\tmean_depth\n"
                    "SAMPLE01\tALL\t0.95\t0.95\t100\n",
                    encoding="utf-8",
                )
                output = root / f"metadata_{virus_arg}.xlsx"
                completed = subprocess.run(
                    [
                        sys.executable, str(SCRIPT),
                        "--metadata", str(source),
                        "--virus", virus_arg,
                        "--qc-dir", str(qc_dir),
                        "--out", str(output),
                    ],
                    check=False, capture_output=True, text=True,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)
                row = metadata.read_table(output)[0]
                self.assertNotIn("Origem da Tipagem", row)
                self.assertNotIn("Alerta de Tipagem", row)
                self.assertEqual(row["Nome da Sequencia"], expected)

    def test_xlsx_template_can_be_read_after_user_adds_a_row(self):
        headers = ["Código Amostra", "Vírus", "Sorotipo", "Subtipo", "Genótipo"]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "metadata.xlsx"
            metadata.write_xlsx(path, headers, [["SAMPLE01", "Dengue", "DENV1", "", "I"]])
            self.assertEqual(metadata.read_table(path)[0]["Código Amostra"], "SAMPLE01")
            self.assertEqual(metadata.read_table(path)[0]["Sorotipo"], "DENV1")


if __name__ == "__main__":
    unittest.main()
