#!/usr/bin/env python3
"""Consolidate one or more Nextclade TSV outputs into a single per-sample table.

Nextclade's column set varies by dataset (SARS-CoV-2 exposes 'clade' +
'Nextclade_pango'; Dengue/CHIKV expose 'clade'/'lineage'/'genotype'; RSV
exposes 'clade'). This reader is schema-flexible: it pulls whichever of the
known label columns are present and always carries Nextclade's own QC.

For segmented genomes (Oropouche) each input TSV is one segment (file name
nextclade.L.tsv / .M.tsv / .S.tsv); the per-segment lineage calls are merged
onto one row per sample as lineage_L / lineage_M / lineage_S.

Output columns:
  sample, segment, clade, lineage, genotype, pango,
  qc_status, total_substitutions, private_mutations, frameshifts, stop_codons,
  lineage_L, lineage_M, lineage_S   (last three only meaningful for Oropouche)
"""
import argparse, csv, glob, os, re

# candidate source columns (Nextclade varies these across datasets)
CLADE_KEYS   = ["clade", "Nextclade_clade", "clade_nextstrain"]
LINEAGE_KEYS = ["lineage", "Nextclade_pango", "pango_lineage", "outbreak", "subclade"]
GENO_KEYS    = ["genotype", "Genotype", "major_genotype"]
PANGO_KEYS   = ["Nextclade_pango", "pango_lineage"]
QC_KEYS      = ["qc.overallStatus", "qc_overallStatus", "qc.overallScore"]
SUBS_KEYS    = ["totalSubstitutions", "total_substitutions"]
PRIV_KEYS    = ["totalPrivateMutations", "privateNucMutations.totalPrivateSubstitutions"]
FS_KEYS      = ["totalFrameShifts", "qc.frameShifts.totalFrameShifts", "frameShifts"]
STOP_KEYS    = ["totalStopCodons", "qc.stopCodons.totalStopCodons", "qc.stopCodons.stopCodons"]


def first(row, keys):
    for k in keys:
        if k in row and row[k] not in (None, "", "NA"):
            return row[k]
    return ""


def read_tsv(path):
    with open(path, newline="") as fh:
        rd = csv.DictReader(fh, delimiter="\t")
        return list(rd)


def seg_from_filename(fn):
    # filenames are nextclade.<group>.<seg>.tsv (seg = L/M/S/ALL); the segment is
    # always the last dotted token before .tsv, regardless of the group token.
    m = re.search(r"\.([A-Za-z]+)\.tsv$", os.path.basename(fn))
    if m:
        s = m.group(1).upper()
        return s if s in ("L", "M", "S", "ALL") else "ALL"
    return "ALL"


def sample_name(row):
    return (row.get("seqName") or row.get("seqname") or "").split("|", 1)[0].strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--nextclade-dir", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    files = sorted(glob.glob(os.path.join(args.nextclade_dir, "*.tsv")))
    # per-sample accumulator
    samples = {}      # sample -> dict of fields
    seg_lineage = {}  # sample -> {L:..,M:..,S:..}
    sample_seg = {}   # sample -> set of segments it appeared in (per-sample decision)

    for f in files:
        seg = seg_from_filename(f)
        for row in read_tsv(f):
            smp = sample_name(row)
            if not smp:
                continue
            sample_seg.setdefault(smp, set()).add(seg)
            rec = samples.setdefault(smp, {
                "sample": smp, "segment": "",
                "clade": "", "lineage": "", "genotype": "", "pango": "",
                "qc_status": "", "total_substitutions": "", "private_mutations": "",
                "frameshifts": "", "stop_codons": "",
            })
            clade = first(row, CLADE_KEYS)
            lin   = first(row, LINEAGE_KEYS)
            geno  = first(row, GENO_KEYS)
            if seg in ("L", "M", "S"):
                seg_lineage.setdefault(smp, {"L": "", "M": "", "S": ""})
                # prefer lineage, fall back to clade/genotype for the segment label
                seg_lineage[smp][seg] = lin or clade or geno or ""
            else:
                # non-segmented: fill main fields (first non-empty wins)
                if clade and not rec["clade"]:   rec["clade"] = clade
                if lin and not rec["lineage"]:   rec["lineage"] = lin
                if geno and not rec["genotype"]: rec["genotype"] = geno
                p = first(row, PANGO_KEYS)
                if p and not rec["pango"]:       rec["pango"] = p
            # QC always carried (take worst status across segments/rows)
            qc = first(row, QC_KEYS)
            if qc:
                order = {"good": 0, "mediocre": 1, "bad": 2}
                if not rec["qc_status"] or order.get(qc.lower(), 0) > order.get(rec["qc_status"].lower(), 0):
                    rec["qc_status"] = qc
            for dst, keys in (("total_substitutions", SUBS_KEYS),
                              ("private_mutations", PRIV_KEYS),
                              ("frameshifts", FS_KEYS),
                              ("stop_codons", STOP_KEYS)):
                v = first(row, keys)
                if v and not rec[dst]:
                    rec[dst] = v

    # per-sample segmentation: a sample is segmented if it appeared in any L/M/S file
    def is_seg(smp):
        return bool(sample_seg.get(smp, set()) & {"L", "M", "S"})

    any_segmented = any(is_seg(s) for s in samples)

    cols = ["sample", "segment", "clade", "lineage", "genotype", "pango",
            "qc_status", "total_substitutions", "private_mutations",
            "frameshifts", "stop_codons"]
    if any_segmented:
        cols += ["lineage_L", "lineage_M", "lineage_S"]

    with open(args.out, "w", newline="") as fh:
        w = csv.writer(fh, delimiter="\t", lineterminator="\n")
        w.writerow(cols)
        for smp in sorted(samples):
            rec = samples[smp]
            if is_seg(smp):
                rec["segment"] = "L/M/S"
                sl = seg_lineage.get(smp, {})
                rec["lineage_L"] = sl.get("L", "")
                rec["lineage_M"] = sl.get("M", "")
                rec["lineage_S"] = sl.get("S", "")
            else:
                segset = sample_seg.get(smp, {"ALL"})
                rec["segment"] = next(iter(segset)) if segset else "ALL"
            w.writerow([rec.get(c, "") for c in cols])

    print(f"nextclade_summary: {len(samples)} sample(s) from {len(files)} TSV(s) "
          f"[{sum(1 for s in samples if is_seg(s))} segmented] -> {args.out}")


if __name__ == "__main__":
    main()
