#!/usr/bin/env python3
"""Check consensus coding regions for frame length and internal stop codons."""

import argparse
import csv
from collections import defaultdict


COMPLEMENT = str.maketrans("ACGTRYMKSWBDHVNacgtrymkswbdhvn", "TGCAYRKMSWVHDBNtgcayrkmswvhdbn")
CODON = {
    "TTT":"F","TTC":"F","TTA":"L","TTG":"L","TCT":"S","TCC":"S","TCA":"S","TCG":"S",
    "TAT":"Y","TAC":"Y","TAA":"*","TAG":"*","TGT":"C","TGC":"C","TGA":"*","TGG":"W",
    "CTT":"L","CTC":"L","CTA":"L","CTG":"L","CCT":"P","CCC":"P","CCA":"P","CCG":"P",
    "CAT":"H","CAC":"H","CAA":"Q","CAG":"Q","CGT":"R","CGC":"R","CGA":"R","CGG":"R",
    "ATT":"I","ATC":"I","ATA":"I","ATG":"M","ACT":"T","ACC":"T","ACA":"T","ACG":"T",
    "AAT":"N","AAC":"N","AAA":"K","AAG":"K","AGT":"S","AGC":"S","AGA":"R","AGG":"R",
    "GTT":"V","GTC":"V","GTA":"V","GTG":"V","GCT":"A","GCC":"A","GCA":"A","GCG":"A",
    "GAT":"D","GAC":"D","GAA":"E","GAG":"E","GGT":"G","GGC":"G","GGA":"G","GGG":"G",
}


def fasta(path):
    records, name, parts = {}, None, []
    with open(path) as handle:
        for line in handle:
            if line.startswith(">"):
                if name is not None:
                    records[name] = "".join(parts).upper()
                name, parts = line[1:].strip().split()[0], []
            else:
                parts.append(line.strip())
        if name is not None:
            records[name] = "".join(parts).upper()
    return records


def attributes(text):
    result = {}
    for item in text.split(";"):
        if "=" in item:
            key, value = item.split("=", 1)
            result[key] = value
    return result


def translate(sequence):
    return "".join(CODON.get(sequence[i:i+3], "X") for i in range(0, len(sequence) - 2, 3))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", required=True)
    parser.add_argument("--fasta", required=True)
    parser.add_argument("--gff", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    records = fasta(args.fasta)
    by_contig = {}
    for header, seq in records.items():
        by_contig[header.split("|", 1)[-1]] = seq
    rows = []
    with open(args.gff, encoding="utf-8-sig") as handle:
        for line in handle:
            if not line.strip() or line.startswith("#"):
                continue
            fields = line.rstrip("\n").split("\t")
            if len(fields) < 9 or fields[2].upper() != "CDS":
                continue
            contig, start, end, strand, phase = fields[0], int(fields[3]), int(fields[4]), fields[6], fields[7]
            attrs = attributes(fields[8])
            feature = attrs.get("Name") or attrs.get("gene") or attrs.get("ID") or f"{contig}:{start}-{end}"
            sequence = by_contig.get(contig, "")
            if not sequence and len(records) == 1:
                sequence = next(iter(records.values()))
            cds = sequence[start-1:end] if sequence else ""
            if strand == "-":
                cds = cds.translate(COMPLEMENT)[::-1]
            try:
                phase_value = int(phase)
            except ValueError:
                phase_value = 0
            cds = cds[phase_value:]
            protein = translate(cds)
            internal_stops = [str(i + 1) for i, aa in enumerate(protein[:-1]) if aa == "*"]
            rows.append([
                args.sample, contig, feature, start, end, strand, len(cds),
                "YES" if len(cds) % 3 else "NO", len(internal_stops),
                ",".join(internal_stops), "YES" if not sequence else "NO",
            ])
    columns = ["sample","contig","feature","start","end","strand","cds_length",
               "cds_length_not_multiple_of_3","internal_stop_count","internal_stop_positions","missing_contig"]
    with open(args.out, "w", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(columns)
        writer.writerows(rows)


if __name__ == "__main__":
    main()
