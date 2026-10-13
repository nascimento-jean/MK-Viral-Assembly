#!/usr/bin/env python3
"""Compare official and iterative second-pass consensus QC without replacing outputs."""

import argparse
import csv


def all_row(path):
    with open(path, encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    if not rows:
        raise ValueError(f"Empty QC table: {path}")
    return next((r for r in rows if r.get("segment") == "ALL"), rows[0])


def num(row, key):
    try:
        return float(row.get(key, 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def breadth(row):
    key = next((k for k in row if k.startswith("breadth_ge_")), "")
    return num(row, key) if key else 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", required=True)
    ap.add_argument("--first-qc", required=True)
    ap.add_argument("--second-qc", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--min-gain", type=float, default=0.005)
    ap.add_argument("--max-breadth-loss", type=float, default=0.01)
    args = ap.parse_args()
    first, second = all_row(args.first_qc), all_row(args.second_qc)
    c1, c2 = num(first, "completeness"), num(second, "completeness")
    b1, b2 = breadth(first), breadth(second)
    d1, d2 = num(first, "mean_depth"), num(second, "mean_depth")
    gain, loss = c2 - c1, b1 - b2
    if gain >= args.min_gain and loss <= args.max_breadth_loss:
        recommendation = "IMPROVED"
    elif loss > args.max_breadth_loss:
        recommendation = "REVIEW_BREADTH_REGRESSION"
    else:
        recommendation = "NO_MEANINGFUL_GAIN"
    columns = ["sample","round1_completeness","round2_completeness","completeness_gain",
               "round1_breadth","round2_breadth","breadth_loss","round1_mean_depth",
               "round2_mean_depth","recommendation"]
    values = [args.sample,f"{c1:.6f}",f"{c2:.6f}",f"{gain:.6f}",f"{b1:.6f}",
              f"{b2:.6f}",f"{loss:.6f}",f"{d1:.3f}",f"{d2:.3f}",recommendation]
    with open(args.output, "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(columns)
        writer.writerow(values)


if __name__ == "__main__":
    main()
