#!/usr/bin/env python3
"""Build an MK_Viral-Assembly samplesheet from folders of paired FASTQ files.

Pairs R1/R2 by sample and writes the CSV the pipeline expects:

    sample,fastq_1,fastq_2,virus,reference,gff,bed_file,nextclade_dataset

The per-virus columns (reference, gff, bed_file, nextclade_dataset) are filled
by looking the virus name up in a catalog TSV (assets/virus_catalog.tsv), so
you type the paths once and reuse them every run.

Two scan modes
--------------
1. Single-virus (one folder, one virus):

       python3 bin/make_samplesheet.py -i /data/run17/chikv \
           --virus chikv -o samplesheet.csv

2. Multi-virus PARENT mode (one subfolder per virus, name = virus):

       /data/run17/
         |- chikv/   R1/R2 fastqs ...
         |- denv2/   R1/R2 fastqs ...
         `- orov/    R1/R2 fastqs ...

       python3 bin/make_samplesheet.py --parent /data/run17 -o samplesheet.csv

   Each subfolder name is looked up in the catalog. Subfolders whose name is
   not in the catalog are skipped with a warning.

Overrides
---------
Catalog values can be overridden on the command line (applied to every sample):
--reference, --gff, --bed-file, --nextclade-dataset. An explicit --virus with
no catalog match is allowed as long as at least --reference is supplied.

Paired-end only. Paths are written absolute unless --relative. Stdlib only.
"""
import argparse
import os
import re
import sys
from glob import glob


FASTQ_EXTS = (".fastq.gz", ".fq.gz", ".fastq", ".fq")
CATALOG_COLS = ("virus", "reference", "gff", "bed_file", "nextclade_dataset")


def strip_ext(name):
    for ext in FASTQ_EXTS:
        if name.endswith(ext):
            return name[: -len(ext)], ext
    return name, ""


def find_fastqs(indir):
    files = []
    for ext in FASTQ_EXTS:
        files.extend(glob(os.path.join(indir, f"*{ext}")))
    return sorted(set(files))


def infer_sample_id(stem, mate_token):
    """Remove the mate token and any trailing lane token to get the sample id."""
    s = stem
    idx = s.rfind(mate_token)
    if idx != -1:
        s = s[:idx] + s[idx + len(mate_token):]
    s = re.sub(r"_L?0*\d+$", "", s)
    s = re.sub(r"_S\d+$", "", s)
    s = s.rstrip("._-")
    return s or stem


def load_catalog(path):
    """Parse virus_catalog.tsv (TAB or comma). Returns {virus_lower: {col: val}}.

    Lines starting with # and blank lines are ignored. A header row containing
    'virus' is detected and skipped. Missing trailing fields => empty string.
    """
    if not path or not os.path.isfile(path):
        return {}
    catalog = {}
    with open(path) as fh:
        for raw in fh:
            line = raw.rstrip("\n")
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            delim = "\t" if "\t" in line else ","
            parts = [p.strip() for p in line.split(delim)]
            if parts[0].lower() == "virus":
                continue  # header
            row = {}
            for i, col in enumerate(CATALOG_COLS):
                row[col] = parts[i] if i < len(parts) else ""
            catalog[row["virus"].lower()] = row
    return catalog


def pair_fastqs(indir, token_pairs, fmt):
    """Return (rows, incomplete, unpaired) for one folder.

    rows: list of (sample_id, fastq_1, fastq_2). Paths passed through fmt().
    """
    files = find_fastqs(indir)
    samples, unpaired = {}, []
    for path in files:
        base = os.path.basename(path)
        stem, _ = strip_ext(base)
        matched = False
        for r1t, r2t in token_pairs:
            if r1t in stem:
                sid = infer_sample_id(stem, r1t)
                samples.setdefault(sid, {})["1"] = path
                matched = True
                break
            if r2t in stem:
                sid = infer_sample_id(stem, r2t)
                samples.setdefault(sid, {})["2"] = path
                matched = True
                break
        if not matched:
            unpaired.append(base)
    rows, incomplete = [], []
    for sid in sorted(samples):
        d = samples[sid]
        if "1" in d and "2" in d:
            rows.append((sid, fmt(d["1"]), fmt(d["2"])))
        else:
            incomplete.append((sid, d))
    return rows, incomplete, unpaired


def resolve_virus_fields(virus, catalog, overrides):
    """Merge catalog entry for `virus` with CLI overrides. Returns dict or None."""
    entry = dict(catalog.get(virus.lower(), {})) if virus else {}
    if not entry and virus:
        entry = {"virus": virus, "reference": "", "gff": "", "bed_file": "",
                 "nextclade_dataset": ""}
    for k, v in overrides.items():
        if v:
            entry[k] = v
    entry.setdefault("virus", virus)
    return entry


