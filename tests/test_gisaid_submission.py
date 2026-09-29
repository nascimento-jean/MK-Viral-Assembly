import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "bin" / "make_gisaid_submission.py"
METADATA_SCRIPT = REPO / "bin" / "make_metadata_xlsx.py"
TEMPLATES = REPO / "assets" / "gisaid_templates"
WHEELS = REPO / "assets" / "python_wheels"

for wheel in sorted(WHEELS.glob("*.whl")):
    sys.path.insert(0, str(wheel))
import xlrd

spec = importlib.util.spec_from_file_location("make_metadata_xlsx", METADATA_SCRIPT)
metadata_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(metadata_module)


class GisaidSubmissionTests(unittest.TestCase):
    headers = [
        "Vírus", "Código Amostra", "Data Coleta", "Município",
        "UF município solicitante", "Idade", "Tipo Idade", "Sexo",
        "Tecnologia de Sequenciamento", "Submissor", "Lab_Origem", "Lab_Submissão", "Endereço",
        "Autores", "Código da Região", "Sorotipo", "Genótipo",
    ]

    @staticmethod
    def read_submission_field(path: Path, code: str) -> str:
        book = xlrd.open_workbook(str(path))
        sheet = book.sheet_by_name("Submissions")
        headers = sheet.row_values(0)
        return str(sheet.cell_value(2, headers.index(code)))

    def run_submission(self, kind: str, row: list[str], fasta_text: str):
        root_context = tempfile.TemporaryDirectory()
        self.addCleanup(root_context.cleanup)
        root = Path(root_context.name)
        metadata = root / "metadata.xlsx"
        fasta_dir = root / "consensus"
        fasta_dir.mkdir()
        (fasta_dir / "sample.consensus.fa").write_text(fasta_text, encoding="utf-8")
        out_xls = root / f"{kind}_GISAID_submission.xls"
        out_fasta = root / f"{kind}_GISAID_submission.fasta"
        metadata_module.write_xlsx(metadata, self.headers, [row])
        completed = subprocess.run(
            [
                sys.executable, str(SCRIPT),
                "--metadata-xlsx", str(metadata),
                "--consensus-fasta", str(fasta_dir),
                "--virus", kind,
                "--templates-dir", str(TEMPLATES),
                "--vendor-dir", str(WHEELS),
                "--out-xls", str(out_xls),
                "--out-fasta", str(out_fasta),
            ],
            check=False, capture_output=True, text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertTrue(out_xls.is_file(), completed.stderr)
        self.assertTrue(out_fasta.is_file(), completed.stderr)
        return out_xls, out_fasta

    def test_dengue_writes_mandatory_serotype(self):
        row = [
            "DENV2", "SAMPLE01", "2026-09-20", "Maceió", "AL", "30", "anos", "Feminino",
            "Illumina NextSeq 2000", "submitter", "LACEN-AL", "LACEN-AL", "Maceió, AL, Brasil",
            "Jean Nascimento", "AL", "DENV2", "",
        ]
        out_xls, out_fasta = self.run_submission("dengue", row, ">SAMPLE01\nACGT\n")
        self.assertEqual(self.read_submission_field(out_xls, "arbo_subtype"), "DENV2")
        self.assertEqual(self.read_submission_field(out_xls, "arbo_seq_technology"), "Illumina NextSeq 2000")
        self.assertEqual(self.read_submission_field(out_xls, "arbo_virus_name"), "hDenV2/Brazil/AL-SAMPLE01/2026")
        self.assertIn(">hDenV2/Brazil/AL-SAMPLE01/2026", out_fasta.read_text(encoding="utf-8"))

    def test_rsv_writes_mandatory_subtype(self):
        row = [
            "VSR", "SAMPLE02", "2026-09-21", "Maceió", "AL", "8", "meses", "",
            "", "submitter", "LACEN-AL", "LACEN-AL", "Maceió, AL, Brasil",
            "Jean Nascimento", "AL", "", "A",
        ]
        out_xls, out_fasta = self.run_submission("vsr", row, ">SAMPLE02|segment-A\nTGCA\n")
        self.assertEqual(self.read_submission_field(out_xls, "rsv_subtype"), "A")
        self.assertEqual(self.read_submission_field(out_xls, "rsv_gender"), "unknown")
        self.assertEqual(self.read_submission_field(out_xls, "rsv_seq_technology"), "Illumina")
        self.assertEqual(self.read_submission_field(out_xls, "rsv_virus_name"), "hRSV/A/Brazil/AL-SAMPLE02/2026")
        self.assertIn(">hRSV/A/Brazil/AL-SAMPLE02/2026", out_fasta.read_text(encoding="utf-8"))

    def test_metadata_builder_preserves_user_supplied_dengue_serotype_and_rsv_subtype(self):
        cases = [
            ("Dengue", "Dengue", "DENV3", "", "Sorotipo", "DENV3"),
            ("VSR", "VSR", "", "B", "Genótipo", "B"),
        ]
        for virus_arg, virus_value, serotype, genotype, expected_field, expected_value in cases:
            with self.subTest(virus=virus_arg), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                metadata_csv = root / "metadata.csv"
                metadata_csv.write_text(
                    "Código Amostra,Vírus,Sorotipo,Genótipo,Data Coleta,Sexo,Submissor,Lab_Origem,Lab_Submissão,Endereço,Autores,Código da Região\n"
                    f"SAMPLE01,{virus_value},{serotype},{genotype},2026-09-20,Feminino,submitter,LACEN-AL,LACEN-AL,Maceió,Jean Nascimento,AL\n",
                    encoding="utf-8",
                )
                qc_dir = root / "qc"
                qc_dir.mkdir()
                (qc_dir / "sample.tsv").write_text(
                    "sample\tsegment\tcompleteness\tbreadth_ge_20x\tmean_depth\n"
                    "SAMPLE01\tALL\t0.95\t0.95\t100\n",
                    encoding="utf-8",
                )
                workbook = root / "metadata.xlsx"
                completed = subprocess.run(
                    [
                        sys.executable, str(METADATA_SCRIPT),
                        "--metadata", str(metadata_csv),
                        "--virus", virus_arg,
                        "--qc-dir", str(qc_dir),
                        "--out", str(workbook),
                    ],
                    check=False, capture_output=True, text=True,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)
                # Read the generated OOXML with the submission script's parser.
                spec = importlib.util.spec_from_file_location("make_gisaid_submission_for_test", SCRIPT)
                gisaid_module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(gisaid_module)
                generated_headers, generated_rows = gisaid_module.read_metadata_xlsx(workbook)
                self.assertIn(expected_field, generated_headers)
                self.assertEqual(generated_rows[0][expected_field], expected_value)

    def test_rejects_missing_vendored_dependencies(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            completed = subprocess.run(
                [
                    sys.executable, str(SCRIPT),
                    "--metadata-xlsx", str(root / "missing.xlsx"),
                    "--consensus-fasta", str(root),
                    "--virus", "dengue",
                    "--templates-dir", str(TEMPLATES),
                    "--vendor-dir", str(root),
                    "--out-xls", str(root / "out.xls"),
                    "--out-fasta", str(root / "out.fasta"),
                ],
                check=False, capture_output=True, text=True,
            )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("no vendored Python wheels", completed.stderr)


if __name__ == "__main__":
    unittest.main()
