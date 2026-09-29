import importlib.util
import tempfile
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "bin" / "make_metadata_xlsx.py"
spec = importlib.util.spec_from_file_location("metadata", SCRIPT)
metadata = importlib.util.module_from_spec(spec)
spec.loader.exec_module(metadata)


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

    def test_xlsx_template_can_be_read_after_user_adds_a_row(self):
        headers = ["Código Amostra", "Vírus", "Sorotipo", "Subtipo", "Genótipo"]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "metadata.xlsx"
            metadata.write_xlsx(path, headers, [["SAMPLE01", "Dengue", "DENV1", "", "I"]])
            self.assertEqual(metadata.read_table(path)[0]["Código Amostra"], "SAMPLE01")
            self.assertEqual(metadata.read_table(path)[0]["Sorotipo"], "DENV1")


if __name__ == "__main__":
    unittest.main()
