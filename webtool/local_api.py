#!/usr/bin/env python3
"""Local-only API for the MK-Viral-Assembly webtool.

Binds to 127.0.0.1, validates known parameters, and starts Nextflow without a
shell. This intentionally accepts filesystem paths instead of browser uploads so
large FASTQ files are not duplicated.
"""
from __future__ import annotations

import base64
import csv
import io
import json
import mimetypes
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import uuid
import zipfile
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urlparse

HOST = "127.0.0.1"
PORT = int(os.environ.get("MKVA_WEBTOOL_PORT", "8787"))
WEBTOOL_DIR = Path(__file__).resolve().parent
PROJECT_DIR = WEBTOOL_DIR.parent
DATA_DIR = WEBTOOL_DIR / ".local-data"
LOG_DIR = DATA_DIR / "logs"
STATE_FILE = DATA_DIR / "jobs.json"
SAMPLESHEET_SCRIPT = PROJECT_DIR / "bin" / "make_samplesheet.py"
VIRUS_CATALOG = PROJECT_DIR / "assets" / "virus_catalog.tsv"
NEXTFLOW = Path(os.environ.get("MKVA_NEXTFLOW") or shutil.which("nextflow") or "nextflow")
JAVA_CMD = os.environ.get("MKVA_JAVA") or shutil.which("java") or "java"
ALLOWED_PROFILES = {"singularity", "docker", "conda", "mamba", "standalone"}
DEFAULT_PROFILE = os.environ.get("MKVA_DEFAULT_PROFILE", "singularity")
if DEFAULT_PROFILE not in ALLOWED_PROFILES:
    DEFAULT_PROFILE = "singularity"
ALLOWED_INPUT_MODES = {"single", "mixed"}
LOCK = threading.Lock()
PROCESSES: dict[str, subprocess.Popen[str]] = {}

DATA_DIR.mkdir(exist_ok=True)
LOG_DIR.mkdir(exist_ok=True)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def clean_text(value: Any, field: str, required: bool = False) -> str:
    text = str(value or "").strip()
    if required and not text:
        raise ValueError(f"{field} é obrigatório")
    if any(char in text for char in ("\x00", "\n", "\r")):
        raise ValueError(f"{field} contém caracteres inválidos")
    return text


def number(value: Any, field: str, minimum: float, maximum: float, integer: bool = False) -> float | int:
    try:
        parsed = int(value) if integer else float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field} deve ser numérico") from None
    if parsed < minimum or parsed > maximum:
        raise ValueError(f"{field} deve estar entre {minimum} e {maximum}")
    return parsed


def local_path(value: Any, field: str, must_exist: bool = True) -> str:
    text = clean_text(value, field, required=True)
    path = Path(os.path.expandvars(os.path.expanduser(text)))
    if must_exist and not path.exists():
        raise ValueError(f"{field} não encontrado: {text}")
    return str(path)


PICKER_CONFIG = {
    "fastq_dir": {"mode": "folder", "title": "Selecione a pasta com os FASTQ.GZ"},
    "reference": {"mode": "file", "title": "Selecione a referência FASTA", "filter": "FASTA (*.fasta;*.fa;*.fna)|*.fasta;*.fa;*.fna|Todos os arquivos (*.*)|*.*"},
    "primer_bed": {"mode": "file", "title": "Selecione o arquivo Primer BED", "filter": "BED (*.bed)|*.bed|Todos os arquivos (*.*)|*.*"},
    "gff": {"mode": "file", "title": "Selecione a anotação GFF3", "filter": "GFF/GFF3 (*.gff;*.gff3)|*.gff;*.gff3|Todos os arquivos (*.*)|*.*"},
    "samplesheet": {"mode": "file", "title": "Selecione o samplesheet CSV", "filter": "CSV (*.csv)|*.csv|Todos os arquivos (*.*)|*.*"},
    "samplesheet_parent": {"mode": "folder", "title": "Selecione a pasta-pai com as subpastas dos vírus"},
    "samplesheet_output": {"mode": "save", "title": "Salvar samplesheet como", "filter": "CSV (*.csv)|*.csv|Todos os arquivos (*.*)|*.*", "default_name": "samplesheet.csv"},
    "metadata": {"mode": "file", "title": "Selecione o arquivo de metadados CSV/TSV", "filter": "Metadados CSV/TSV (*.csv;*.tsv)|*.csv;*.tsv|Todos os arquivos (*.*)|*.*"},
    "outdir": {"mode": "folder", "title": "Selecione o diretório de resultados"},
    "kraken_db": {"mode": "folder", "title": "Selecione o diretório do banco Kraken2"},
}
WINDOWS_POWERSHELL = Path("/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe")
LINUX_ZENITY = shutil.which("zenity")


