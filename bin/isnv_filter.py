#!/usr/bin/env python3
"""Apply explicit, auditable filters to low-frequency iVar calls."""

import argparse
import csv
import math


def number(value, default=0.0):
    try:
        parsed = float(str(value).strip())
        return parsed if math.isfinite(parsed) else default
    except (TypeError, ValueError):
        return default


def integer(value):
    return int(round(number(value, 0.0)))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", required=True)
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--min-depth", type=int, default=100)
    parser.add_argument("--min-alt-reads", type=int, default=10)
    parser.add_argument("--min-frequency", type=float, default=0.02)
    parser.add_argument("--max-frequency", type=float, default=0.50)
    parser.add_argument("--min-quality", type=float, default=20.0)
    parser.add_argument("--min-strand-reads", type=int, default=3)
    parser.add_argument("--min-strand-balance", type=float, default=0.10)
    args = parser.parse_args()

    with open(args.input, encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))

    fields = [
        "sample", "contig", "position", "ref", "alt", "depth", "alt_depth",
        "alt_frequency", "alt_quality", "alt_forward", "alt_reverse",
        "strand_balance", "status", "filter_reasons",
    ]
    with open(args.output, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            contig = (row.get("REGION") or row.get("CHROM") or "").strip()
            position = (row.get("POS") or "").strip()
            ref = (row.get("REF") or "").strip()
            alt = (row.get("ALT") or "").strip()
            if not (contig and position and ref and alt):
                continue
            depth = integer(row.get("TOTAL_DP"))
            alt_depth = integer(row.get("ALT_DP"))
            alt_reverse = integer(row.get("ALT_RV"))
            alt_forward = max(0, alt_depth - alt_reverse)
            frequency = number(row.get("ALT_FREQ"))
            quality = number(row.get("ALT_QUAL"))
            balance = min(alt_forward, alt_reverse) / alt_depth if alt_depth else 0.0
            reasons = []
            if depth < args.min_depth:
                reasons.append("LOW_DEPTH")
            if alt_depth < args.min_alt_reads:
                reasons.append("LOW_ALT_READS")
            if frequency < args.min_frequency:
                reasons.append("LOW_FREQUENCY")
            if frequency > args.max_frequency:
                reasons.append("ABOVE_ISNV_RANGE")
            if quality < args.min_quality:
                reasons.append("LOW_ALT_QUALITY")
            if alt_forward < args.min_strand_reads:
                reasons.append("LOW_FORWARD_SUPPORT")
            if alt_reverse < args.min_strand_reads:
                reasons.append("LOW_REVERSE_SUPPORT")
            if balance < args.min_strand_balance:
                reasons.append("STRAND_BIAS")
            writer.writerow({
                "sample": args.sample, "contig": contig, "position": position,
                "ref": ref, "alt": alt, "depth": depth, "alt_depth": alt_depth,
                "alt_frequency": f"{frequency:.6f}", "alt_quality": f"{quality:.2f}",
                "alt_forward": alt_forward, "alt_reverse": alt_reverse,
                "strand_balance": f"{balance:.4f}",
                "status": "PASS" if not reasons else "REVIEW",
                "filter_reasons": ";".join(reasons) if reasons else "-",
            })


if __name__ == "__main__":
    main()
