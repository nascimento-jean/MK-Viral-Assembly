#!/usr/bin/env python3
"""Reduce raw blastn output (outfmt 6 with qcovs+stitle) to a best-hit-per-sample
species-confirmation table.

Input columns (tab):
  qseqid sseqid pident length qcovs evalue bitscore stitle

For each query (consensus record; header 'sample' or 'sample|segment') keep the
single best hit ranked by bitscore. The subject title (stitle) from RefSeq is
parsed to a readable species/organism string.

Output columns:
  sample, segment, best_hit_species, accession, pct_identity, coverage,
  evalue, bitscore
"""
import argparse, csv, os, re


def parse_species(stitle, sseqid):
    # stitle like: "NC_004162.2 Chikungunya virus, complete genome"
    t = stitle.strip()
    # drop a leading accession token if present
    parts = t.split(None, 1)
    if len(parts) == 2 and re.match(r"^[A-Z_]+\d", parts[0]):
        t = parts[1]
    # trim common suffixes
    for suf in (", complete genome", ", complete sequence", ", complete cds",
                " complete genome", " genomic sequence"):
        if t.endswith(suf):
            t = t[: -len(suf)]
    return t.strip() or sseqid


def accession(sseqid, stitle):
    # sseqid may be 'ref|NC_004162.2|' or 'NC_004162.2'
    m = re.search(r"([A-Z]{1,3}_?\d{4,}\.\d+)", sseqid) or re.search(r"([A-Z]{1,3}_?\d{4,}\.\d+)", stitle)
    return m.group(1) if m else sseqid.strip("|")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    best = {}   # qseqid -> row tuple
    if os.path.exists(args.raw):
        with open(args.raw) as fh:
            for line in fh:
                f = line.rstrip("\n").split("\t")
                if len(f) < 8:
                    continue
                qseqid, sseqid, pident, length, qcovs, evalue, bitscore, stitle = f[:8]
                try:
                    bs = float(bitscore)
                except ValueError:
                    continue
                if qseqid not in best or bs > best[qseqid][0]:
                    best[qseqid] = (bs, sseqid, pident, qcovs, evalue, stitle)

    cols = ["sample", "segment", "best_hit_species", "accession",
            "pct_identity", "coverage", "evalue", "bitscore"]
    with open(args.out, "w", newline="") as fh:
        w = csv.writer(fh, delimiter="\t", lineterminator="\n")
        w.writerow(cols)
        for qseqid in sorted(best):
            bs, sseqid, pident, qcovs, evalue, stitle = best[qseqid]
            if "|" in qseqid:
                smp, seg = qseqid.split("|", 1)
            else:
                smp, seg = qseqid, "ALL"
            w.writerow([smp, seg, parse_species(stitle, sseqid),
                        accession(sseqid, stitle), pident, qcovs, evalue, f"{bs:g}"])

    print(f"blast_summary: {len(best)} query hit(s) -> {args.out}")


if __name__ == "__main__":
    main()
