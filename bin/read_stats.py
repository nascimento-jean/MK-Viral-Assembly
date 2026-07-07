#!/usr/bin/env python3
"""Per-sample read accounting for the surveillance dashboard.

Reads the fastp JSON (raw and post-filter read counts) and, when host
depletion was run, counts the reads remaining in the dehosted FASTQ files.
Emits a one-row TSV:

    sample  reads_raw  reads_post_fastp  reads_post_deplete

Counts are total reads (R1 + R2), matching fastp's own total_reads. Missing
values are written empty so the dashboard renders a dash.
"""
import argparse
import glob
import gzip
import json
import os


def count_fastq_reads(path):
    """Count reads (lines / 4) in a plain or gzipped FASTQ."""
    opener = gzip.open if path.endswith(".gz") else open
    n = 0
    with opener(path, "rt") as fh:
        for _ in fh:
            n += 1
    return n // 4


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", required=True)
    ap.add_argument("--fastp-json", required=True)
    ap.add_argument("--dehost-dir", default=None,
                    help="directory with dehosted *.fastq.gz (host-depletion output)")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    raw = post = ""
    try:
        with open(a.fastp_json) as fh:
            j = json.load(fh)
        summ = j.get("summary", {})
        raw = summ.get("before_filtering", {}).get("total_reads", "")
        post = summ.get("after_filtering", {}).get("total_reads", "")
    except Exception:
        pass

    deplete = ""
    if a.dehost_dir and os.path.isdir(a.dehost_dir):
        files = [f for f in sorted(glob.glob(os.path.join(a.dehost_dir, "*.fastq.gz")))
                 if "NO_FILE" not in os.path.basename(f)]
        if files:
            deplete = sum(count_fastq_reads(f) for f in files)

    with open(a.out, "w") as fh:
        fh.write("sample\treads_raw\treads_post_fastp\treads_post_deplete\n")
        fh.write(f"{a.sample}\t{raw}\t{post}\t{deplete}\n")


if __name__ == "__main__":
    main()