def windows_to_wsl_path(value: str) -> str:
    """Convert a path returned by a Windows dialog into the current WSL namespace."""
    text = value.strip()
    if not text:
        return ""
    if text.startswith("/"):
        return text
    wsl_unc = re.match(r"^\\\\(?:wsl\.localhost|wsl\$)\\[^\\]+\\(.*)$", text, re.IGNORECASE)
    if wsl_unc:
        return "/" + wsl_unc.group(1).replace("\\", "/").lstrip("/")
    drive = re.match(r"^([A-Za-z]):[\\/]*(.*)$", text)
    if drive:
        suffix = drive.group(2).replace("\\", "/").lstrip("/")
        return f"/mnt/{drive.group(1).lower()}" + (f"/{suffix}" if suffix else "")
    converted = subprocess.run(["wslpath", "-u", text], capture_output=True, text=True, timeout=10, check=False)
    if converted.returncode == 0 and converted.stdout.strip():
        return converted.stdout.strip()
    raise ValueError("O caminho selecionado não pôde ser convertido para o WSL")


def wsl_to_windows_path(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if re.match(r"^[A-Za-z]:[\\/]", text) or text.startswith("\\\\"):
        return text
    expanded = os.path.expandvars(os.path.expanduser(text))
    converted = subprocess.run(["wslpath", "-w", expanded], capture_output=True, text=True, timeout=10, check=False)
    return converted.stdout.strip() if converted.returncode == 0 else ""


def _powershell_value(value: str) -> str:
    encoded = base64.b64encode(value.encode("utf-8")).decode("ascii")
    return f"[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{encoded}'))"


def _zenity_filters(file_filter: str) -> list[str]:
    """Convert the Windows Forms filter format into Zenity arguments."""
    parts = file_filter.split("|")
    filters = []
    for label, patterns in zip(parts[0::2], parts[1::2]):
        normalized = " ".join(patterns.replace(";", " ").split())
        if label and normalized:
            filters.append(f"--file-filter={label} | {normalized}")
    return filters


def _pick_linux_path(config: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
    if not LINUX_ZENITY:
        raise ValueError("O seletor nativo do Ubuntu não está disponível. Instale o pacote zenity.")

    mode = config["mode"]
    title = config["title"]
    default_name = config.get("default_name", "")
    current = clean_text(payload.get("current"), "Caminho atual")
    expanded = Path(os.path.expandvars(os.path.expanduser(current))) if current else None
    command = [LINUX_ZENITY, "--file-selection", f"--title={title}"]

    if mode == "folder":
        command.append("--directory")
    elif mode == "save":
        command.extend(("--save", "--confirm-overwrite"))
    else:
        command.extend(_zenity_filters(config.get("filter", "Todos os arquivos (*.*)|*.*")))

    if expanded:
        if mode == "save" and expanded.is_dir():
            initial = expanded / default_name
        elif mode == "folder" and expanded.is_file():
            initial = expanded.parent
        else:
            initial = expanded
        initial_text = str(initial)
        if mode == "folder" and not initial_text.endswith(os.sep):
            initial_text += os.sep
        command.append(f"--filename={initial_text}")
    elif mode == "save" and default_name:
        command.append(f"--filename={Path.home() / default_name}")

    completed = subprocess.run(command, capture_output=True, text=True, timeout=900, check=False)
    selected = completed.stdout.strip()
    if completed.returncode == 1 or not selected:
        return {"cancelled": True, "path": ""}
    if completed.returncode != 0:
        raise ValueError("Não foi possível abrir o seletor nativo do Ubuntu")
    return {"cancelled": False, "path": selected, "linux_path": selected}


def pick_local_path(payload: dict[str, Any]) -> dict[str, Any]:
    picker = clean_text(payload.get("picker"), "Seletor", required=True)
    config = PICKER_CONFIG.get(picker)
    if not config:
        raise ValueError("Seletor de caminho não permitido")
    if not WINDOWS_POWERSHELL.exists():
        return _pick_linux_path(config, payload)
    mode = config["mode"]
    title = config["title"]
    file_filter = config.get("filter", "Todos os arquivos (*.*)|*.*")
    default_name = config.get("default_name", "")
    initial = wsl_to_windows_path(clean_text(payload.get("current"), "Caminho atual"))
    script = f"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
[System.Windows.Forms.Application]::EnableVisualStyles()
Add-Type -ReferencedAssemblies System.Windows.Forms -TypeDefinition ({_powershell_value((WEBTOOL_DIR / "native_picker.cs").read_text(encoding="utf-8-sig"))})
$mode = {_powershell_value(mode)}
$title = {_powershell_value(title)}
$initial = {_powershell_value(initial)}
$filter = {_powershell_value(file_filter)}
$defaultName = {_powershell_value(default_name)}
$owner = [MkvaNativePicker]::FindOwner()
try {{
    if ($mode -eq 'folder') {{
        $dialog = New-Object System.Windows.Forms.FolderBrowserDialog
        $dialog.Description = $title
        $dialog.ShowNewFolderButton = $true
        if ($initial) {{
            if (Test-Path -LiteralPath $initial -PathType Leaf) {{ $dialog.SelectedPath = Split-Path -Parent $initial }}
            else {{ $dialog.SelectedPath = $initial }}
        }}
        if ([MkvaNativePicker]::Show($dialog, $owner) -eq [System.Windows.Forms.DialogResult]::OK) {{ [Console]::Write([Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($dialog.SelectedPath))) }}
    }} elseif ($mode -eq 'save') {{
        $dialog = New-Object System.Windows.Forms.SaveFileDialog
        $dialog.Title = $title
        $dialog.Filter = $filter
        $dialog.DefaultExt = 'csv'
        $dialog.AddExtension = $true
        $dialog.OverwritePrompt = $true
        if ($initial) {{
            if (Test-Path -LiteralPath $initial -PathType Container) {{ $dialog.InitialDirectory = $initial }}
            else {{
                $parent = Split-Path -Parent $initial
                if ($parent -and (Test-Path -LiteralPath $parent -PathType Container)) {{ $dialog.InitialDirectory = $parent }}
                $dialog.FileName = Split-Path -Leaf $initial
            }}
        }} elseif ($defaultName) {{ $dialog.FileName = $defaultName }}
        if ([MkvaNativePicker]::Show($dialog, $owner) -eq [System.Windows.Forms.DialogResult]::OK) {{ [Console]::Write([Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($dialog.FileName))) }}
    }} else {{
        $dialog = New-Object System.Windows.Forms.OpenFileDialog
        $dialog.Title = $title
        $dialog.Filter = $filter
        $dialog.CheckFileExists = $true
        $dialog.Multiselect = $false
        if ($initial) {{
            if (Test-Path -LiteralPath $initial -PathType Leaf) {{
                $dialog.InitialDirectory = Split-Path -Parent $initial
                $dialog.FileName = Split-Path -Leaf $initial
            }} elseif (Test-Path -LiteralPath $initial -PathType Container) {{ $dialog.InitialDirectory = $initial }}
        }}
        if ([MkvaNativePicker]::Show($dialog, $owner) -eq [System.Windows.Forms.DialogResult]::OK) {{ [Console]::Write([Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($dialog.FileName))) }}
    }}
}} finally {{
    if ($null -ne $dialog) {{ $dialog.Dispose() }}
}}
"""
    encoded_command = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    completed = subprocess.run(
        [str(WINDOWS_POWERSHELL), "-NoProfile", "-STA", "-EncodedCommand", encoded_command],
        capture_output=True, text=False, timeout=900, check=False,
    )
    selected_token = completed.stdout.strip()
    if completed.returncode != 0:
        raise ValueError("Não foi possível abrir o seletor nativo do Windows")
    if not selected_token:
        return {"cancelled": True, "path": ""}
    try:
        selected = base64.b64decode(selected_token, validate=True).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError("O caminho selecionado não pôde ser decodificado") from exc
    return {"cancelled": False, "path": windows_to_wsl_path(selected), "windows_path": selected}


def generate_samplesheet(payload: dict[str, Any]) -> dict[str, Any]:
    parent = Path(local_path(payload.get("parent"), "Pasta-pai dos dados brutos")).resolve()
    if not parent.is_dir():
        raise ValueError("Pasta-pai dos dados brutos deve ser um diretório")

    output = Path(local_path(payload.get("output"), "Arquivo CSV de saída", must_exist=False)).resolve()
    if output.suffix.lower() != ".csv":
        raise ValueError("O arquivo de saída da samplesheet deve ter extensão .csv")
    if not output.parent.is_dir():
        raise ValueError(f"Diretório de destino não encontrado: {output.parent}")
    if not SAMPLESHEET_SCRIPT.is_file():
        raise ValueError(f"Gerador de samplesheet não encontrado: {SAMPLESHEET_SCRIPT}")
    if not VIRUS_CATALOG.is_file():
        raise ValueError(f"Catálogo de vírus não encontrado: {VIRUS_CATALOG}")

    completed = subprocess.run(
        [
            sys.executable,
            str(SAMPLESHEET_SCRIPT),
            "--parent",
            str(parent),
            "--catalog",
            str(VIRUS_CATALOG),
            "--out",
            str(output),
        ],
        cwd=PROJECT_DIR,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise ValueError(detail or "Não foi possível criar a samplesheet")
    if not output.is_file():
        raise ValueError("O gerador terminou sem criar o arquivo de saída")

    with output.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        required = {
            "sample", "fastq_1", "fastq_2", "virus",
            "reference", "gff", "bed_file", "nextclade_dataset",
        }
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise ValueError("A samplesheet gerada não contém todas as colunas obrigatórias")
        rows = list(reader)
    if not rows:
        detail = completed.stderr.strip()
        raise ValueError(detail or "Nenhum par FASTQ foi encontrado nas subpastas informadas")

    virus_counts: dict[str, int] = {}
    for row in rows:
        virus_name = (row.get("virus") or "").strip()
        if virus_name:
            virus_counts[virus_name] = virus_counts.get(virus_name, 0) + 1

    warnings = []
    for line in completed.stderr.splitlines():
        cleaned = line.strip()
        if cleaned and cleaned.lower() != "notes/warnings:":
            warnings.append(cleaned.removeprefix("-").strip())

    return {
        "path": str(output),
        "samples": len(rows),
        "viruses": virus_counts,
        "warnings": warnings,
        "catalog": str(VIRUS_CATALOG),
    }


def load_jobs() -> list[dict[str, Any]]:
    if not STATE_FILE.exists():
        return []
    try:
        jobs = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    for job in jobs:
        if job.get("status") == "Executando":
            log_tail = ""
            try:
                log_path = Path(job.get("log", ""))
                if log_path.is_file():
                    with log_path.open("rb") as handle:
                        handle.seek(max(0, log_path.stat().st_size - 200_000))
                        log_tail = handle.read().decode("utf-8", errors="replace")
            except OSError:
                pass
            job["status"] = "Com erro" if "ERROR ~" in log_tail or "Finished with errors" in log_tail else "Interrompida"
            job["finished_at"] = now()
    return jobs


JOBS = load_jobs()


def save_jobs() -> None:
    STATE_FILE.write_text(json.dumps(JOBS, ensure_ascii=False, indent=2), encoding="utf-8")


def find_job(job_id: str) -> dict[str, Any] | None:
    return next((job for job in JOBS if job["id"] == job_id), None)


def build_command(payload: dict[str, Any]) -> tuple[list[str], dict[str, Any]]:
    if not NEXTFLOW.exists():
        raise ValueError(f"Nextflow não encontrado: {NEXTFLOW}")
    profile = clean_text(payload.get("profile", DEFAULT_PROFILE), "Perfil", True)
    if profile not in ALLOWED_PROFILES:
        raise ValueError("Perfil de execução não permitido")

    input_mode = clean_text(payload.get("input_mode", "mixed"), "Modo de entrada", True)
    if input_mode not in ALLOWED_INPUT_MODES:
        raise ValueError("Modo de entrada não permitido")
    if input_mode == "single":
        pipeline_input = local_path(payload.get("raw_data_dir"), "Pasta dos dados brutos")
        if not Path(pipeline_input).is_dir():
            raise ValueError("Pasta dos dados brutos deve ser um diretório")
        reference = local_path(payload.get("reference"), "Referência FASTA")
        if not Path(reference).is_file():
            raise ValueError("Referência FASTA deve ser um arquivo")
        samplesheet = ""
    else:
        pipeline_input = local_path(payload.get("samplesheet"), "Samplesheet")
        if not Path(pipeline_input).is_file():
            raise ValueError("Samplesheet deve ser um arquivo CSV")
        samplesheet = pipeline_input
        reference = ""
    outdir = local_path(payload.get("outdir"), "Diretório de resultados", must_exist=False)
    metadata_raw = clean_text(payload.get("metadata"), "Metadados")
    kraken_enabled = bool(payload.get("kraken"))
    kraken_raw = clean_text(payload.get("kraken_db"), "Banco Kraken2")
    metadata = local_path(metadata_raw, "Metadados") if metadata_raw else ""
    if metadata and Path(metadata).suffix.lower() not in {".csv", ".tsv"}:
        raise ValueError("Metadados: selecione um arquivo CSV ou TSV")
    kraken_db = local_path(kraken_raw, "Banco Kraken2") if kraken_enabled and kraken_raw else ""
    primer_bed_raw = clean_text(payload.get("primer_bed"), "Primer BED") if input_mode == "single" else ""
    gff_raw = clean_text(payload.get("gff"), "Anotação GFF3") if input_mode == "single" else ""
    primer_bed = local_path(primer_bed_raw, "Primer BED") if primer_bed_raw else ""
    gff = local_path(gff_raw, "Anotação GFF3") if gff_raw else ""
    if primer_bed and not Path(primer_bed).is_file():
        raise ValueError("Primer BED deve ser um arquivo")
    if gff and not Path(gff).is_file():
        raise ValueError("Anotação GFF3 deve ser um arquivo")
    virus = clean_text(payload.get("virus"), "Vírus", True) if input_mode == "single" else "Mixed viruses"
    nextclade_enabled = bool(payload.get("nextclade"))
    nextclade_dataset = clean_text(payload.get("nextclade_dataset"), "Dataset Nextclade") if input_mode == "single" else ""
    if nextclade_enabled and input_mode == "single" and not nextclade_dataset:
        raise ValueError("Dataset Nextclade é obrigatório no modo Single quando Nextclade está ativado")
    if nextclade_dataset and (len(nextclade_dataset) > 200 or not re.fullmatch(r"[A-Za-z0-9._/-]+", nextclade_dataset)):
        raise ValueError("Dataset Nextclade deve ser um alias ou caminho válido do catálogo")

    normalized = {
        "name": clean_text(payload.get("run_name"), "Nome da execução", True),
        "virus": virus,
        "profile": profile,
        "input_mode": input_mode,
        "input": pipeline_input,
        "raw_data_dir": pipeline_input if input_mode == "single" else "",
        "reference": reference,
        "primer_bed": primer_bed,
        "gff": gff,
        "samplesheet": samplesheet,
        "metadata": metadata,
        "outdir": outdir,
        "kraken_db": kraken_db,
        "min_cov": number(payload.get("min_cov", 20), "Cobertura mínima", 1, 100000, True),
        "min_freq": number(payload.get("min_freq", 0.75), "Frequência mínima", 0, 1),
        "min_qual": number(payload.get("min_qual", 20), "Qualidade da base", 0, 100, True),
        "min_map_qual": number(payload.get("min_map_qual", 20), "Qualidade de mapeamento", 0, 100, True),
        "max_cpus": number(payload.get("max_cpus", 14), "CPUs", 1, os.cpu_count() or 64, True),
        "max_memory": number(payload.get("max_memory", 50), "Memória", 1, 1024, True),
        "nextclade": nextclade_enabled,
        "nextclade_dataset": nextclade_dataset,
        "blast": bool(payload.get("blast")),
        "kraken": kraken_enabled,
        "deplete": bool(payload.get("deplete")) and kraken_enabled,
    }

    cmd = [str(NEXTFLOW), "run", "main.nf", "-profile", profile,
           "--input", normalized["input"], "--outdir", outdir,
           "--run_name", normalized["name"], "--min_cov", str(normalized["min_cov"]),
           "--min_freq", str(normalized["min_freq"]), "--min_qual", str(normalized["min_qual"]),
           "--min_map_qual", str(normalized["min_map_qual"]), "--max_cpus", str(normalized["max_cpus"]),
           "--max_memory", f"{normalized['max_memory']}.GB", "--nextclade", str(normalized["nextclade"]).lower(),
           "--blast_id", str(normalized["blast"]).lower()]
    if normalized["input_mode"] == "single":
        cmd.extend(["--reference", normalized["reference"], "--virus", normalized["virus"]])
        if normalized["nextclade_dataset"]:
            cmd.extend(["--nextclade_dataset", normalized["nextclade_dataset"]])
        if normalized["primer_bed"]:
            cmd.extend(["--primer_bed", normalized["primer_bed"]])
        if normalized["gff"]:
            cmd.extend(["--gff", normalized["gff"]])
    if metadata:
        cmd.extend(["--metadata", metadata])
    if kraken_db:
        cmd.extend(["--kraken2_db", kraken_db])
    if normalized["deplete"]:
        cmd.extend(["--deplete_host", "true"])
    cmd.append("-resume")
    return cmd, normalized


def queued_jobs() -> list[dict[str, Any]]:
    return sorted(
        (job for job in JOBS if job.get("status") == "Na fila"),
        key=lambda job: (job.get("created_at", ""), job.get("id", "")),
    )


def dispatch_next() -> dict[str, Any] | None:
    """Start the oldest queued job when no other Nextflow process is active."""
    while True:
        thread: threading.Thread | None = None
        started_job: dict[str, Any] | None = None
        with LOCK:
            active = any(
                job.get("status") == "Executando"
                and (process := PROCESSES.get(job["id"])) is not None
                and process.poll() is None
                for job in JOBS
            )
            if active:
                return None
            waiting = queued_jobs()
            if not waiting:
                return None
            job = waiting[0]
            log_path = Path(job["log"])
            log_handle = log_path.open("a", encoding="utf-8")
            env = os.environ.copy()
            env["JAVA_CMD"] = JAVA_CMD
            try:
                process = subprocess.Popen(
                    job["command"], cwd=PROJECT_DIR, env=env, stdout=log_handle,
                    stderr=subprocess.STDOUT, text=True, start_new_session=True,
                )
            except Exception as exc:
                log_handle.write(f"Não foi possível iniciar a execução: {exc}\n")
                log_handle.close()
                job["status"] = "Com erro"
                job["finished_at"] = now()
                job["exit_code"] = None
                save_jobs()
                continue
            job["status"] = "Executando"
            job["pid"] = process.pid
            job["started_at"] = now()
            PROCESSES[job["id"]] = process
            save_jobs()
            thread = threading.Thread(
                target=monitor, args=(job["id"], process, log_handle), daemon=True,
            )
            started_job = job
        thread.start()
        return started_job


def monitor(job_id: str, process: subprocess.Popen[str], log_handle: Any) -> None:
    code = process.wait()
    log_handle.close()
    with LOCK:
        job = find_job(job_id)
        if job:
            if job.get("status") != "Cancelada":
                job["status"] = "Concluída" if code == 0 else "Com erro"
            job["exit_code"] = code
            job["finished_at"] = now()
            save_jobs()
        PROCESSES.pop(job_id, None)
    dispatch_next()


def start_job(payload: dict[str, Any]) -> dict[str, Any]:
    cmd, normalized = build_command(payload)
    job_id = f"MKVA-{datetime.now():%Y%m%d}-{uuid.uuid4().hex[:6].upper()}"
    log_path = LOG_DIR / f"{job_id}.log"
    Path(normalized["outdir"]).mkdir(parents=True, exist_ok=True)
    log_path.touch()
    job = {"id": job_id, **normalized, "status": "Na fila", "pid": None,
           "created_at": now(), "started_at": None, "finished_at": None,
           "exit_code": None, "log": str(log_path), "command": cmd}
    with LOCK:
        JOBS.insert(0, job)
        save_jobs()
    dispatch_next()
    return job


def cancel_job(job_id: str) -> dict[str, Any]:
    with LOCK:
        job = find_job(job_id)
        if not job:
            raise ValueError("Execução não encontrada")
        if job.get("status") == "Na fila":
            job["status"] = "Cancelada"
            job["finished_at"] = now()
            save_jobs()
            return job
        process = PROCESSES.get(job_id)
        if not process or process.poll() is not None:
            raise ValueError("A execução não está ativa")
        os.killpg(process.pid, signal.SIGTERM)
        job["status"] = "Cancelada"
        job["finished_at"] = now()
        save_jobs()
        return job


def delete_job(job_id: str) -> dict[str, Any]:
    log_path: Path | None = None
    with LOCK:
        job = find_job(job_id)
        process = PROCESSES.get(job_id)
        if not job:
            raise ValueError("Execução não encontrada")
        if job.get("status") in {"Na fila", "Executando"} or (process and process.poll() is None):
            raise ValueError("Pare a análise antes de excluir a execução")
        raw_log_path = str(job.get("log") or "").strip()
        if raw_log_path:
            log_path = Path(raw_log_path).resolve()
        JOBS.remove(job)
        PROCESSES.pop(job_id, None)
        save_jobs()
    if log_path:
        try:
            if log_path.is_file() and log_path.is_relative_to(LOG_DIR.resolve()):
                log_path.unlink()
        except OSError:
            pass
    return {"id": job_id, "deleted": True, "results_preserved": True}


def public_job(job: dict[str, Any]) -> dict[str, Any]:
    public = {key: value for key, value in job.items() if key not in {"pid"}}
    waiting = queued_jobs()
    public["queue_position"] = next(
        (index for index, queued in enumerate(waiting, start=1) if queued["id"] == job["id"]),
        None,
    )
    return public


ARTIFACT_CATEGORIES = {
    "dashboard": ("Dashboard de vigilância", ("**/*dashboard*.html",), True),
    "consensus": ("Sequências consenso", ("**/consensus/*.fa", "**/consensus/*.fasta"), False),
    "metadata": ("Metadados consolidados", ("**/metadata*.xlsx",), False),
    "gisaid": ("Submissão GISAID", ("**/gisaid/*_GISAID_submission.*",), False),
    "quality": ("Relatório de qualidade", ("**/multiqc_report.html",), True),
    "variants": ("Variantes anotadas", ("**/variants/*.tsv",), False),
    "taxonomy": ("Classificação taxonômica", ("**/krona/*.html",), True),
}


def artifact_files(job: dict[str, Any], category: str) -> list[Path]:
    definition = ARTIFACT_CATEGORIES.get(category)
    if not definition:
        raise ValueError("Categoria de resultado inválida")
    root = Path(job["outdir"]).resolve()
    if not root.is_dir():
        return []
    files: set[Path] = set()
    for pattern in definition[1]:
        for candidate in root.glob(pattern):
            if candidate.is_file() and candidate.resolve().is_relative_to(root):
                files.add(candidate.resolve())
    return sorted(files)


def artifact_manifest(job: dict[str, Any]) -> list[dict[str, Any]]:
    items = []
    for key, (title, _patterns, opens_inline) in ARTIFACT_CATEGORIES.items():
        files = artifact_files(job, key)
        items.append({
            "key": key,
            "title": title,
            "available": bool(files),
            "count": len(files),
            "files": [str(path.relative_to(Path(job["outdir"]).resolve())) for path in files],
            "url": f"http://{HOST}:{PORT}/api/jobs/{quote(job['id'])}/artifacts/{key}" if files else "",
            "opens_inline": opens_inline and len(files) == 1,
        })
    return items


def resolve_job_file(job: dict[str, Any], relative_path: str) -> Path:
    root = Path(job["outdir"]).resolve()
    requested = Path(unquote(relative_path))
    if requested.is_absolute():
        raise ValueError("Caminho de resultado inválido")
    candidate = (root / requested).resolve()
    if not candidate.is_file() or not candidate.is_relative_to(root):
        raise ValueError("Arquivo de resultado não encontrado")
    return candidate


LOCAL_HTML_LINK = re.compile(
    r"(?P<prefix>\b(?:href|src)=[\"'])(?P<target>[^\"']+)(?P<suffix>[\"'])",
    re.IGNORECASE,
)


def rewrite_dashboard_links(job: dict[str, Any], dashboard: Path, content: str) -> str:
    root = Path(job["outdir"]).resolve()

    def replace(match: re.Match[str]) -> str:
        target = match.group("target")
        parsed = urlparse(target)
        if parsed.scheme or parsed.netloc or target.startswith(("#", "//")):
            return match.group(0)
        candidate = (dashboard.parent / unquote(parsed.path)).resolve()
        if not candidate.is_file() or not candidate.is_relative_to(root):
            return match.group(0)
        relative = quote(candidate.relative_to(root).as_posix(), safe="/")
        url = f"http://{HOST}:{PORT}/api/jobs/{quote(job['id'])}/files/{relative}"
        return f"{match.group('prefix')}{url}{match.group('suffix')}"

    return LOCAL_HTML_LINK.sub(replace, content)


def read_tsv_rows(path: Path) -> list[dict[str, str]]:
    try:
        with path.open(encoding="utf-8", errors="replace", newline="") as handle:
            return list(csv.DictReader(handle, delimiter="\t"))
    except OSError:
        return []


def virus_label(species: str, fallback: str) -> str:
    dengue = re.search(r"Dengue virus\s*(\d)", species, re.IGNORECASE)
    if dengue:
        return f"DENV{dengue.group(1)}"
    lowered = species.lower()
    if "chikungunya" in lowered:
        return "CHIKV"
    if "sars-cov-2" in lowered:
        return "SARS-CoV-2"
    if "respiratory syncytial" in lowered:
        return "VSR"
    return fallback


def sample_records(job: dict[str, Any]) -> list[dict[str, Any]]:
    root = Path(job["outdir"]).resolve()
    if not root.is_dir():
        return []
    records: dict[str, dict[str, Any]] = {}
    for path in root.glob("**/read_stats/*.read_stats.tsv"):
        for row in read_tsv_rows(path):
            sample = row.get("sample", "").strip()
            if sample:
                records.setdefault(sample, {})["reads"] = row.get("reads_raw") or row.get("reads_post_fastp") or ""
    for path in root.glob("**/consensus_qc/*.consensus_qc.tsv"):
        for row in read_tsv_rows(path):
            sample = row.get("sample", "").strip()
            if not sample:
                continue
            record = records.setdefault(sample, {})
            try:
                record["depth"] = f"{float(row.get('mean_depth') or 0):.2f}"
            except ValueError:
                record["depth"] = ""
            try:
                record["coverage"] = f"{float(row.get('breadth_ge_20x') or 0) * 100:.2f}"
            except ValueError:
                record["coverage"] = ""
    for path in root.glob("**/blast/blast_summary.tsv"):
        for row in read_tsv_rows(path):
            sample = row.get("sample", "").strip()
            if sample:
                species = row.get("best_hit_species", "").strip()
                records.setdefault(sample, {})["virus"] = virus_label(species, job["virus"])
    return [{
        "run_id": job["id"], "run_name": job["name"], "sample": sample,
        "virus": values.get("virus", job["virus"]), "qc": "—",
        "reads": values.get("reads", ""), "depth": values.get("depth", ""),
        "coverage": values.get("coverage", ""), "lineage_genotype": "",
        "status": job["status"],
    } for sample, values in sorted(records.items())]


class Handler(BaseHTTPRequestHandler):
    server_version = "MKVAWebtool/0.1"

    def end_headers(self) -> None:
        origin = self.headers.get("Origin", "")
        if re.fullmatch(r"http://(?:localhost|127\.0\.0\.1):\d+", origin):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        super().end_headers()

    def json_response(self, status: int, payload: Any) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def file_response(self, payload: bytes, content_type: str, filename: str, inline: bool = False) -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        disposition = "inline" if inline else "attachment"
        self.send_header("Content-Disposition", f"{disposition}; filename*=UTF-8''{quote(filename)}")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length > 100_000:
            raise ValueError("Requisição muito grande")
        return json.loads(self.rfile.read(length) or b"{}")

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.end_headers()

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/health":
            self.json_response(200, {"ok": True, "project": str(PROJECT_DIR),
                                     "nextflow": str(NEXTFLOW), "nextflow_available": NEXTFLOW.exists(),
                                     "default_profile": DEFAULT_PROFILE,
                                     "singularity_available": bool(shutil.which("singularity") or shutil.which("apptainer")),
                                     "jobs": len(JOBS)})
            return
        if path == "/api/jobs":
            with LOCK:
                self.json_response(200, [public_job(job) for job in JOBS])
            return
        match = re.fullmatch(r"/api/jobs/([^/]+)/log", path)
        if match:
            job = find_job(match.group(1))
            if not job:
                self.json_response(404, {"error": "Execução não encontrada"}); return
            log_path = Path(job["log"])
            text = log_path.read_text(encoding="utf-8", errors="replace")[-100_000:] if log_path.exists() else ""
            self.json_response(200, {"id": job["id"], "log": text}); return
        match = re.fullmatch(r"/api/jobs/([^/]+)/samples", path)
        if match:
            job = find_job(match.group(1))
            if not job:
                self.json_response(404, {"error": "Execução não encontrada"}); return
            self.json_response(200, {"id": job["id"], "samples": sample_records(job)}); return
        match = re.fullmatch(r"/api/jobs/([^/]+)/artifacts", path)
        if match:
            job = find_job(match.group(1))
            if not job:
                self.json_response(404, {"error": "Execução não encontrada"}); return
            self.json_response(200, {"id": job["id"], "artifacts": artifact_manifest(job)}); return
        match = re.fullmatch(r"/api/jobs/([^/]+)/files/(.+)", path)
        if match:
            job = find_job(match.group(1))
            if not job:
                self.json_response(404, {"error": "Execução não encontrada"}); return
            try:
                file = resolve_job_file(job, match.group(2))
            except ValueError as exc:
                self.json_response(404, {"error": str(exc)}); return
            content_type = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
            inline = content_type.startswith(("text/", "image/")) or content_type in {"application/javascript", "application/json"}
            self.file_response(file.read_bytes(), content_type, file.name, inline); return
        match = re.fullmatch(r"/api/jobs/([^/]+)/artifacts/([a-z]+)", path)
        if match:
            job = find_job(match.group(1))
            if not job:
                self.json_response(404, {"error": "Execução não encontrada"}); return
            category = match.group(2)
            try:
                files = artifact_files(job, category)
            except ValueError as exc:
                self.json_response(400, {"error": str(exc)}); return
            if not files:
                self.json_response(404, {"error": "Resultado ainda não disponível"}); return
            title, _patterns, opens_inline = ARTIFACT_CATEGORIES[category]
            if len(files) == 1:
                file = files[0]
                content_type = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
                if category == "dashboard" and file.suffix.lower() == ".html":
                    content = file.read_text(encoding="utf-8", errors="replace")
                    content = rewrite_dashboard_links(job, file, content)
                    self.file_response(content.encode("utf-8"), "text/html; charset=utf-8", file.name, True); return
                self.file_response(file.read_bytes(), content_type, file.name, opens_inline); return
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
                root = Path(job["outdir"]).resolve()
                for file in files:
                    archive.write(file, file.relative_to(root))
            filename = f"{job['name']}_{category}.zip"
            self.file_response(buffer.getvalue(), "application/zip", filename); return
        self.json_response(404, {"error": "Rota não encontrada"})

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        try:
            payload = self.read_json()
            if path == "/api/picker":
                self.json_response(200, pick_local_path(payload)); return
            if path == "/api/samplesheet":
                self.json_response(201, generate_samplesheet(payload)); return
            if path == "/api/jobs/preview":
                cmd, normalized = build_command(payload)
                self.json_response(200, {"command": cmd, "parameters": normalized}); return
            if path == "/api/jobs":
                self.json_response(201, public_job(start_job(payload))); return
            match = re.fullmatch(r"/api/jobs/([^/]+)/cancel", path)
            if match:
                self.json_response(200, public_job(cancel_job(match.group(1)))); return
            self.json_response(404, {"error": "Rota não encontrada"})
        except (ValueError, json.JSONDecodeError) as exc:
            self.json_response(400, {"error": str(exc)})
        except Exception as exc:
            self.json_response(500, {"error": f"Erro interno: {exc}"})

    def do_DELETE(self) -> None:
        path = urlparse(self.path).path
        try:
            match = re.fullmatch(r"/api/jobs/([^/]+)", path)
            if not match:
                self.json_response(404, {"error": "Rota não encontrada"}); return
            self.json_response(200, delete_job(match.group(1)))
        except ValueError as exc:
            self.json_response(400, {"error": str(exc)})
        except Exception as exc:
            self.json_response(500, {"error": f"Erro interno: {exc}"})

    def log_message(self, format: str, *args: Any) -> None:
        print(f"[webtool] {self.address_string()} - {format % args}")


if __name__ == "__main__":
    print(f"MK-Viral-Assembly local API: http://{HOST}:{PORT}")
    print(f"Project: {PROJECT_DIR}")
    dispatch_next()
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
