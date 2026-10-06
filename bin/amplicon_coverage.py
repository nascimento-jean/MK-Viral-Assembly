#!/usr/bin/env python3
"""Summarize depth across amplicons inferred from a primer BED file."""

import argparse
import csv
import re
from collections import defaultdict


def amplicon_name(name):
    text = (name or "").strip()
    patterns = [
        r"(?i)(?:[_-](?:LEFT|RIGHT))$",
        r"(?i)(?:[_-](?:L|R))$",
        r"(?i)(?:[_-](?:F|REV|FORWARD|REVERSE))$",
    ]
    for pattern in patterns:
        reduced = re.sub(pattern, "", text)
        if reduced != text:
            return reduced
    return text or "unnamed"


def read_bed(path):
    groups = {}
    with open(path, encoding="utf-8-sig") as handle:
        for index, line in enumerate(handle, 1):
            if not line.strip() or line.startswith(("#", "track", "browser")):
                continue
            fields = line.rstrip("\n").split("\t")
            if len(fields) < 3:
                continue
            chrom, start, end = fields[:3]
            try:
                start, end = int(start), int(end)
            except ValueError:
                continue
            name = fields[3] if len(fields) > 3 else f"interval_{index}"
            key = (chrom, amplicon_name(name))
            if key not in groups:
                groups[key] = [start, end]
            else:
                groups[key][0] = min(groups[key][0], start)
                groups[key][1] = max(groups[key][1], end)
    return groups


def read_depth(path):
    depths = defaultdict(dict)
    with open(path) as handle:
        for line in handle:
            fields = line.rstrip("\n").split("\t")
            if len(fields) < 3:
                continue
            try:
                depths[fields[0]][int(fields[1])] = int(fields[2])
            except ValueError:
                continue
    return depths


def accession_without_version(contig):
    """Return an accession without a final numeric version (e.g. .1)."""
    return re.sub(r"\.\d+$", "", (contig or "").strip())


def resolve_depth_contig(bed_contig, depths):
    """Prefer an exact contig; otherwise accept one unambiguous version alias."""
    if bed_contig in depths:
        return bed_contig
    base = accession_without_version(bed_contig)
    matches = [name for name in depths if accession_without_version(name) == base]
    return matches[0] if len(matches) == 1 else None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", required=True)
    parser.add_argument("--bed", required=True)
    parser.add_argument("--depth", required=True)
    parser.add_argument("--min-depth", type=int, required=True)
    parser.add_argument("--min-breadth", type=float, default=0.90)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    groups = read_bed(args.bed)
    depths = read_depth(args.depth)
    columns = [
        "sample", "contig", "amplicon", "start_1based", "end_1based",
        "length", "mean_depth", "min_depth", "breadth_ge_min_depth", "dropout",
    ]
    with open(args.out, "w", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(columns)
        for (contig, name), (bed_start, bed_end) in sorted(groups.items()):
            start, end = bed_start + 1, bed_end
            depth_contig = resolve_depth_contig(contig, depths)
            contig_depths = depths.get(depth_contig, {}) if depth_contig else {}
            values = [contig_depths.get(pos, 0) for pos in range(start, end + 1)]
            length = len(values)
            mean = sum(values) / length if length else 0.0
            minimum = min(values) if values else 0
            breadth = sum(value >= args.min_depth for value in values) / length if length else 0.0
            writer.writerow([
                args.sample, contig, name, start, end, length, f"{mean:.2f}",
                minimum, f"{breadth:.4f}", "YES" if breadth < args.min_breadth else "NO",
            ])


if __name__ == "__main__":
    main()
