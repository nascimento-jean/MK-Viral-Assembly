#!/usr/bin/env python3
"""Convert SnpEff ANN fields to an auditable per-effect TSV."""

import argparse
import csv


ANN_FIELDS = [
    "allele", "effect", "impact", "gene", "gene_id", "feature_type",
    "feature_id", "transcript_biotype", "rank", "hgvs_c", "hgvs_p",
    "cdna_position", "cds_position", "protein_position", "distance", "warnings",
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", required=True)
    ap.add_argument("--vcf", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--status", default="OK")
    ap.add_argument("--message", default="")
    args = ap.parse_args()

    columns = ["sample", "chrom", "position", "ref", "alt"] + ANN_FIELDS + ["status", "message"]
    rows = []
    # SnpSift is a post-annotation FILTER selector. If only this optional
    # filtering step fails or is unavailable, the retained SnpEff VCF still
    # contains valid ANN fields and must remain visible with its warning.
    annotated_statuses = {"OK", "SNPSIFT_FAILED", "SNPSIFT_UNAVAILABLE"}
    if args.status in annotated_statuses:
        with open(args.vcf, encoding="utf-8-sig") as handle:
            for line in handle:
                if not line.strip() or line.startswith("#"):
                    continue
                fields = line.rstrip("\n").split("\t")
                if len(fields) < 8:
                    continue
                chrom, pos, _identifier, ref, alt, _qual, _flt, info = fields[:8]
                ann_value = ""
                for item in info.split(";"):
                    if item.startswith("ANN="):
                        ann_value = item[4:]
                        break
                for ann in ann_value.split(",") if ann_value else [""]:
                    values = ann.split("|") if ann else []
                    values += [""] * (len(ANN_FIELDS) - len(values))
                    row = [args.sample, chrom, pos, ref, alt] + values[:len(ANN_FIELDS)] + [args.status, args.message]
                    rows.append(row)
    if not rows:
        rows.append([args.sample, "", "", "", ""] + [""] * len(ANN_FIELDS) + [args.status, args.message or "No annotated effects"])

    with open(args.output, "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(columns)
        writer.writerows(rows)


if __name__ == "__main__":
    main()
