#!/usr/bin/env python3
"""Combine per-sample consensus FASTAs into run-level multi-FASTAs.

Emits:
  - one general multi-FASTA with every record from every (retained) sample
  - for segmented genomes, one multi-FASTA per segment

Segment detection relies on the header convention written by IVAR_CONSENSUS:
  >sample            -> single-segment genome (goes only to the general file)
  >sample|segment    -> segmented genome (also grouped into a per-segment file)

Quality filtering
-----------------
When a QC directory is supplied (--qc-dir), each sample is classified
PASS / WARN / FAIL from the whole-sample consensus completeness (the QC row
with segment == "ALL") using the same thresholds as the dashboard
(--pass / --warn). Samples whose status ranks below --min-status are left OUT
of the combined multi-FASTAs. By default FAIL samples are dropped and
PASS + WARN are kept, so the run-level FASTA carries only sequences fit for
downstream analysis (lineage assignment, phylogenetics). Per-sample consensus
FASTAs are never modified. Without --qc-dir every sample is included
(back-compatible behaviour).

Only the standard library is used so the module can run in a bare python image.
"""
import argparse
import os
import re
import sys


# status ranking used for the --min-status threshold (higher = better quality)
STATUS_RANK = {"FAIL": 0, "WARN": 1, "PASS": 2}


def read_tsv(path):
    with open(path) as fh:
        rows = [ln.rstrip("\n").split("\t") for ln in fh if ln.strip() != ""]
    if not rows:
        return [], []
    return rows[0], rows[1:]


def classify(completeness, pass_t, warn_t):
    try:
        c = float(completeness)
    except (TypeError, ValueError):
        return "FAIL"
    if c >= pass_t:
        return "PASS"
    if c >= warn_t:
        return "WARN"
    return "FAIL"


def load_qc_status(qc_dir, pass_t, warn_t):
    """Return {sample: status} from *.tsv QC tables (whole-sample 'ALL' row)."""
    status = {}
    if not qc_dir or not os.path.isdir(qc_dir):
        return status
    import glob
    for f in sorted(glob.glob(os.path.join(qc_dir, "*.tsv"))):
        header, rows = read_tsv(f)
        if not header:
            continue
        for r in rows:
            d = dict(zip(header, r))
            sample = d.get("sample")
            if not sample:
                continue
            segment = d.get("segment", "ALL")
            # prefer the whole-sample summary row; fall back to any row present
            if segment == "ALL" or sample not in status:
                status[sample] = classify(d.get("completeness", ""), pass_t, warn_t)
    return status


def read_fasta(path):
    """Yield (header, sequence_lines) tuples from a FASTA file.

    header is the full header line WITHOUT the leading '>'. sequence_lines is
    the list of raw sequence lines (newlines stripped) exactly as stored.
    """
    header = None
    seq = []
    with open(path) as fh:
        for line in fh:
            line = line.rstrip("\n")
            if line.startswith(">"):
                if header is not None:
                    yield header, seq
                header = line[1:]
                seq = []
            elif header is not None:
                seq.append(line)
        if header is not None:
            yield header, seq


def sanitize(token):
    """Make a token safe for use inside a filename."""
    return re.sub(r"[^A-Za-z0-9._-]", "_", token)


