#!/usr/bin/env python3
"""Per-sample consensus QC metrics for the viral-assembly pipeline.

Reads a consensus FASTA and a `samtools depth -a` file and reports:
  - genome length (consensus)
  - number and fraction of N bases
  - fraction of the reference covered at >= min_depth (breadth)
  - mean / median depth over the reference
This is deliberately dependency-free (stdlib only) so it runs in the same
minimal container as samtools.
"""
import argparse
import statistics
import sys


def read_fasta_records(path):
    """Return an ordered list of (name, sequence) records."""
    records = []
    name, seq = None, []
    with open(path) as fh:
        for line in fh:
            if line.startswith(">"):
                if name is not None:
                    records.append((name, "".join(seq)))
                name = line[1:].strip().split()[0] if line[1:].strip() else ""
                seq = []
            else:
                seq.append(line.strip())
    if name is not None:
        records.append((name, "".join(seq)))
    return records


def read_depth_by_contig(path):
    """samtools depth -a -> {contig: [depths...]} preserving contig order."""
    per = {}
    order = []
    with open(path) as fh:
        for line in fh:
            parts = line.rstrip("\n").split("\t")
            if len(parts) >= 3:
                contig = parts[0]
                try:
                    d = int(parts[2])
                except ValueError:
                    continue
                if contig not in per:
                    per[contig] = []
                    order.append(contig)
                per[contig].append(d)
    return per, order


def metrics(name, seq, depths, min_depth):
    seq = seq.upper()
    length = len(seq)
    n_count = seq.count("N")
    n_frac = (n_count / length) if length else 0.0
    completeness = ((length - n_count) / length) if length else 0.0
    ref_positions = len(depths)
    covered = sum(1 for d in depths if d >= min_depth)
    breadth = (covered / ref_positions) if ref_positions else 0.0
    mean_depth = (sum(depths) / ref_positions) if ref_positions else 0.0
    median_depth = statistics.median(depths) if depths else 0
    return [
        name, length, n_count, f"{n_frac:.4f}",
        f"{completeness:.4f}", ref_positions,
        f"{breadth:.4f}", f"{mean_depth:.2f}", median_depth,
    ]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", required=True)
    ap.add_argument("--fasta", required=True)
    ap.add_argument("--depth", required=True, help="samtools depth -a output")
    ap.add_argument("--min-depth", type=int, default=10)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    records = read_fasta_records(args.fasta)
    per_contig, contig_order = read_depth_by_contig(args.depth)

    # whole-sample sequence = all records concatenated
    all_seq = "".join(s for _, s in records)
    all_depths = [d for c in contig_order for d in per_contig[c]]

    header = [
        "sample", "segment", "consensus_length", "n_bases", "n_fraction",
        "completeness", "ref_positions",
        f"breadth_ge_{args.min_depth}x", "mean_depth", "median_depth",
    ]

    rows = []
    # whole-sample summary row (segment = "ALL")
    whole = metrics(args.sample, all_seq, all_depths, args.min_depth)
    rows.append([whole[0], "ALL"] + whole[1:])

    # per-segment rows only when the reference has more than one contig
    if len(contig_order) > 1:
        # map consensus records to contigs by order (headers are >sample|contig)
        for i, contig in enumerate(contig_order):
            seq = records[i][1] if i < len(records) else ""
            m = metrics(args.sample, seq, per_contig[contig], args.min_depth)
            rows.append([m[0], contig] + m[1:])

    with open(args.out, "w") as out:
        out.write("\t".join(header) + "\n")
        for r in rows:
            out.write("\t".join(str(x) for x in r) + "\n")

    # echo to stdout for the log
    for r in rows:
        sys.stdout.write("\t".join(str(x) for x in r) + "\n")


if __name__ == "__main__":
    main()