def main():
    ap = argparse.ArgumentParser(
        description="Build an MK_Viral-Assembly samplesheet (single-virus or --parent multi-virus).")
    ap.add_argument("-i", "--indir", help="folder with FASTQs for ONE virus (use with --virus)")
    ap.add_argument("--parent", help="parent folder whose subfolders are named by virus")
    ap.add_argument("-o", "--out", default="samplesheet.csv", help="output CSV [samplesheet.csv]")
    ap.add_argument("--virus", default="", help="virus name for single-folder mode (catalog key)")
    ap.add_argument("--catalog", default=None,
                    help="virus catalog TSV [assets/virus_catalog.tsv next to this script]")
    ap.add_argument("--reference", default="", help="override reference FASTA for every sample")
    ap.add_argument("--gff", default="", help="override GFF3 for every sample")
    ap.add_argument("--bed-file", default="", help="override primer BED for every sample")
    ap.add_argument("--nextclade-dataset", default="", help="override Nextclade dataset for every sample")
    ap.add_argument("--r1-token", default=None, help="explicit R1 token (e.g. _R1 or _1). Auto if omitted.")
    ap.add_argument("--r2-token", default=None, help="explicit R2 token (e.g. _R2 or _2). Auto if omitted.")
    ap.add_argument("--relative", action="store_true", help="write relative paths instead of absolute")
    args = ap.parse_args()

    if not args.indir and not args.parent:
        sys.exit("ERROR: give either -i/--indir (single virus) or --parent (multi-virus).")
    if args.indir and args.parent:
        sys.exit("ERROR: use -i/--indir OR --parent, not both.")

    # locate catalog: explicit --catalog, else assets/virus_catalog.tsv relative to bin/
    if args.catalog:
        catalog_path = args.catalog
    else:
        here = os.path.dirname(os.path.abspath(__file__))
        catalog_path = os.path.join(here, os.pardir, "assets", "virus_catalog.tsv")
    catalog = load_catalog(catalog_path)

    token_pairs = ([(args.r1_token, args.r2_token)] if args.r1_token and args.r2_token
                   else [("_R1", "_R2"), ("_1", "_2"), (".R1", ".R2"), (".1", ".2")])

    def fmt(p):
        return p if args.relative else os.path.abspath(p)

    overrides = {"reference": args.reference, "gff": args.gff,
                 "bed_file": args.bed_file, "nextclade_dataset": args.nextclade_dataset}

    # build list of (virus, folder) jobs
    jobs = []
    if args.parent:
        if not os.path.isdir(args.parent):
            sys.exit(f"ERROR: not a directory: {args.parent}")
        for name in sorted(os.listdir(args.parent)):
            sub = os.path.join(args.parent, name)
            if os.path.isdir(sub):
                jobs.append((name, sub))
        if not jobs:
            sys.exit(f"ERROR: no subfolders found under {args.parent}")
    else:
        if not os.path.isdir(args.indir):
            sys.exit(f"ERROR: not a directory: {args.indir}")
        if not args.virus and not args.reference:
            sys.exit("ERROR: single-folder mode needs --virus (catalog lookup) or --reference.")
        jobs.append((args.virus, args.indir))

    all_rows = []          # (sid, f1, f2, fields)
    warnings = []
    seen_samples = {}      # sid -> folder (detect cross-virus id clashes)

    for virus, folder in jobs:
        fields = resolve_virus_fields(virus, catalog, overrides)
        if virus and virus.lower() not in catalog and not args.reference and not fields.get("reference"):
            warnings.append(f"skip '{virus}': not in catalog and no --reference given ({folder})")
            continue
        rows, incomplete, unpaired = pair_fastqs(folder, token_pairs, fmt)
        if not rows:
            warnings.append(f"no complete R1/R2 pairs in {folder}")
        for sid, f1, f2 in rows:
            key = sid
            if key in seen_samples:
                # disambiguate by prefixing the virus to avoid a duplicate sample id
                key = f"{virus}_{sid}" if virus else sid
            seen_samples[key] = folder
            all_rows.append((key, f1, f2, fields))
        for sid, d in incomplete:
            warnings.append(f"{folder}: sample '{sid}' had only one mate, skipped")
        for b in unpaired:
            warnings.append(f"{folder}: '{b}' matched no R1/R2 token, ignored")

    if not all_rows:
        msg = "ERROR: no complete R1/R2 pairs were found.\n" + "\n".join(warnings)
        sys.exit(msg)

    header = "sample,fastq_1,fastq_2,virus,reference,gff,bed_file,nextclade_dataset\n"
    with open(args.out, "w") as fh:
        fh.write(header)
        for sid, f1, f2, fi in all_rows:
            fh.write(",".join([sid, f1, f2, fi.get("virus", ""), fi.get("reference", ""),
                               fi.get("gff", ""), fi.get("bed_file", ""),
                               fi.get("nextclade_dataset", "")]) + "\n")

    print(f"Wrote {len(all_rows)} sample(s) to {args.out}")
    by_virus = {}
    for sid, _, _, fi in all_rows:
        by_virus.setdefault(fi.get("virus", "?"), []).append(sid)
    for v in sorted(by_virus):
        print(f"  [{v}] {len(by_virus[v])} sample(s): {', '.join(by_virus[v])}")
    if warnings:
        print("\nNotes/warnings:", file=sys.stderr)
        for w in warnings:
            print(f"  - {w}", file=sys.stderr)


if __name__ == "__main__":
    main()