def write_records(path, records):
    with open(path, "w") as out:
        for header, seq in records:
            out.write(">" + header + "\n")
            for s in seq:
                out.write(s + "\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("fastas", nargs="*", help="per-sample *.consensus.fa files")
    ap.add_argument("--indir", help="directory to scan for *.consensus.fa "
                    "(used in addition to any positional files)")
    ap.add_argument("--run-name", default="", help="run label appended to output filenames")
    ap.add_argument("--outdir", default=".", help="where to write the combined FASTAs")
    ap.add_argument("--prefix", default="all_consensus", help="output filename prefix")
    ap.add_argument("--qc-dir", default=None,
                    help="directory of *.consensus_qc.tsv tables; enables quality "
                         "filtering of the combined FASTA(s)")
    ap.add_argument("--pass", dest="pass_t", type=float, default=0.90,
                    help="min completeness for PASS [0.90]")
    ap.add_argument("--warn", dest="warn_t", type=float, default=0.70,
                    help="min completeness for WARN [0.70]")
    ap.add_argument("--min-status", default="WARN", choices=["PASS", "WARN", "FAIL"],
                    help="lowest QC status kept in the combined FASTA(s); samples below "
                         "are excluded [WARN => drop FAIL, keep PASS+WARN]")
    args = ap.parse_args()

    inputs = list(args.fastas)
    if args.indir and os.path.isdir(args.indir):
        for fn in sorted(os.listdir(args.indir)):
            if fn.endswith(".consensus.fa") or fn.endswith(".consensus.fasta"):
                inputs.append(os.path.join(args.indir, fn))
    # de-duplicate while preserving order
    seen = set()
    inputs = [p for p in inputs if not (p in seen or seen.add(p))]

    if not inputs:
        sys.stderr.write("combine_consensus: no input FASTA files found\n")
        sys.exit(1)

    os.makedirs(args.outdir, exist_ok=True)

    suffix = ""
    run = args.run_name.strip()
    if run and run.lower() not in ("null", "none"):
        suffix = "." + sanitize(run)

    # optional QC-based filtering
    qc_status = load_qc_status(args.qc_dir, args.pass_t, args.warn_t)
    min_rank = STATUS_RANK[args.min_status]
    excluded = []             # (sample, status) dropped from the combined output

    def keep(sample):
        """True if `sample` should be included in the combined FASTA(s)."""
        if not qc_status:
            return True
        st = qc_status.get(sample)
        if st is None:        # no QC row -> keep, but flag
            sys.stderr.write(
                "combine_consensus: no QC status for '{}', keeping it\n".format(sample))
            return True
        if STATUS_RANK[st] < min_rank:
            excluded.append((sample, st))
            return False
        return True

    all_records = []          # every retained record, in input order
    per_segment = {}          # segment token -> list of retained records
    kept_samples = set()

    for path in sorted(inputs):
        for header, seq in read_fasta(path):
            sample = header.split("|", 1)[0].strip()
            if not keep(sample):
                continue
            kept_samples.add(sample)
            all_records.append((header, seq))
            if "|" in header:
                seg = header.split("|", 1)[1].strip()
                if seg:
                    per_segment.setdefault(seg, []).append((header, seq))

    # general multi-FASTA (always written)
    general = os.path.join(args.outdir, "{}{}.fasta".format(args.prefix, suffix))
    write_records(general, all_records)
    print("wrote {} ({} records from {} samples)".format(
        os.path.basename(general), len(all_records), len(kept_samples)))
    if qc_status:
        # de-duplicate excluded list (per-record loop may append a sample twice)
        seen_x = set()
        uniq_x = [(s, st) for s, st in excluded if not (s in seen_x or seen_x.add(s))]
        if uniq_x:
            print("excluded {} sample(s) below status '{}': {}".format(
                len(uniq_x), args.min_status,
                ", ".join("{} ({})".format(s, st) for s, st in uniq_x)))
            # leave an auditable side-car listing the dropped samples
            excl_path = os.path.join(args.outdir, "excluded_samples{}.txt".format(suffix))
            with open(excl_path, "w") as xf:
                xf.write("sample\tstatus\n")
                for s, st in uniq_x:
                    xf.write("{}\t{}\n".format(s, st))
        else:
            print("no samples excluded (all >= status '{}')".format(args.min_status))

    # per-segment multi-FASTAs (only when the run contains segmented genomes)
    for seg in sorted(per_segment):
        seg_path = os.path.join(
            args.outdir, "{}.{}{}.fasta".format(args.prefix, sanitize(seg), suffix))
        write_records(seg_path, per_segment[seg])
        print("wrote {} ({} records)".format(
            os.path.basename(seg_path), len(per_segment[seg])))


if __name__ == "__main__":
    main()
