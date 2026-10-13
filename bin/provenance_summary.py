#!/usr/bin/env python3
"""Build a compact tool and database provenance table for the dashboard."""

import argparse
import csv
import re
from pathlib import Path


def add(rows, category, name, version="", source="", details=""):
    rows.append([category, name, str(version or ""), str(source or ""), str(details or "")])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", required=True)
    ap.add_argument("--pipeline-version", required=True)
    ap.add_argument("--nextflow-version", required=True)
    ap.add_argument("--profile", default="")
    ap.add_argument("--module-dir", required=True)
    ap.add_argument("--nextclade-dataset", default="")
    ap.add_argument("--nextclade-tag", default="")
    ap.add_argument("--blast-date", default="")
    ap.add_argument("--blast-db", default="")
    ap.add_argument("--kraken-db", default="")
    ap.add_argument("--snpeff-enabled", default="false")
    args = ap.parse_args()

    rows = []
    add(rows, "pipeline", "MK-Viral-Assembly", args.pipeline_version, "local checkout", f"profile={args.profile}")
    add(rows, "engine", "Nextflow", args.nextflow_version, "runtime", args.profile)

    seen = set()
    for path in sorted(Path(args.module_dir).glob("*.nf")):
        text = path.read_text(encoding="utf-8", errors="replace")
        for declaration in re.findall(r'conda\s+"([^"]+)"', text):
            for spec in declaration.split():
                if "::" not in spec:
                    continue
                package = spec.split("::", 1)[1]
                if "=" in package:
                    name, version = package.split("=", 1)
                else:
                    name, version = package, ""
                key = (name.lower(), version)
                if key not in seen:
                    add(rows, "tool", name, version, "module declaration", path.name)
                    seen.add(key)

    if args.nextclade_dataset:
        add(rows, "database", "Nextclade dataset", args.nextclade_tag or "latest", "Nextclade catalog", args.nextclade_dataset)
    if args.blast_db:
        date = ""
        p = Path(args.blast_date) if args.blast_date else None
        if p and p.is_file() and p.stat().st_size:
            date = p.read_text(encoding="utf-8", errors="replace").strip()
        add(rows, "database", "NCBI RefSeq viral BLAST", date or "local", args.blast_db, "blastn species confirmation")
    if args.kraken_db:
        add(rows, "database", "Kraken2", "user-provided", args.kraken_db, "read-level taxonomic screen")
    if args.snpeff_enabled.lower() == "true":
        add(rows, "database", "SnpEff per-reference database", "run-specific", "selected FASTA + GFF3", "built locally for each sample")

    with open(args.output, "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(["category", "name", "version_or_release", "source", "details"])
        writer.writerows(rows)


if __name__ == "__main__":
    main()
