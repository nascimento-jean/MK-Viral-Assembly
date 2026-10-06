#!/usr/bin/env python3
"""Convert an iVar variants TSV into a standards-compliant, site-only VCF 4.2."""

import argparse
import csv
import math
import re


def number(value, default=None):
    try:
        parsed = float(str(value).strip())
        return parsed if math.isfinite(parsed) else default
    except (TypeError, ValueError):
        return default


def clean_info(value):
    return re.sub(r"[^A-Za-z0-9_.:|+\-]", "_", str(value or ""))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--source", default="MK-Viral-Assembly")
    args = parser.parse_args()

    with open(args.input, encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))

    with open(args.output, "w", encoding="utf-8", newline="") as out:
        out.write("##fileformat=VCFv4.2\n")
        out.write(f"##source={clean_info(args.source)}\n")
        out.write('##INFO=<ID=DP,Number=1,Type=Integer,Description="Total read depth">\n')
        out.write('##INFO=<ID=AF,Number=A,Type=Float,Description="Alternate allele frequency reported by iVar">\n')
        out.write('##INFO=<ID=AD,Number=A,Type=Integer,Description="Alternate allele depth">\n')
        out.write('##INFO=<ID=AA_CHANGE,Number=1,Type=String,Description="Annotated amino-acid change">\n')
        out.write('##FILTER=<ID=IVAR_FAIL,Description="iVar PASS column is not TRUE">\n')
        out.write("#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n")

        for row in rows:
            chrom = (row.get("REGION") or row.get("CHROM") or "").strip()
            pos = (row.get("POS") or "").strip()
            ref = (row.get("REF") or "").strip()
            alt = (row.get("ALT") or "").strip()
            if not (chrom and pos.isdigit() and ref and alt):
                continue
            alt_freq = number(row.get("ALT_FREQ"))
            depth = number(row.get("TOTAL_DP"))
            alt_depth = number(row.get("ALT_DP"))
            alt_qual = number(row.get("ALT_QUAL"))
            filt = "PASS" if str(row.get("PASS", "")).upper() == "TRUE" else "IVAR_FAIL"
            info = []
            if depth is not None:
                info.append(f"DP={int(depth)}")
            if alt_freq is not None:
                info.append(f"AF={alt_freq:.6g}")
            if alt_depth is not None:
                info.append(f"AD={int(alt_depth)}")
            aa = (row.get("aa_change") or "").strip()
            if aa:
                info.append("AA_CHANGE=" + clean_info(aa))
            qual = "." if alt_qual is None else f"{alt_qual:.6g}"
            out.write("\t".join([
                chrom, pos, ".", ref, alt, qual, filt, ";".join(info) or "."
            ]) + "\n")


if __name__ == "__main__":
    main()
