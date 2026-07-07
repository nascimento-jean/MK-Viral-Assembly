#!/usr/bin/env python3
"""Convert a Kraken2 report into Krona text (ktImportText) format.

Kraken2 report columns (tab-separated):
  1) percent of reads in clade
  2) reads in clade
  3) reads assigned directly to this taxon
  4) rank code (U, R, D/K, P, C, O, F, G, S, ...)
  5) NCBI taxid
  6) scientific name, indented by 2 spaces per depth level

Krona text format (one line per leaf/taxon):
  <count>\t<level1>\t<level2>\t...\t<levelN>

We emit one line per taxon using the reads assigned DIRECTLY to it (col 3),
with the full lineage path rebuilt from the indentation. This mirrors
KrakenTools' kreport2krona so ktImportText renders the same hierarchy,
without needing the NCBI taxonomy database.
"""
import argparse
import sys


def indent_level(name_field):
    """Number of leading 2-space indents in the name column."""
    n = 0
    for ch in name_field:
        if ch == " ":
            n += 1
        else:
            break
    return n // 2


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", required=True, help="Kraken2 report file")
    ap.add_argument("--out", required=True, help="output Krona text file")
    ap.add_argument("--intermediate-ranks", action="store_true",
                    help="keep all ranks (default: keep too)")
    args = ap.parse_args()

    lineage = []  # stack of (level, name)
    lines_out = []
    with open(args.report) as fh:
        for line in fh:
            if not line.strip():
                continue
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 6:
                continue
            try:
                reads_direct = int(parts[2])
            except ValueError:
                continue
            rank = parts[3].strip()
            name_field = parts[5]
            name = name_field.strip()
            lvl = indent_level(name_field)

            # unclassified (rank U) has no indentation and taxid 0
            if rank == "U":
                if reads_direct > 0:
                    lines_out.append((reads_direct, ["unclassified"]))
                continue

            # maintain the lineage stack by indentation level
            while lineage and lineage[-1][0] >= lvl:
                lineage.pop()
            lineage.append((lvl, name))

            if reads_direct > 0:
                path = [nm for _, nm in lineage]
                lines_out.append((reads_direct, path))

    with open(args.out, "w") as out:
        for count, path in lines_out:
            out.write("\t".join([str(count)] + path) + "\n")

    sys.stderr.write(f"kreport2krona: wrote {len(lines_out)} taxa -> {args.out}\n")


if __name__ == "__main__":
    main()
