#!/usr/bin/env python3
"""Summarise Kraken2 reports into a per-sample composition table.

For each <sample>.kraken2.report.txt we report:
  sample, total_reads, pct_unclassified, pct_human, pct_viral,
  pct_bacterial, top_nonhost_taxon, top_nonhost_pct

Percentages are of total reads (classified + unclassified). "Viral" uses the
clade-level count at the Viruses domain (taxid 10239); "human" uses the
Homo sapiens species (taxid 9606); "bacterial" uses Bacteria (taxid 2).
Dependency-free (stdlib) so it runs in the python:3.10 container.
"""
import argparse
import glob
import os
import sys


def parse_report(path):
    """Return dict with the fields we need from one Kraken2 report."""
    total = 0
    pct_unclass = 0.0
    clade_reads = {}   # taxid -> reads in clade
    clade_pct = {}     # taxid -> percent (clade)
    rows = []
    with open(path) as fh:
        for line in fh:
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 6:
                continue
            try:
                pct = float(parts[0])
                clade = int(parts[1])
            except ValueError:
                continue
            rank = parts[3].strip()
            taxid = parts[4].strip()
            name = parts[5].strip()
            total += clade if rank == "U" or taxid == "1" else 0
            clade_reads[taxid] = clade
            clade_pct[taxid] = pct
            if rank == "U":
                pct_unclass = pct
            rows.append((pct, clade, rank, taxid, name))
    # total reads = unclassified + root(taxid 1) clade
    total_reads = clade_reads.get("0", 0) + clade_reads.get("1", 0)
    return {
        "total_reads": total_reads,
        "pct_unclassified": clade_pct.get("0", pct_unclass),
        "pct_human": clade_pct.get("9606", 0.0),
        "pct_viral": clade_pct.get("10239", 0.0),
        "pct_bacterial": clade_pct.get("2", 0.0),
        "rows": rows,
    }


def top_nonhost(rows):
    """Highest-percent species-level taxon that is not human/root/unclassified."""
    best = ("-", 0.0)
    for pct, clade, rank, taxid, name in rows:
        if rank.startswith("S") and taxid not in ("9606", "0", "1"):
            if pct > best[1]:
                best = (name, pct)
    return best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kraken-dir", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    reports = sorted(glob.glob(os.path.join(args.kraken_dir, "*.kraken2.report.txt")))
    header = ["sample", "total_reads", "pct_unclassified", "pct_human",
              "pct_viral", "pct_bacterial", "top_nonhost_taxon", "top_nonhost_pct"]
    with open(args.out, "w") as out:
        out.write("\t".join(header) + "\n")
        for rp in reports:
            sample = os.path.basename(rp).replace(".kraken2.report.txt", "")
            d = parse_report(rp)
            tname, tpct = top_nonhost(d["rows"])
            out.write("\t".join(str(x) for x in [
                sample, d["total_reads"],
                f"{d['pct_unclassified']:.2f}", f"{d['pct_human']:.2f}",
                f"{d['pct_viral']:.2f}", f"{d['pct_bacterial']:.2f}",
                tname, f"{tpct:.2f}",
            ]) + "\n")
    sys.stderr.write(f"taxonomy_summary: {len(reports)} report(s) -> {args.out}\n")


if __name__ == "__main__":
    main()
