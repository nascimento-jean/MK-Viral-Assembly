#!/usr/bin/env python3
"""
annotate_aa.py  —  add a human-readable amino-acid change column to an iVar
variants table produced with `-g <gff>`.

iVar (>=1.4) already emits REF_AA, ALT_AA and POS_AA when a GFF is supplied.
This script turns those into the compact surveillance notation used in reports,
prefixed with the gene/feature name, e.g.:

    S:N501Y      (non-synonymous)
    ORF1a:M89V
    N:R203=      (synonymous; REF_AA == ALT_AA)

Rows outside any CDS (empty REF_AA/ALT_AA) and indels get an empty aa_change.
The gene label is taken from the GFF 'Name' attribute of the feature whose ID
matches GFF_FEATURE (falls back to the GFF_FEATURE id with common prefixes
stripped).

Pure standard library. Reads/writes TSV, preserving all original columns and
appending `aa_change` as the last column.

Usage:
    annotate_aa.py --in <ivar.tsv> --gff <ref.gff> --out <annotated.tsv>
"""
import argparse
import sys


def parse_gff_names(gff_path):
    """Map feature ID -> display Name from a GFF3 file."""
    id2name = {}
    if not gff_path:
        return id2name
    try:
        with open(gff_path) as fh:
            for line in fh:
                if not line.strip() or line.startswith("#"):
                    continue
                cols = line.rstrip("\n").split("\t")
                if len(cols) < 9:
                    continue
                attrs = {}
                for kv in cols[8].split(";"):
                    kv = kv.strip()
                    if "=" in kv:
                        k, v = kv.split("=", 1)
                        attrs[k.strip()] = v.strip()
                fid = attrs.get("ID")
                name = attrs.get("Name") or attrs.get("gene") or attrs.get("gene_name")
                if fid:
                    id2name[fid] = name or fid
    except OSError:
        pass
    return id2name


def gene_label(feature_id, id2name):
    """Human gene label for a GFF_FEATURE id."""
    if not feature_id or feature_id == "NA":
        return ""
    if feature_id in id2name:
        return id2name[feature_id]
    # strip common GFF id prefixes: cds-XXX, gene-XXX, rna-XXX
    for pref in ("cds-", "CDS-", "gene-", "rna-", "id-"):
        if feature_id.startswith(pref):
            return feature_id[len(pref):]
    return feature_id


def is_aa(x):
    return len(x) == 1 and x.isalpha()


def build_change(row, cols, id2name):
    def get(c):
        i = cols.get(c)
        return row[i].strip() if (i is not None and i < len(row)) else ""

    ref_aa = get("REF_AA")
    alt_aa = get("ALT_AA")
    pos_aa = get("POS_AA")
    feat = get("GFF_FEATURE")

    # need coding info + a valid residue number
    if not (is_aa(ref_aa) and is_aa(alt_aa) and pos_aa):
        return ""
    try:
        int(pos_aa)
    except ValueError:
        return ""

    gene = gene_label(feat, id2name)
    if ref_aa == alt_aa:
        core = f"{ref_aa}{pos_aa}="        # synonymous (HGVS-style)
    else:
        core = f"{ref_aa}{pos_aa}{alt_aa}"  # e.g. N501Y
    return f"{gene}:{core}" if gene else core


def main():
    ap = argparse.ArgumentParser(description="Add aa_change column to an iVar variants TSV.")
    ap.add_argument("--in", dest="inp", required=True, help="iVar variants TSV (with -g columns)")
    ap.add_argument("--gff", dest="gff", default=None, help="GFF3 used by iVar (for gene names)")
    ap.add_argument("--out", dest="out", required=True, help="output annotated TSV")
    args = ap.parse_args()

    id2name = parse_gff_names(args.gff)

    with open(args.inp) as fh:
        lines = fh.read().splitlines()

    if not lines:
        # empty input -> just create an empty output with the extra header
        with open(args.out, "w") as out:
            out.write("aa_change\n")
        return

    header = lines[0].split("\t")
    cols = {name: i for i, name in enumerate(header)}

    has_aa = "REF_AA" in cols and "ALT_AA" in cols and "POS_AA" in cols

    with open(args.out, "w") as out:
        out.write("\t".join(header + ["aa_change"]) + "\n")
        for line in lines[1:]:
            if not line:
                continue
            row = line.split("\t")
            change = build_change(row, cols, id2name) if has_aa else ""
            out.write("\t".join(row + [change]) + "\n")


if __name__ == "__main__":
    sys.exit(main())
