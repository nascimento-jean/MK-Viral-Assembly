import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("local_api", ROOT / "webtool" / "local_api.py")
api = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(api)


class WebToolNewOptionsTests(unittest.TestCase):
    def test_command_uses_user_reference_bed_gff_and_optional_snpeff(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "tests") as directory:
            root = Path(directory)
            reads = root / "reads"
            reads.mkdir()
            reference = root / "ref.fasta"
            reference.write_text(">ref\nAAAA\n", encoding="utf-8")
            bed = root / "primers.bed"
            bed.write_text("ref\t0\t1\tLEFT\n", encoding="utf-8")
            gff = root / "ref.gff3"
            gff.write_text("ref\ttest\tCDS\t1\t4\t.\t+\t0\tID=cds1\n", encoding="utf-8")
            payload = {
                "run_name": "test", "virus": "Dengue", "profile": "standalone",
                "input_mode": "single", "raw_data_dir": str(reads),
                "reference": str(reference), "primer_bed": str(bed), "gff": str(gff),
                "outdir": str(root / "results"), "snpeff": True,
                "nextclade": False, "blast": False,
            }
            with patch.object(api, "NEXTFLOW", Path("/bin/echo")):
                command, normalized = api.build_command(payload)
            self.assertEqual(normalized["reference"], str(reference))
            self.assertEqual(normalized["primer_bed"], str(bed))
            self.assertEqual(normalized["gff"], str(gff))
            self.assertTrue(normalized["snpeff"])
            self.assertEqual(command[command.index("--reference") + 1], str(reference))
            self.assertEqual(command[command.index("--primer_bed") + 1], str(bed))
            self.assertEqual(command[command.index("--gff") + 1], str(gff))
            self.assertEqual(command[command.index("--snpeff") + 1], "true")
            self.assertNotIn("--reference_mode", command)
            self.assertNotIn("--reference_panel", command)
            self.assertNotIn("--primer_scheme", command)


if __name__ == "__main__":
    unittest.main()
