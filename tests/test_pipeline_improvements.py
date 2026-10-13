import csv
import importlib.util
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def load_script(name):
    path = ROOT / "bin" / name
    spec = importlib.util.spec_from_file_location(name.replace(".", "_"), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_main(module, *args):
    with patch.object(sys, "argv", [module.__file__, *map(str, args)]):
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            module.main()


class PipelineImprovementTests(unittest.TestCase):
    def test_schema_is_valid_and_separates_thresholds(self):
        schema = json.loads((ROOT / "nextflow_schema.json").read_text(encoding="utf-8"))
        calling = schema["definitions"]["calling"]["properties"]
        self.assertEqual(calling["trim_min_len"]["default"], 30)
        self.assertEqual(calling["consensus_min_freq"]["default"], 0.75)
        self.assertEqual(calling["variant_min_freq"]["default"], 0.25)

    def test_cli_numeric_parameters_are_coerced_before_comparison(self):
        source = (ROOT / "main.nf").read_text(encoding="utf-8")
        conversion = source.index("trimMinLenValue = params.trim_min_len.toString().toInteger()")
        comparison = source.index("if (trimMinLenValue < 1)")
        self.assertLess(conversion, comparison)
        self.assertNotIn("if (params.trim_min_len <", source)
        self.assertNotIn("if (params.consensus_min_freq <", source)
        self.assertNotIn("if (params.variant_min_freq <", source)
        self.assertIn("consensusMinFreqValue = params.consensus_min_freq.toString().toBigDecimal()", source)
        self.assertIn("variantMinFreqValue = params.variant_min_freq.toString().toBigDecimal()", source)

    def test_bwa_index_does_not_use_sample_publish_rule(self):
        config = (ROOT / "conf" / "modules.config").read_text(encoding="utf-8")
        self.assertNotIn("withName: 'ALIGN:.*'", config)
        selector = config.index("withName: 'ALIGN:BWA_INDEX'")
        next_selector = config.index("withName:", selector + 10)
        block = config[selector:next_selector]
        self.assertIn("enabled: false", block)
        self.assertNotIn("meta.vdir", block)

    def test_shared_bwa_index_is_broadcast_to_all_matching_samples(self):
        source = (ROOT / "subworkflows" / "local" / "align.nf").read_text(encoding="utf-8")
        self.assertIn(".combine(ch_indexes_keyed, by: 0)", source)
        self.assertNotIn(".join(ch_indexes_keyed)", source)

    def test_new_analysis_outputs_are_wired_into_dashboard(self):
        workflow = (ROOT / "main.nf").read_text(encoding="utf-8")
        module = (ROOT / "modules" / "local" / "dashboard.nf").read_text(encoding="utf-8")
        for channel in ("ch_dash_amplicon", "ch_dash_coding", "ch_dash_vcf"):
            self.assertIn(f".mix( {channel}.map", workflow)
        for option in ("--amplicon-dir", "--coding-qc-dir", "--vcf-dir"):
            self.assertIn(option, module)

    def test_new_python_processes_stage_their_helpers(self):
        expected = {
            "amplicon_coverage.nf": "python ${helper} --sample",
            "coding_qc.nf": "python ${helper} --sample",
            "variants_vcf.nf": "python ${helper}",
        }
        for filename, command in expected.items():
            with self.subTest(filename=filename):
                source = (ROOT / "modules" / "local" / filename).read_text(encoding="utf-8")
                self.assertIn("path helper", source)
                self.assertIn(command, source)
        workflow = (ROOT / "main.nf").read_text(encoding="utf-8")
        for helper in ("amplicon_coverage.py", "coding_qc.py", "ivar_tsv_to_vcf.py"):
            self.assertIn(f'file("$projectDir/bin/{helper}", checkIfExists: true)', workflow)

    def test_segment_qc_matches_depth_by_contig_name(self):
        module = load_script("consensus_qc.py")
        with tempfile.TemporaryDirectory(dir=ROOT / "tests") as directory:
            root = Path(directory)
            fasta = root / "consensus.fa"
            depth = root / "depth.tsv"
            output = root / "qc.tsv"
            # FASTA order is deliberately the opposite of the depth order.
            fasta.write_text(">S1|M\nNNNN\n>S1|L\nAAAA\n", encoding="utf-8")
            depth.write_text("L\t1\t30\nL\t2\t30\nL\t3\t30\nL\t4\t30\nM\t1\t0\nM\t2\t0\nM\t3\t0\nM\t4\t0\n", encoding="utf-8")
            run_main(module, "--sample", "S1", "--fasta", fasta, "--depth", depth,
                     "--min-depth", "20", "--out", output)
            with output.open(encoding="utf-8", newline="") as handle:
                rows = {row["segment"]: row for row in csv.DictReader(handle, delimiter="\t")}
            self.assertEqual(rows["L"]["n_bases"], "0")
            self.assertEqual(rows["M"]["n_bases"], "4")
            self.assertEqual(rows["L"]["breadth_ge_20x"], "1.0000")

    def test_mixed_sample_suffix_matches_base_metadata_id(self):
        module = load_script("make_metadata_xlsx.py")
        self.assertEqual(module.sample_code("260123-DENV1_S12_L001"), "260123")
        self.assertEqual(module.sample_code("260123-RSVA"), "260123")
        self.assertEqual(module.sample_code("ordinary-sample_S3"), "ordinary-sample")

    def test_ivar_tsv_conversion_produces_vcf(self):
        module = load_script("ivar_tsv_to_vcf.py")
        with tempfile.TemporaryDirectory(dir=ROOT / "tests") as directory:
            root = Path(directory)
            source = root / "variants.tsv"
            output = root / "variants.vcf"
            source.write_text(
                "REGION\tPOS\tREF\tALT\tALT_FREQ\tTOTAL_DP\tALT_DP\tALT_QUAL\tPASS\taa_change\n"
                "NC_1\t10\tA\tG\t0.31\t100\t31\t35\tTRUE\tE:K4R\n",
                encoding="utf-8",
            )
            run_main(module, "--input", source, "--output", output, "--source", "test")
            text = output.read_text(encoding="utf-8")
            self.assertIn("##fileformat=VCFv4.2", text)
            self.assertIn("NC_1\t10\t.\tA\tG\t35\tPASS\tDP=100;AF=0.31;AD=31;AA_CHANGE=E:K4R", text)

    def test_amplicon_dropout_and_coding_qc(self):
        coverage = load_script("amplicon_coverage.py")
        coding = load_script("coding_qc.py")
        with tempfile.TemporaryDirectory(dir=ROOT / "tests") as directory:
            root = Path(directory)
            bed, depth, cov_out = root / "primers.bed", root / "depth.tsv", root / "coverage.tsv"
            bed.write_text("ref\t0\t2\tamp1_LEFT\nref\t8\t10\tamp1_RIGHT\n", encoding="utf-8")
            depth.write_text("".join(f"ref\t{i}\t{30 if i < 6 else 0}\n" for i in range(1, 11)), encoding="utf-8")
            run_main(coverage, "--sample", "S1", "--bed", bed, "--depth", depth,
                     "--min-depth", "20", "--min-breadth", "0.9", "--out", cov_out)
            with cov_out.open(encoding="utf-8", newline="") as handle:
                cov = next(csv.DictReader(handle, delimiter="\t"))
            self.assertEqual(cov["amplicon"], "amp1")
            self.assertEqual(cov["dropout"], "YES")

            fasta, gff, coding_out = root / "consensus.fa", root / "annotation.gff3", root / "coding.tsv"
            fasta.write_text(">S1|ref\nATGTAGAAA\n", encoding="utf-8")
            gff.write_text("ref\ttest\tCDS\t1\t9\t.\t+\t0\tID=gene1\n", encoding="utf-8")
            run_main(coding, "--sample", "S1", "--fasta", fasta, "--gff", gff, "--out", coding_out)
            with coding_out.open(encoding="utf-8", newline="") as handle:
                qc = next(csv.DictReader(handle, delimiter="\t"))
            self.assertEqual(qc["cds_length_not_multiple_of_3"], "NO")
            self.assertEqual(qc["internal_stop_count"], "1")

    def test_blast_failure_is_visible_in_summary(self):
        module = load_script("blast_summary.py")
        with tempfile.TemporaryDirectory(dir=ROOT / "tests") as directory:
            root = Path(directory)
            raw, status, output = root / "raw.tsv", root / "status.tsv", root / "summary.tsv"
            raw.write_text("", encoding="utf-8")
            status.write_text("status\tmessage\nBLAST_FAILED\tdatabase unavailable\n", encoding="utf-8")
            run_main(module, "--raw", raw, "--status", status, "--out", output)
            with output.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle, delimiter="\t"))
            self.assertEqual(rows[0]["sample"], "__BLAST_STATUS__")
            self.assertEqual(rows[0]["blast_status"], "BLAST_FAILED")

    def test_blast_follows_nextflow_staged_consensus_symlinks(self):
        blast_id = (ROOT / "modules" / "local" / "blast_id.nf").read_text(encoding="utf-8")
        self.assertIn("find -L consensus", blast_id)
        self.assertNotIn("find consensus -maxdepth 1 -type f", blast_id)
        for filename in ("blast_id.nf", "blast_summary.nf", "blast_db.nf"):
            source = (ROOT / "modules" / "local" / filename).read_text(encoding="utf-8")
            self.assertNotIn("cat <<-END_VERSIONS", source)

    def test_amplicon_coverage_matches_accession_with_or_without_version(self):
        coverage = load_script("amplicon_coverage.py")
        with tempfile.TemporaryDirectory(dir=ROOT / "tests") as directory:
            root = Path(directory)
            bed, depth, output = root / "primers.bed", root / "depth.tsv", root / "coverage.tsv"
            bed.write_text(
                "NC_001477\t0\t2\tDENV1_1_LEFT\n"
                "NC_001477\t8\t10\tDENV1_1_RIGHT\n",
                encoding="utf-8",
            )
            depth.write_text(
                "".join(f"NC_001477.1\t{i}\t30\n" for i in range(1, 11)),
                encoding="utf-8",
            )
            run_main(coverage, "--sample", "DENV1", "--bed", bed, "--depth", depth,
                     "--min-depth", "20", "--min-breadth", "0.9", "--out", output)
            with output.open(encoding="utf-8", newline="") as handle:
                row = next(csv.DictReader(handle, delimiter="\t"))
            self.assertEqual(row["mean_depth"], "30.00")
            self.assertEqual(row["breadth_ge_min_depth"], "1.0000")
            self.assertEqual(row["dropout"], "NO")

    def test_isnv_filters_frequency_depth_quality_and_strand_support(self):
        module = load_script("isnv_filter.py")
        with tempfile.TemporaryDirectory(dir=ROOT / "tests") as directory:
            root = Path(directory)
            source, output = root / "raw.tsv", root / "isnv.tsv"
            source.write_text(
                "REGION\tPOS\tREF\tALT\tTOTAL_DP\tALT_DP\tALT_RV\tALT_FREQ\tALT_QUAL\n"
                "ref\t10\tA\tG\t200\t30\t14\t0.15\t35\n"
                "ref\t20\tC\tT\t80\t5\t0\t0.0625\t15\n",
                encoding="utf-8",
            )
            run_main(module, "--sample", "S1", "--input", source, "--output", output)
            with output.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle, delimiter="\t"))
            self.assertEqual(rows[0]["status"], "PASS")
            self.assertEqual(rows[0]["filter_reasons"], "-")
            self.assertEqual(rows[1]["status"], "REVIEW")
            self.assertIn("LOW_DEPTH", rows[1]["filter_reasons"])
            self.assertIn("STRAND_BIAS", rows[1]["filter_reasons"])

    def test_snpeff_summary_parses_multiple_ann_effects(self):
        module = load_script("snpeff_summary.py")
        with tempfile.TemporaryDirectory(dir=ROOT / "tests") as directory:
            root = Path(directory)
            vcf, output = root / "annotated.vcf", root / "summary.tsv"
            vcf.write_text(
                "##fileformat=VCFv4.2\n#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
                "ref\t42\t.\tA\tG\t35\tPASS\tANN=G|missense_variant|MODERATE|E1|gene1|transcript|tx1||||p.Lys14Arg|||||\n",
                encoding="utf-8",
            )
            run_main(module, "--sample", "S1", "--vcf", vcf, "--output", output)
            with output.open(newline="", encoding="utf-8") as handle:
                row = next(csv.DictReader(handle, delimiter="\t"))
            self.assertEqual(row["effect"], "missense_variant")
            self.assertEqual(row["impact"], "MODERATE")
            self.assertEqual(row["status"], "OK")

            recovered = root / "summary_recovered.tsv"
            run_main(
                module, "--sample", "S1", "--vcf", vcf, "--output", recovered,
                "--status", "SNPSIFT_FAILED",
                "--message", "SnpSift filtering failed; unfiltered SnpEff VCF retained",
            )
            with recovered.open(newline="", encoding="utf-8") as handle:
                recovered_row = next(csv.DictReader(handle, delimiter="\t"))
            self.assertEqual(recovered_row["effect"], "missense_variant")
            self.assertEqual(recovered_row["status"], "SNPSIFT_FAILED")
            self.assertIn("unfiltered SnpEff VCF retained", recovered_row["message"])

    def test_snpeff_and_snpsift_use_dedicated_reproducible_containers(self):
        source = (ROOT / "modules/local/snpeff.nf").read_text(encoding="utf-8")
        main = (ROOT / "main.nf").read_text(encoding="utf-8")
        config = (ROOT / "conf/modules.config").read_text(encoding="utf-8")
        self.assertIn("process SNPEFF_ANNOTATE", source)
        self.assertIn("snpeff:5.2--hdfd78af_0", source)
        self.assertIn("process SNPSIFT_FILTER", source)
        self.assertIn("snpsift:5.2--hdfd78af_0", source)
        self.assertIn('SnpSift filter', source)
        self.assertIn("SNPSIFT_FILTER.out.tsv", main)
        self.assertIn("withName: 'SNPSIFT_FILTER'", config)

    def test_windows_and_ubuntu_installers_share_release_and_self_test_contract(self):
        windows = (ROOT / "windows-launcher" / "bootstrap-wsl.sh").read_text(encoding="utf-8")
        linux = (ROOT / "linux-launcher" / "bootstrap-linux.sh").read_text(encoding="utf-8")
        for expected in (
            'RELEASE_REF="${MKVA_RELEASE_REF:-v1.2.5}"',
            'RELEASE_REVISION="${MKVA_RELEASE_REVISION:-feature-parity-2026-10-13}"',
            'NF_TEST_VERSION="${MKVA_NF_TEST_VERSION:-0.9.5}"',
            "https://get.nf-test.com",
            'MKVA_NF_TEST="$NF_TEST_BIN"',
        ):
            self.assertIn(expected, windows)
            self.assertIn(expected, linux)

    def test_windows_installer_pins_and_exposes_nf_test(self):
        bootstrap = (ROOT / "windows-launcher" / "bootstrap-wsl.sh").read_text(encoding="utf-8")
        start = (ROOT / "webtool" / "start-local.sh").read_text(encoding="utf-8")
        verify = (ROOT / "webtool" / "verify-install.sh").read_text(encoding="utf-8")
        launcher = (ROOT / "windows-launcher" / "launcher" / "Program.cs").read_text(encoding="utf-8")
        self.assertIn('NF_TEST_VERSION="${MKVA_NF_TEST_VERSION:-0.9.5}"', bootstrap)
        self.assertIn("https://get.nf-test.com", bootstrap)
        self.assertIn('MKVA_NF_TEST="$NF_TEST_BIN"', bootstrap)
        self.assertIn('export MKVA_NF_TEST="$PROJECT_DIR/tools/nf-test"', start)
        self.assertIn('"$NF_TEST" version', verify)
        self.assertIn('$PROJECT/tools/nf-test', launcher)


    def test_pipeline_uses_only_user_supplied_reference(self):
        main = (ROOT / "main.nf").read_text(encoding="utf-8")
        config = (ROOT / "nextflow.config").read_text(encoding="utf-8")
        schema = (ROOT / "nextflow_schema.json").read_text(encoding="utf-8")
        webtool = (ROOT / "webtool" / "local_api.py").read_text(encoding="utf-8")
        combined = "\n".join((main, config, schema, webtool))
        for discarded in ("reference_mode", "reference_panel", "primer_scheme",
                          "REFERENCE_SELECT", "CONSENSUS_SELECT", "ALIGN_AUTO"):
            self.assertNotIn(discarded, combined)
        self.assertIn("ch_consensus_final = IVAR_CONSENSUS.out.consensus", main)
        self.assertIn("ch_bam_final = ch_bam_manual_final", main)
        self.assertIn('cmd.extend(["--reference", normalized["reference"]', webtool)

    def test_metadata_export_requires_consensus_qc_and_uses_fixed_slots(self):
        source = (ROOT / "main.nf").read_text(encoding="utf-8")
        self.assertIn("ch_meta_tagged = ch_meta_qc.map", source)
        self.assertIn("[vdir, 'qc', files]", source)
        self.assertIn(".groupTuple(by: 0)", source)
        self.assertIn(".filter { row -> row[1] }", source)
        self.assertIn("slots = [qc: [], reads: [], nextclade: [], blast: []]", source)

    def test_dashboard_aggregation_uses_fixed_width_tagged_rows(self):
        main = (ROOT / "main.nf").read_text(encoding="utf-8")
        self.assertIn("ch_dash_tagged = ch_dash_qc.map", main)
        self.assertIn(".groupTuple(by: 0)", main)
        self.assertIn("validation_krona: []", main)
        self.assertIn("slots.snpeff, slots.iterative", main)
        self.assertNotIn("ch_dash_in = ch_dash_qc\n            .join", main)

if __name__ == "__main__":
    unittest.main()
