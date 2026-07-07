#!/usr/bin/env python3
"""Generate a tiny self-contained test dataset for the viral-assembly pipeline.

Creates:
  <outdir>/reference.fasta            a ~2 kb synthetic "viral" genome
  <outdir>/<sample>_R1.fastq.gz       paired-end reads (2 samples)
  <outdir>/<sample>_R2.fastq.gz
  <outdir>/samplesheet.csv

Reads are simulated from the reference with a handful of introduced
substitutions per sample, so variant calling and consensus generation
have something to find. Stdlib only.
"""
import argparse
import gzip
import os
import random

BASES = "ACGT"


def make_reference(length, seed=1):
    rng = random.Random(seed)
    return "".join(rng.choice(BASES) for _ in range(length))


def mutate(seq, positions_to_alt):
    s = list(seq)
    for pos, alt in positions_to_alt.items():
        s[pos] = alt
    return "".join(s)


def revcomp(seq):
    comp = {"A": "T", "T": "A", "G": "C", "C": "G", "N": "N"}
    return "".join(comp[b] for b in reversed(seq))


def qual_string(n, q=38):
    return chr(q + 33) * n


def simulate_reads(genome, n_reads, read_len, frag_len, rng, err=0.001):
    """Yield (r1, r2) sequence tuples as paired-end reads across the genome."""
    glen = len(genome)
    for _ in range(n_reads):
        start = rng.randint(0, max(0, glen - frag_len))
        frag = genome[start:start + frag_len]
        r1 = frag[:read_len]
        r2 = revcomp(frag[-read_len:])
        r1 = add_errors(r1, rng, err)
        r2 = add_errors(r2, rng, err)
        yield r1, r2


def add_errors(read, rng, err):
    if err <= 0:
        return read
    out = list(read)
    for i, b in enumerate(out):
        if rng.random() < err:
            out[i] = rng.choice([x for x in BASES if x != b])
    return "".join(out)


def write_fastq(path, records):
    with gzip.open(path, "wt") as fh:
        for name, seq in records:
            fh.write(f"@{name}\n{seq}\n+\n{qual_string(len(seq))}\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("outdir")
    ap.add_argument("--genome-length", type=int, default=2000)
    ap.add_argument("--reads-per-sample", type=int, default=3000)
    ap.add_argument("--read-len", type=int, default=150)
    ap.add_argument("--frag-len", type=int, default=350)
    args = ap.parse_args()

    os.makedirs(args.outdir, exist_ok=True)

    ref = make_reference(args.genome_length)
    with open(os.path.join(args.outdir, "reference.fasta"), "w") as fh:
        fh.write(">test_reference\n")
        for i in range(0, len(ref), 70):
            fh.write(ref[i:i + 70] + "\n")

    # two samples, each with its own set of substitutions
    sample_variants = {
        "sampleA": {300: "A", 750: "C", 1200: "T"},
        "sampleB": {450: "G", 900: "A"},
    }

    rows = []
    for sample, variants in sample_variants.items():
        rng = random.Random(hash(sample) % (2**32))
        # enforce variants that differ from the reference
        variants = {p: (a if a != ref[p] else BASES[(BASES.index(ref[p]) + 1) % 4])
                    for p, a in variants.items()}
        genome = mutate(ref, variants)
        r1_records, r2_records = [], []
        for i, (r1, r2) in enumerate(
                simulate_reads(genome, args.reads_per_sample, args.read_len, args.frag_len, rng)):
            name = f"{sample}_read{i}"
            r1_records.append((f"{name}/1", r1))
            r2_records.append((f"{name}/2", r2))
        f1 = os.path.join(args.outdir, f"{sample}_R1.fastq.gz")
        f2 = os.path.join(args.outdir, f"{sample}_R2.fastq.gz")
        write_fastq(f1, r1_records)
        write_fastq(f2, r2_records)
        rows.append((sample, os.path.abspath(f1), os.path.abspath(f2)))

    with open(os.path.join(args.outdir, "samplesheet.csv"), "w") as fh:
        fh.write("sample,fastq_1,fastq_2,reference\n")
        for sample, f1, f2 in rows:
            fh.write(f"{sample},{f1},{f2},\n")

    print(f"Wrote test data to {args.outdir}/ ({len(rows)} samples)")


if __name__ == "__main__":
    main()
