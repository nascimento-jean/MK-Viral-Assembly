import csv
import json
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import local_api


class MetadataTemplateTests(unittest.TestCase):
    def test_all_metadata_templates_are_packaged(self):
        self.assertEqual(set(local_api.METADATA_TEMPLATES), {"xlsx", "csv", "tsv"})
        for path, content_type in local_api.METADATA_TEMPLATES.values():
            self.assertTrue(path.is_file(), path)
            self.assertGreater(path.stat().st_size, 100)
            self.assertTrue(content_type)


class BuildCommandTests(unittest.TestCase):
    def setUp(self):
        self.nextflow_patch = patch.object(local_api, "NEXTFLOW", Path(sys.executable))
        self.nextflow_patch.start()
        self.addCleanup(self.nextflow_patch.stop)

    def base_payload(self, root: Path) -> dict:
        return {
            "run_name": "webtool_test",
            "virus": "Dengue",
            "profile": "singularity",
            "outdir": str(root / "results"),
            "metadata": "",
            "kraken": False,
            "kraken_db": "",
            "deplete": False,
            "nextclade": True,
            "nextclade_dataset": "denv4",
            "blast": True,
            "min_cov": 20,
            "min_freq": 0.75,
            "min_qual": 20,
            "min_map_qual": 20,
            "max_cpus": 2,
            "max_memory": 8,
        }

    def test_single_adds_optional_bed_and_gff(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reads = root / "reads"
            reads.mkdir()
            reference = root / "reference.fasta"
            primer_bed = root / "primers.bed"
            gff = root / "annotation.gff3"
            reference.write_text(">ref\nA\n", encoding="utf-8")
            primer_bed.write_text("ref\t0\t1\n", encoding="utf-8")
            gff.write_text("##gff-version 3\n", encoding="utf-8")
            payload = self.base_payload(root) | {
                "input_mode": "single",
                "raw_data_dir": str(reads),
                "reference": str(reference),
                "primer_bed": str(primer_bed),
                "gff": str(gff),
            }
            command, normalized = local_api.build_command(payload)
            self.assertIn("--primer_bed", command)
            self.assertIn(str(primer_bed), command)
            self.assertIn("--gff", command)
            self.assertIn(str(gff), command)
            self.assertIn("--nextclade_dataset", command)
            self.assertIn("denv4", command)
            self.assertEqual(normalized["primer_bed"], str(primer_bed))
            self.assertEqual(normalized["gff"], str(gff))
            self.assertEqual(normalized["nextclade_dataset"], "denv4")

    def test_mixed_ignores_global_bed_and_gff(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            samplesheet = root / "samplesheet.csv"
            samplesheet.write_text("sample,fastq_1,fastq_2,virus,reference,gff,bed_file\n", encoding="utf-8")
            payload = self.base_payload(root) | {
                "input_mode": "mixed",
                "samplesheet": str(samplesheet),
                "primer_bed": "/ignored/global.bed",
                "gff": "/ignored/global.gff3",
                "nextclade_dataset": "denv4",
            }
            command, normalized = local_api.build_command(payload)
            self.assertNotIn("--primer_bed", command)
            self.assertNotIn("--gff", command)
            self.assertNotIn("--nextclade_dataset", command)
            self.assertEqual(normalized["primer_bed"], "")
            self.assertEqual(normalized["gff"], "")
            self.assertEqual(normalized["virus"], "Mixed viruses")
            self.assertEqual(normalized["nextclade_dataset"], "")

    def test_single_requires_dataset_when_nextclade_is_enabled(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reads = root / "reads"
            reads.mkdir()
            reference = root / "reference.fasta"
            reference.write_text(">ref\nA\n", encoding="utf-8")
            payload = self.base_payload(root) | {
                "input_mode": "single",
                "raw_data_dir": str(reads),
                "reference": str(reference),
                "nextclade_dataset": "",
            }
            with self.assertRaisesRegex(ValueError, "Dataset Nextclade é obrigatório"):
                local_api.build_command(payload)

    def test_metadata_accepts_xlsx_csv_and_tsv(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reads = root / "reads"
            reads.mkdir()
            reference = root / "reference.fasta"
            reference.write_text(">ref\nA\n", encoding="utf-8")
            base = self.base_payload(root) | {
                "input_mode": "single",
                "raw_data_dir": str(reads),
                "reference": str(reference),
            }
            for suffix in (".xlsx", ".csv", ".tsv"):
                metadata = root / f"metadata{suffix}"
                metadata.write_bytes(b"template")
                command, normalized = local_api.build_command(base | {"metadata": str(metadata)})
                self.assertIn("--metadata", command)
                self.assertEqual(normalized["metadata"], str(metadata))
            invalid = root / "metadata.txt"
            invalid.write_text("Código Amostra\nSAMPLE01\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "XLSX, CSV ou TSV"):
                local_api.build_command(base | {"metadata": str(invalid)})

    def test_single_allows_empty_dataset_when_nextclade_is_disabled(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reads = root / "reads"
            reads.mkdir()
            reference = root / "reference.fasta"
            reference.write_text(">ref\nA\n", encoding="utf-8")
            payload = self.base_payload(root) | {
                "input_mode": "single",
                "raw_data_dir": str(reads),
                "reference": str(reference),
                "nextclade": False,
                "nextclade_dataset": "",
            }
            command, normalized = local_api.build_command(payload)
            self.assertNotIn("--nextclade_dataset", command)
            self.assertEqual(normalized["nextclade_dataset"], "")



class SamplesheetGenerationTests(unittest.TestCase):
    def test_generates_samplesheet_with_internal_catalog_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            parent = root / "run17"
            virus_dir = parent / "chikv"
            virus_dir.mkdir(parents=True)
            (virus_dir / "sample01_R1.fastq.gz").write_bytes(b"")
            (virus_dir / "sample01_R2.fastq.gz").write_bytes(b"")
            catalog = root / "virus_catalog.tsv"
            catalog.write_text(
                "virus\treference\tgff\tbed_file\tnextclade_dataset\n"
                "chikv\t/refs/chikv.fa\t/refs/chikv.gff3\t/refs/chikv.bed\tchikv\n",
                encoding="utf-8",
            )
            output = root / "samplesheet_run17.csv"

            with patch.object(local_api, "VIRUS_CATALOG", catalog):
                result = local_api.generate_samplesheet({"parent": str(parent), "output": str(output)})

            self.assertEqual(result["path"], str(output.resolve()))
            self.assertEqual(result["samples"], 1)
            self.assertEqual(result["viruses"], {"chikv": 1})
            with output.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(rows[0]["sample"], "sample01")
            self.assertEqual(rows[0]["virus"], "chikv")
            self.assertEqual(rows[0]["reference"], "/refs/chikv.fa")
            self.assertEqual(rows[0]["nextclade_dataset"], "chikv")
            self.assertEqual(rows[0]["fastq_1"], str((virus_dir / "sample01_R1.fastq.gz").resolve()))
            self.assertEqual(rows[0]["fastq_2"], str((virus_dir / "sample01_R2.fastq.gz").resolve()))

    def test_rejects_non_csv_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(ValueError, "extensão .csv"):
                local_api.generate_samplesheet({"parent": str(root), "output": str(root / "samplesheet.txt")})


class PathConversionTests(unittest.TestCase):
    def test_converts_windows_drive_path_to_wsl(self):
        self.assertEqual(
            local_api.windows_to_wsl_path(r"D:\Dados Brutos\DENV\reads"),
            "/mnt/d/Dados Brutos/DENV/reads",
        )

    def test_converts_wsl_unc_path_to_linux(self):
        self.assertEqual(
            local_api.windows_to_wsl_path(r"\\wsl.localhost\Ubuntu-22.04\home\researcher\data"),
            "/home/researcher/data",
        )

    def test_rejects_unknown_picker(self):
        with self.assertRaisesRegex(ValueError, "não permitido"):
            local_api.pick_local_path({"picker": "arbitrary"})

    def test_windows_picker_uses_launcher_bridge(self):
        with tempfile.TemporaryDirectory() as directory:
            bridge = Path(directory)
            (bridge / "heartbeat").touch()
            observed = {}

            def respond():
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    requests = list(bridge.glob("request-*.json"))
                    if requests:
                        request = json.loads(requests[0].read_text(encoding="utf-8"))
                        observed.update(request)
                        response = bridge / f"response-{request['id']}.json"
                        response.write_text(
                            json.dumps({"cancelled": False, "path": r"D:\Dados\DENV"}),
                            encoding="utf-8",
                        )
                        return
                    time.sleep(0.01)
                raise AssertionError("bridge request was not created")

            worker = threading.Thread(target=respond)
            worker.start()
            with patch.object(local_api, "PICKER_BRIDGE_DIR", bridge), \
                 patch.object(local_api, "RUNNING_IN_WSL", True):
                result = local_api.pick_local_path({"picker": "fastq_dir", "current": ""})
            worker.join(timeout=5)

        self.assertFalse(worker.is_alive())
        self.assertEqual(result["path"], "/mnt/d/Dados/DENV")
        self.assertEqual(observed["mode"], "folder")
        self.assertEqual(observed["title"], "Selecione a pasta com os FASTQ.GZ")

    def test_windows_picker_preserves_bridge_cancellation(self):
        with tempfile.TemporaryDirectory() as directory:
            bridge = Path(directory)
            (bridge / "heartbeat").touch()

            def respond():
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    requests = list(bridge.glob("request-*.json"))
                    if requests:
                        request = json.loads(requests[0].read_text(encoding="utf-8"))
                        (bridge / f"response-{request['id']}.json").write_text(
                            json.dumps({"cancelled": True, "path": ""}),
                            encoding="utf-8",
                        )
                        return
                    time.sleep(0.01)

            worker = threading.Thread(target=respond)
            worker.start()
            with patch.object(local_api, "PICKER_BRIDGE_DIR", bridge), \
                 patch.object(local_api, "RUNNING_IN_WSL", True):
                result = local_api.pick_local_path({"picker": "reference", "current": ""})
            worker.join(timeout=5)

        self.assertEqual(result, {"cancelled": True, "path": ""})

    def test_windows_picker_rejects_stale_launcher_bridge(self):
        with tempfile.TemporaryDirectory() as directory:
            bridge = Path(directory)
            heartbeat = bridge / "heartbeat"
            heartbeat.touch()
            with patch.object(local_api, "PICKER_BRIDGE_DIR", bridge),                  patch.object(local_api.time, "time", return_value=heartbeat.stat().st_mtime + 10):
                with self.assertRaisesRegex(ValueError, "abra-o novamente pelo menu Iniciar"):
                    local_api.pick_local_path({"picker": "fastq_dir", "current": ""})

    def test_wsl_without_launcher_bridge_has_clear_error(self):
        with patch.object(local_api, "PICKER_BRIDGE_DIR", None), \
             patch.object(local_api, "RUNNING_IN_WSL", True):
            with self.assertRaisesRegex(ValueError, "abra-o novamente pelo menu Iniciar"):
                local_api.pick_local_path({"picker": "fastq_dir", "current": ""})

    def test_linux_folder_picker_uses_zenity(self):
        completed = subprocess.CompletedProcess([], 0, stdout="/home/researcher/reads\n", stderr="")
        with patch.object(local_api, "PICKER_BRIDGE_DIR", None), \
             patch.object(local_api, "RUNNING_IN_WSL", False), \
             patch.object(local_api, "LINUX_ZENITY", "/usr/bin/zenity"), \
             patch.object(local_api.subprocess, "run", return_value=completed) as run:
            result = local_api.pick_local_path({"picker": "fastq_dir", "current": "/home/researcher"})

        self.assertEqual(result["path"], "/home/researcher/reads")
        command = run.call_args.args[0]
        self.assertIn("--file-selection", command)
        self.assertIn("--directory", command)
        self.assertIn("--title=Selecione a pasta com os FASTQ.GZ", command)

    def test_linux_save_picker_preserves_cancellation(self):
        completed = subprocess.CompletedProcess([], 1, stdout="", stderr="")
        with patch.object(local_api, "PICKER_BRIDGE_DIR", None), \
             patch.object(local_api, "RUNNING_IN_WSL", False), \
             patch.object(local_api, "LINUX_ZENITY", "/usr/bin/zenity"), \
             patch.object(local_api.subprocess, "run", return_value=completed):
            result = local_api.pick_local_path({"picker": "samplesheet_output", "current": ""})

        self.assertEqual(result, {"cancelled": True, "path": ""})

    def test_linux_file_picker_translates_filters(self):
        completed = subprocess.CompletedProcess([], 0, stdout="/home/researcher/ref.fasta\n", stderr="")
        with patch.object(local_api, "PICKER_BRIDGE_DIR", None), \
             patch.object(local_api, "RUNNING_IN_WSL", False), \
             patch.object(local_api, "LINUX_ZENITY", "/usr/bin/zenity"), \
             patch.object(local_api.subprocess, "run", return_value=completed) as run:
            result = local_api.pick_local_path({"picker": "reference", "current": ""})

        self.assertEqual(result["linux_path"], "/home/researcher/ref.fasta")
        command = run.call_args.args[0]
        self.assertTrue(any(item.startswith("--file-filter=") for item in command))
        self.assertIn("*.fasta", " ".join(command))

class ResultDiscoveryTests(unittest.TestCase):
    def test_discovers_only_real_artifacts_and_sample_metrics(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "dengue" / "consensus").mkdir(parents=True)
            (root / "dengue" / "read_stats").mkdir()
            (root / "dengue" / "consensus_qc").mkdir()
            (root / "dengue" / "blast").mkdir()
            (root / "dengue" / "gisaid").mkdir()
            (root / "multiqc").mkdir()
            (root / "dengue" / "dengue_dashboard.html").write_text("<html></html>", encoding="utf-8")
            (root / "dengue" / "consensus" / "sample.consensus.fa").write_text(">sample\nACGT\n", encoding="utf-8")
            (root / "multiqc" / "multiqc_report.html").write_text("<html></html>", encoding="utf-8")
            (root / "dengue" / "gisaid" / "dengue_GISAID_submission.xls").write_bytes(b"xls")
            (root / "dengue" / "gisaid" / "dengue_GISAID_submission.fasta").write_text(">sample\nACGT\n", encoding="utf-8")
            (root / "dengue" / "read_stats" / "sample.read_stats.tsv").write_text(
                "sample\treads_raw\treads_post_fastp\treads_post_deplete\nSAMPLE01\t42444\t42000\t41900\n", encoding="utf-8")
            (root / "dengue" / "consensus_qc" / "sample.consensus_qc.tsv").write_text(
                "sample\tsegment\tbreadth_ge_20x\tmean_depth\nSAMPLE01\tALL\t0.856\t393.95\n", encoding="utf-8")
            (root / "dengue" / "blast" / "blast_summary.tsv").write_text(
                "sample\tbest_hit_species\nSAMPLE01\tDengue virus 3\n", encoding="utf-8")
            job = {"id": "MKVA-TEST", "name": "test_run", "virus": "Dengue",
                   "status": "Concluída", "outdir": str(root)}

            manifest = {item["key"]: item for item in local_api.artifact_manifest(job)}
            self.assertTrue(manifest["dashboard"]["available"])
            self.assertTrue(manifest["consensus"]["available"])
            self.assertTrue(manifest["quality"]["available"])
            self.assertFalse(manifest["metadata"]["available"])
            self.assertTrue(manifest["gisaid"]["available"])
            self.assertEqual(manifest["gisaid"]["count"], 2)
            self.assertFalse(manifest["variants"]["available"])

            samples = local_api.sample_records(job)
            self.assertEqual(len(samples), 1)
            self.assertEqual(samples[0]["sample"], "SAMPLE01")
            self.assertEqual(samples[0]["virus"], "DENV3")
            self.assertEqual(samples[0]["reads"], "42444")
            self.assertEqual(samples[0]["depth"], "393.95")
            self.assertEqual(samples[0]["coverage"], "85.60")


class DashboardLinkTests(unittest.TestCase):
    def test_rewrites_and_resolves_nested_krona_links(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dashboard = root / "chikv" / "chikv_dashboard.html"
            krona = root / "chikv" / "krona" / "krona.html"
            krona.parent.mkdir(parents=True)
            dashboard.write_text('<a href="krona/krona.html">Krona</a><iframe src="krona/krona.html"></iframe>', encoding="utf-8")
            krona.write_text("<html><title>Krona</title></html>", encoding="utf-8")
            job = {"id": "MKVA-TEST", "outdir": str(root)}

            rewritten = local_api.rewrite_dashboard_links(job, dashboard, dashboard.read_text(encoding="utf-8"))
            expected = "http://127.0.0.1:8787/api/jobs/MKVA-TEST/files/chikv/krona/krona.html"
            self.assertEqual(rewritten.count(expected), 2)
            self.assertEqual(local_api.resolve_job_file(job, "chikv/krona/krona.html"), krona.resolve())

    def test_rejects_result_path_traversal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "results"
            root.mkdir()
            outside = root.parent / "outside.html"
            outside.write_text("outside", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "não encontrado"):
                local_api.resolve_job_file({"id": "MKVA-TEST", "outdir": str(root)}, "../outside.html")


class QueueTests(unittest.TestCase):
    @staticmethod
    def normalized(root: Path, name: str) -> dict:
        return {"name": name, "virus": "Dengue", "outdir": str(root / name)}

    def test_second_job_waits_without_starting_another_process(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            logs = root / "logs"
            logs.mkdir()
            state = root / "jobs.json"
            jobs: list[dict] = []
            processes: dict = {}
            running = Mock(pid=101)
            running.poll.return_value = None

            def build(payload):
                name = payload["run_name"]
                return ["nextflow", name], self.normalized(root, name)

            with patch.object(local_api, "JOBS", jobs), patch.object(local_api, "PROCESSES", processes), \
                 patch.object(local_api, "STATE_FILE", state), patch.object(local_api, "LOG_DIR", logs), \
                 patch.object(local_api, "build_command", side_effect=build), \
                 patch.object(local_api.subprocess, "Popen", return_value=running) as popen, \
                 patch.object(local_api.threading, "Thread") as thread:
                first = local_api.start_job({"run_name": "first"})
                second = local_api.start_job({"run_name": "second"})
                second_public = local_api.public_job(second)

            popen.call_args.kwargs["stdout"].close()
            self.assertEqual(first["status"], "Executando")
            self.assertEqual(second["status"], "Na fila")
            self.assertEqual(second_public["queue_position"], 1)
            self.assertEqual(popen.call_count, 1)
            thread.return_value.start.assert_called_once()

    def test_start_job_recreates_missing_runtime_and_log_directories(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = root / ".local-data"
            logs = data / "logs"
            state = data / "jobs.json"
            jobs: list[dict] = []
            processes: dict = {}
            running = Mock(pid=303)
            running.poll.return_value = None

            def build(payload):
                return ["nextflow", payload["run_name"]], self.normalized(root, payload["run_name"])

            with patch.object(local_api, "JOBS", jobs), patch.object(local_api, "PROCESSES", processes), \
                 patch.object(local_api, "DATA_DIR", data), patch.object(local_api, "LOG_DIR", logs), \
                 patch.object(local_api, "STATE_FILE", state), \
                 patch.object(local_api, "build_command", side_effect=build), \
                 patch.object(local_api.subprocess, "Popen", return_value=running) as popen, \
                 patch.object(local_api.threading, "Thread"):
                job = local_api.start_job({"run_name": "runtime-recovery"})

            popen.call_args.kwargs["stdout"].close()
            self.assertTrue(data.is_dir())
            self.assertTrue(logs.is_dir())
            self.assertTrue(Path(job["log"]).is_file())
            self.assertTrue(state.is_file())
            self.assertEqual(job["status"], "Executando")

    def test_completion_dispatches_oldest_queued_job(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            logs = root / "logs"
            logs.mkdir()
            state = root / "jobs.json"
            current_log = (logs / "active.log").open("w", encoding="utf-8")
            queued_log = logs / "queued.log"
            queued_log.touch()
            active = {
                "id": "ACTIVE", "name": "active", "status": "Executando",
                "created_at": "2026-01-01T00:00:00+00:00", "log": str(logs / "active.log"),
            }
            queued = {
                "id": "QUEUED", "name": "queued", "status": "Na fila",
                "created_at": "2026-01-01T00:01:00+00:00", "log": str(queued_log),
                "command": ["nextflow", "queued"], "outdir": str(root / "queued"),
            }
            current = Mock(pid=101)
            current.wait.return_value = 0
            next_process = Mock(pid=202)
            next_process.poll.return_value = None
            jobs = [queued, active]
            processes = {"ACTIVE": current}

            with patch.object(local_api, "JOBS", jobs), patch.object(local_api, "PROCESSES", processes), \
                 patch.object(local_api, "STATE_FILE", state), \
                 patch.object(local_api.subprocess, "Popen", return_value=next_process) as popen, \
                 patch.object(local_api.threading, "Thread") as thread:
                local_api.monitor("ACTIVE", current, current_log)

            popen.call_args.kwargs["stdout"].close()
            self.assertEqual(active["status"], "Concluída")
            self.assertEqual(queued["status"], "Executando")
            self.assertEqual(queued["pid"], 202)
            self.assertIn("QUEUED", processes)
            self.assertNotIn("ACTIVE", processes)
            popen.assert_called_once()
            thread.return_value.start.assert_called_once()

    def test_cancel_queued_job_without_signalling_active_process(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "jobs.json"
            queued = {"id": "QUEUED", "status": "Na fila", "created_at": "2026-01-01T00:00:00+00:00"}
            jobs = [queued]
            with patch.object(local_api, "JOBS", jobs), patch.object(local_api, "PROCESSES", {}), \
                 patch.object(local_api, "STATE_FILE", state), patch.object(local_api.os, "killpg") as killpg:
                result = local_api.cancel_job("QUEUED")

            self.assertEqual(result["status"], "Cancelada")
            self.assertIsNone(local_api.public_job(result)["queue_position"])
            killpg.assert_not_called()

    def test_load_jobs_preserves_queue_and_marks_only_running_job_interrupted(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "jobs.json"
            state.write_text(json.dumps([
                {"id": "QUEUED", "status": "Na fila", "created_at": "2026-01-01T00:01:00+00:00"},
                {"id": "ACTIVE", "status": "Executando", "created_at": "2026-01-01T00:00:00+00:00", "log": ""},
            ]), encoding="utf-8")
            with patch.object(local_api, "STATE_FILE", state):
                loaded = local_api.load_jobs()

            self.assertEqual(loaded[0]["status"], "Na fila")
            self.assertEqual(loaded[1]["status"], "Interrompida")


class DeleteJobTests(unittest.TestCase):
    def test_deletes_history_and_log_but_preserves_results(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            logs = root / "logs"
            logs.mkdir()
            state = root / "jobs.json"
            result = root / "results" / "consensus.fa"
            result.parent.mkdir()
            result.write_text(">sample\nACGT\n", encoding="utf-8")
            log = logs / "MKVA-TEST.log"
            log.write_text("finished", encoding="utf-8")
            jobs = [{"id": "MKVA-TEST", "status": "Concluída", "log": str(log), "outdir": str(result.parent)}]

            with patch.object(local_api, "JOBS", jobs), patch.object(local_api, "PROCESSES", {}), patch.object(local_api, "STATE_FILE", state), patch.object(local_api, "LOG_DIR", logs):
                response = local_api.delete_job("MKVA-TEST")

            self.assertTrue(response["deleted"])
            self.assertTrue(response["results_preserved"])
            self.assertEqual(jobs, [])
            self.assertEqual(json.loads(state.read_text(encoding="utf-8")), [])
            self.assertFalse(log.exists())
            self.assertTrue(result.exists())

    def test_rejects_deleting_active_job(self):
        jobs = [{"id": "MKVA-ACTIVE", "status": "Executando", "log": "", "outdir": "/tmp/results"}]
        with patch.object(local_api, "JOBS", jobs), patch.object(local_api, "PROCESSES", {}):
            with self.assertRaisesRegex(ValueError, "Pare a análise"):
                local_api.delete_job("MKVA-ACTIVE")
        self.assertEqual(len(jobs), 1)


if __name__ == "__main__":
    unittest.main()
