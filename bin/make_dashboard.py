#!/usr/bin/env python3
"""Build a single self-contained HTML surveillance dashboard for a run.

Reads the per-sample consensus-QC tables and the iVar variant tables produced
by the viral-assembly pipeline and writes ONE portable HTML file (no server, no
CDN, no external assets) summarising the whole run.

The report is organised into tabs:

  - Overview  : cards, PASS/WARN/FAIL donut, completeness/depth histograms,
                and aggregate statistics
  - Samples   : sortable, filterable per-sample metrics table
  - Coverage  : completeness and mean-depth bars per sample
  - Mutations : recurrent amino-acid changes, gene-level burden, and
                per-sample detail (when GFF annotation is available)
  - Segments  : per-segment metrics (for segmented viruses only)

All charts are drawn as inline SVG in pure Python, so the script needs only
the standard library and runs in the same minimal python container as the QC
step. Tabs use a few lines of vanilla JS (with a <noscript> fallback that
reveals every panel).

Usage
-----
    make_dashboard.py --qc-dir consensus_qc/ --variants-dir variants/ \
        --out surveillance_dashboard.html --run-name "Run 17" \
        --pass 0.90 --warn 0.70 --min-cov 20
"""
import argparse
import datetime as _dt
import glob
import html
import math
import os
import sys
from collections import Counter, defaultdict


# ----------------------------------------------------------------------------- parsing
def read_tsv(path):
    with open(path) as fh:
        rows = [ln.rstrip("\n").split("\t") for ln in fh if ln.strip() != ""]
    if not rows:
        return [], []
    header = rows[0]
    return header, rows[1:]


def load_qc(qc_dir):
    """Return {sample: {"ALL": rowdict, segments: [rowdict,...]}} from QC TSVs."""
    files = sorted(glob.glob(os.path.join(qc_dir, "*.tsv")))
    samples = {}
    breadth_key = None
    for f in files:
        header, rows = read_tsv(f)
        if not header:
            continue
        for r in rows:
            d = dict(zip(header, r))
            for k in header:
                if k.startswith("breadth_ge_"):
                    breadth_key = k
            sample = d.get("sample", os.path.basename(f))
            segment = d.get("segment", "ALL")
            samples.setdefault(sample, {"ALL": None, "segments": []})
            if segment == "ALL":
                samples[sample]["ALL"] = d
            else:
                samples[sample]["segments"].append(d)
        # back-compat: old QC files had no 'segment' column
        if "segment" not in header:
            for r in rows:
                d = dict(zip(header, r))
                sample = d.get("sample", os.path.basename(f))
                samples.setdefault(sample, {"ALL": None, "segments": []})
                samples[sample]["ALL"] = d
    return samples, (breadth_key or "breadth")


def load_variants(variants_dir):
    """Return {sample: {"total": int, "by_segment": {region: int}, "aa": [...]}}."""
    out = {}
    if not variants_dir or not os.path.isdir(variants_dir):
        return out
    for f in sorted(glob.glob(os.path.join(variants_dir, "*.tsv"))):
        base = os.path.basename(f)
        # strip common suffixes to recover the sample id
        sample = base
        for suf in (".variants.tsv", ".tsv"):
            if sample.endswith(suf):
                sample = sample[: -len(suf)]
                break
        header, rows = read_tsv(f)
        if not header:
            out[sample] = {"total": 0, "by_segment": {}, "aa": []}
            continue
        idx = {c: i for i, c in enumerate(header)}
        pass_i = idx.get("PASS")
        reg_i = idx.get("REGION")
        aa_i = idx.get("aa_change")   # present only when a GFF was supplied
        total = 0
        by_seg = {}
        aa_muts = []          # ordered, de-duplicated amino-acid changes (non-synonymous)
        aa_seen = set()
        seen = set()
        for r in rows:
            # a variant row can repeat POS for codon annotation; de-dup on REGION+POS+ALT
            reg = r[reg_i] if reg_i is not None and reg_i < len(r) else "NA"
            pos = r[idx["POS"]] if "POS" in idx and idx["POS"] < len(r) else ""
            alt = r[idx["ALT"]] if "ALT" in idx and idx["ALT"] < len(r) else ""
            is_pass = True
            if pass_i is not None and pass_i < len(r):
                is_pass = str(r[pass_i]).upper() in ("TRUE", "T", "1")
            if not is_pass:
                continue
            key = (reg, pos, alt)
            if key in seen:
                continue
            seen.add(key)
            total += 1
            by_seg[reg] = by_seg.get(reg, 0) + 1
            # collect amino-acid change (skip synonymous "=" and empties)
            if aa_i is not None and aa_i < len(r):
                aa = r[aa_i].strip()
                if aa and not aa.endswith("=") and aa not in aa_seen:
                    aa_seen.add(aa)
                    aa_muts.append(aa)
        out[sample] = {"total": total, "by_segment": by_seg, "aa": aa_muts}
    return out


def load_mixed_sites(mixed_dir):
    """Read *.mixed_sites.tsv -> {sample: {covered, n_mixed, per_kb, max_freq}}.

    Produced by the MIXED_SITES module: intra-sample heterozygosity screen
    (ambiguous-frequency positions = contamination / co-infection signal).
    """
    out = {}
    if not mixed_dir or not os.path.isdir(mixed_dir):
        return out
    for fn in sorted(os.listdir(mixed_dir)):
        if not fn.endswith(".mixed_sites.tsv"):
            continue
        header, rows = read_tsv(os.path.join(mixed_dir, fn))
        if not rows:
            continue
        r = dict(zip(header, rows[0]))
        out[r.get("sample", fn.replace(".mixed_sites.tsv", ""))] = {
            "covered": r.get("covered_positions", "0"),
            "n_mixed": r.get("n_mixed_sites", "0"),
            "per_kb": r.get("mixed_per_kb", "0"),
            "max_freq": r.get("max_minor_freq", "0"),
        }
    return out


def load_taxonomy(tax_file):
    """Read the taxonomy_summary.py table -> {sample: {..pct fields..}}."""
    out = {}
    if not tax_file or not os.path.isfile(tax_file):
        return out
    header, rows = read_tsv(tax_file)
    for row in rows:
        r = dict(zip(header, row))
        sid = r.get("sample")
        if sid:
            out[sid] = r
    return out


def load_nextclade(nc_file):
    """Read nextclade_summary.tsv -> {sample: {..fields..}}. Empty if missing."""
    out = {}
    if not nc_file or not os.path.isfile(nc_file):
        return out
    header, rows = read_tsv(nc_file)
    for row in rows:
        r = dict(zip(header, row))
        sid = r.get("sample")
        if sid:
            out[sid] = r
    return out


def load_blast(blast_file):
    """Read blast_summary.tsv -> {sample: {..fields..}}. Empty if missing.
    If multiple segments per sample, keep the best-covered hit for the summary cell."""
    out = {}
    if not blast_file or not os.path.isfile(blast_file):
        return out
    header, rows = read_tsv(blast_file)
    for row in rows:
        r = dict(zip(header, row))
        sid = r.get("sample")
        if not sid:
            continue
        prev = out.get(sid)
        if prev is None or ffloat(r.get("coverage", 0)) > ffloat(prev.get("coverage", 0)):
            out[sid] = r
    return out


def load_read_stats(rs_dir):
    """Read *.read_stats.tsv -> {sample: {reads_raw, reads_post_fastp,
    reads_post_deplete}}. Empty dict if the directory is absent."""
    out = {}
    if not rs_dir or not os.path.isdir(rs_dir):
        return out
    for f in sorted(glob.glob(os.path.join(rs_dir, "*.tsv"))):
        header, rows = read_tsv(f)
        for row in rows:
            r = dict(zip(header, row))
            sid = r.get("sample")
            if sid:
                out[sid] = r
    return out


def load_validation(validation_dir):
    """Read *.sample_validation.tsv -> {sample: validation row}.

    These rows are produced before any heavy processing step. They include
    samples skipped because the input FASTQs were empty/truncated/unreadable and
    mark CN* samples as negative controls for run-level validation.
    """
    out = {}
    if not validation_dir or not os.path.isdir(validation_dir):
        return out
    for f in sorted(glob.glob(os.path.join(validation_dir, "*.sample_validation.tsv"))):
        header, rows = read_tsv(f)
        for row in rows:
            r = dict(zip(header, row))
            sid = r.get("sample")
            if sid:
                out[sid] = r
    return out


# ----------------------------------------------------------------------------- helpers
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


def fnum(x, nd=1):
    try:
        return f"{float(x):.{nd}f}"
    except (TypeError, ValueError):
        return "-"


def fint(x):
    """Integer with a thin-space thousands separator (e.g. 1 234 567).
    The table sorter strips spaces before parseFloat, so this stays sortable."""
    try:
        return f"{int(float(x)):,}".replace(",", "\u2009")
    except (TypeError, ValueError):
        return "-"


def pct(x):
    try:
        return f"{float(x) * 100:.1f}%"
    except (TypeError, ValueError):
        return "-"


def ffloat(x, default=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def human_join(items):
    items = [str(x) for x in items if str(x)]
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " and " + items[-1]


def median(vals):
    xs = sorted(v for v in vals if v is not None)
    if not xs:
        return 0.0
    n = len(xs)
    mid = n // 2
    return xs[mid] if n % 2 else (xs[mid - 1] + xs[mid]) / 2.0


# ----------------------------------------------------------------------------- svg charts
def svg_barchart(labels, values, title, unit="", is_pct=False, colors=None, width=680):
    """Horizontal bar chart as inline SVG. values are floats."""
    if not labels:
        return "<p class='muted'>(no data)</p>"
    row_h = 26
    pad_left = 150
    pad_right = 74
    pad_top = 34
    pad_bottom = 12
    plot_w = width - pad_left - pad_right
    height = pad_top + pad_bottom + row_h * len(labels)
    vmax = max(values) if values and max(values) > 0 else 1.0
    if is_pct:
        vmax = 1.0
    parts = [f'<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" '
             f'role="img" style="max-width:100%;height:auto;font-family:inherit">']
    parts.append(f'<text x="8" y="20" font-size="14" font-weight="600" fill="#1a2b4a">{html.escape(title)}</text>')
    for i, (lab, val) in enumerate(zip(labels, values)):
        y = pad_top + i * row_h
        bar_w = (val / vmax) * plot_w if vmax else 0
        color = (colors[i] if colors else "#2b6cb0")
        parts.append(
            f'<text x="{pad_left - 8}" y="{y + row_h/2 + 4}" font-size="12" '
            f'text-anchor="end" fill="#333">{html.escape(str(lab))}</text>'
        )
        parts.append(
            f'<rect x="{pad_left}" y="{y + 4}" width="{bar_w:.1f}" height="{row_h - 10}" '
            f'rx="2" fill="{color}"><title>{html.escape(str(lab))}: {val}</title></rect>'
        )
        vlabel = pct(val) if is_pct else (fnum(val, 0) + unit)
        parts.append(
            f'<text x="{pad_left + bar_w + 6:.1f}" y="{y + row_h/2 + 4}" font-size="11" '
            f'fill="#555">{html.escape(vlabel)}</text>'
        )
    parts.append("</svg>")
    return "".join(parts)


def svg_vbars(labels, values, title, colors=None, width=460, unit=""):
    """Vertical bar chart / histogram as inline SVG."""
    if not labels:
        return "<p class='muted'>(no data)</p>"
    n = len(values)
    pad_left = 40
    pad_right = 14
    pad_top = 34
    pad_bottom = 52
    plot_h = 160
    height = pad_top + plot_h + pad_bottom
    area_w = width - pad_left - pad_right
    slot = area_w / n
    bar_w = slot * 0.68
    vmax = max(values) if values and max(values) > 0 else 1.0
    baseline = pad_top + plot_h
    parts = [f'<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" '
             f'role="img" style="max-width:100%;height:auto;font-family:inherit">']
    parts.append(f'<text x="8" y="20" font-size="14" font-weight="600" fill="#1a2b4a">{html.escape(title)}</text>')
    # horizontal gridlines (0, half, max)
    for gv in (0, vmax / 2.0, vmax):
        gy = baseline - (gv / vmax) * plot_h if vmax else baseline
        parts.append(f'<line x1="{pad_left}" y1="{gy:.1f}" x2="{width - pad_right}" y2="{gy:.1f}" '
                     f'stroke="#edf2f7" stroke-width="1"/>')
        parts.append(f'<text x="{pad_left - 6}" y="{gy + 4:.1f}" font-size="10" '
                     f'text-anchor="end" fill="#999">{gv:.0f}</text>')
    for i, (lab, val) in enumerate(zip(labels, values)):
        x = pad_left + i * slot + (slot - bar_w) / 2.0
        bh = (val / vmax) * plot_h if vmax else 0
        y = baseline - bh
        color = (colors[i] if colors else "#2b6cb0")
        parts.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" height="{bh:.1f}" rx="2" '
            f'fill="{color}"><title>{html.escape(str(lab))}: {val}{unit}</title></rect>'
        )
        if val:
            parts.append(
                f'<text x="{x + bar_w/2:.1f}" y="{y - 4:.1f}" font-size="10.5" '
                f'text-anchor="middle" fill="#555">{val:.0f}</text>'
            )
        parts.append(
            f'<text x="{x + bar_w/2:.1f}" y="{baseline + 14:.1f}" font-size="10.5" '
            f'text-anchor="middle" fill="#444">{html.escape(str(lab))}</text>'
        )
    parts.append("</svg>")
    return "".join(parts)


def svg_donut(items, size=190, thickness=34):
    """Donut chart from items = [(label, value, color), ...]."""
    total = sum(v for _, v, _ in items)
    r = (size - thickness) / 2.0
    cx = cy = size / 2.0
    circ = 2 * math.pi * r
    parts = [f'<svg viewBox="0 0 {size} {size}" xmlns="http://www.w3.org/2000/svg" '
             f'role="img" style="width:{size}px;max-width:100%;height:auto">']
    parts.append(f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="#edf2f7" '
                 f'stroke-width="{thickness}"/>')
    if total > 0:
        offset = 0.0
        for label, val, color in items:
            if val <= 0:
                continue
            seg = (val / total) * circ
            parts.append(
                f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{color}" '
                f'stroke-width="{thickness}" stroke-dasharray="{seg:.2f} {circ - seg:.2f}" '
                f'stroke-dashoffset="{-offset:.2f}" transform="rotate(-90 {cx} {cy})">'
                f'<title>{html.escape(label)}: {val} ({val/total*100:.0f}%)</title></circle>'
            )
            offset += seg
    parts.append(f'<text x="{cx}" y="{cy - 2}" font-size="30" font-weight="700" '
                 f'text-anchor="middle" fill="#1a2b4a">{total}</text>')
    parts.append(f'<text x="{cx}" y="{cy + 18}" font-size="12" text-anchor="middle" '
                 f'fill="#667">samples</text>')
    parts.append("</svg>")
    return "".join(parts)


# ----------------------------------------------------------------------------- html
BADGE_COLORS = {"PASS": "#2f855a", "WARN": "#b7791f", "FAIL": "#c53030"}
BAR_COLORS = {"PASS": "#38a169", "WARN": "#d69e2e", "FAIL": "#e53e3e"}


def _hist(values, edges, labels):
    """Bin `values` into len(labels) buckets defined by edges (upper bounds)."""
    counts = [0] * len(labels)
    for v in values:
        placed = False
        for i, up in enumerate(edges):
            if v < up:
                counts[i] += 1
                placed = True
                break
        if not placed:
            counts[-1] += 1
    return counts


def svg_heatmap(row_labels, col_labels, matrix, title,
                row_counts=None, legend_max=None, cell=18, pad_left=200, pad_top=104):
    """Presence/recurrence heatmap as a self-contained SVG string.

    matrix[r][c] truthy  -> cell filled; falsy -> empty.
    Filled cells are coloured on a light->dark blue scale by row_counts[r]
    (the recurrence, i.e. number of samples carrying that mutation); with
    legend_max giving the darkest anchor.  Column labels are rotated -60deg.
    """
    nrow, ncol = len(row_labels), len(col_labels)
    if nrow == 0 or ncol == 0:
        return '<p class="muted">No data available for the heatmap.</p>'
    if row_counts is None:
        row_counts = [1] * nrow
    lmax = legend_max if (legend_max and legend_max > 1) else max(row_counts + [1])

    def color(cnt):
        t = 0.0 if lmax <= 1 else (cnt - 1) / (lmax - 1)
        t = max(0.0, min(1.0, t))
        c0 = (0xcf, 0xe3, 0xf7)   # light blue (low recurrence)
        c1 = (0x1a, 0x4e, 0x8a)   # dark blue (high recurrence)
        r = int(c0[0] + (c1[0] - c0[0]) * t)
        g = int(c0[1] + (c1[1] - c0[1]) * t)
        b = int(c0[2] + (c1[2] - c0[2]) * t)
        return f"#{r:02x}{g:02x}{b:02x}"

    grid_w, grid_h = ncol * cell, nrow * cell
    legend_h = 46
    width = pad_left + grid_w + 26
    height = pad_top + grid_h + legend_h + 12
    esc = html.escape
    P = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
         f'viewBox="0 0 {width} {height}" font-family="system-ui,Segoe UI,Roboto,sans-serif" '
         f'role="img" style="max-width:100%;height:auto">']
    P.append(f'<text x="0" y="20" font-size="15" font-weight="700" fill="#1a202c">{esc(title)}</text>')
    # column headers (rotated)
    for c, cl in enumerate(col_labels):
        cx = pad_left + c * cell + cell / 2
        P.append(f'<text x="{cx:.1f}" y="{pad_top - 6}" font-size="10.5" fill="#4a5568" '
                 f'text-anchor="start" transform="rotate(-60 {cx:.1f} {pad_top - 6})">{esc(cl)}</text>')
    # rows
    for r, rl in enumerate(row_labels):
        ry = pad_top + r * cell
        P.append(f'<text x="{pad_left - 8}" y="{ry + cell/2 + 3.5:.1f}" font-size="11" '
                 f'fill="#2d3748" text-anchor="end" font-family="ui-monospace,Menlo,monospace">{esc(rl)}</text>')
        for c in range(ncol):
            x = pad_left + c * cell
            filled = bool(matrix[r][c])
            fill = color(row_counts[r]) if filled else "#eef2f6"
            P.append(f'<rect x="{x}" y="{ry}" width="{cell-2}" height="{cell-2}" rx="2" '
                     f'fill="{fill}" stroke="#dbe2ea" stroke-width="0.6"><title>'
                     f'{esc(rl)} — {esc(col_labels[c])}: {"present" if filled else "absent"}</title></rect>')
    # legend (light-to-dark gradient = recurrence 1..lmax)
    ly = pad_top + grid_h + 24
    P.append(f'<text x="0" y="{ly-6}" font-size="11" fill="#4a5568">'
             f'Color = recurrence (number of samples): light = 1, dark = {lmax}</text>')
    steps = 24
    for i in range(steps):
        cnt = 1 + (lmax - 1) * i / (steps - 1) if lmax > 1 else 1
        P.append(f'<rect x="{i*10}" y="{ly}" width="10" height="12" fill="{color(cnt)}"/>')
    P.append(f'<text x="0" y="{ly+26}" font-size="10" fill="#718096">1</text>')
    P.append(f'<text x="{steps*10}" y="{ly+26}" font-size="10" fill="#718096" text-anchor="end">{lmax}</text>')
    P.append('</svg>')
    return "".join(P)


def build_html(run_name, samples, variants, breadth_key, pass_t, warn_t, min_cov,
               mixed=None, taxonomy=None, krona_rel=None, nextclade=None, blast=None,
               nextclade_info=None, blast_info=None, read_stats=None,
               validation=None, validation_krona_rel=None):
    now = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    sample_ids = sorted(samples.keys())
    mixed = mixed or {}
    taxonomy = taxonomy or {}
    nextclade = nextclade or {}
    blast = blast or {}
    read_stats = read_stats or {}
    validation = validation or {}

    # per-sample summary (ALL row)
    summary = []
    for sid in sample_ids:
        allrow = samples[sid]["ALL"] or {}
        comp = allrow.get("completeness", "")
        status = classify(comp, pass_t, warn_t)
        vinfo = variants.get(sid, {})
        minfo = mixed.get(sid, {})
        rinfo = read_stats.get(sid, {})
        # divergence proxy: PASS variants per kb of reference covered
        nvar = vinfo.get("total", 0)
        refpos = ffloat(allrow.get("ref_positions", 0))
        div_per_kb = (nvar / refpos * 1000) if refpos else 0.0
        summary.append({
            "sample": sid,
            "status": status,
            "completeness": comp,
            "length": allrow.get("consensus_length", "-"),
            "n_bases": allrow.get("n_bases", "-"),
            "breadth": allrow.get(breadth_key, ""),
            "mean_depth": allrow.get("mean_depth", ""),
            "nvar": nvar,
            "aa": vinfo.get("aa", []),
            "segments": samples[sid]["segments"],
            "n_mixed": minfo.get("n_mixed", ""),
            "mixed_per_kb": minfo.get("per_kb", ""),
            "max_minor_freq": minfo.get("max_freq", ""),
            "div_per_kb": div_per_kb,
            "reads_raw": rinfo.get("reads_raw", ""),
            "reads_post_fastp": rinfo.get("reads_post_fastp", ""),
            "reads_post_deplete": rinfo.get("reads_post_deplete", ""),
        })

    n_pass = sum(1 for s in summary if s["status"] == "PASS")
    n_warn = sum(1 for s in summary if s["status"] == "WARN")
    n_fail = sum(1 for s in summary if s["status"] == "FAIL")
    any_segmented = any(len(s["segments"]) > 0 for s in summary)
    any_aa = any(s["aa"] for s in summary)
    any_mixed = bool(mixed) and any(s["n_mixed"] != "" for s in summary)
    any_reads = bool(read_stats) and any(str(s["reads_raw"]) != "" for s in summary)
    # the depletion column only appears when at least one sample was dehosted
    any_deplete = any_reads and any(str(s["reads_post_deplete"]) != "" for s in summary)
    any_tax = bool(taxonomy)
    any_nextclade = bool(nextclade)
    any_blast = bool(blast)
    any_typing = any_nextclade or any_blast
    any_validation = bool(validation)
    # segmented Oropouche => nextclade rows carry lineage_L/M/S
    nc_segmented = any("lineage_L" in r or "lineage_M" in r or "lineage_S" in r
                       for r in nextclade.values())

    comp_vals = [ffloat(s["completeness"]) for s in summary]
    depth_vals = [ffloat(s["mean_depth"]) for s in summary]
    bar_cols = [BAR_COLORS[s["status"]] for s in summary]

    # aggregate stats
    med_comp = median(comp_vals)
    med_depth = median(depth_vals)
    total_var = sum(s["nvar"] for s in summary)
    uniq_aa = set()
    for s in summary:
        uniq_aa.update(s["aa"])

    # ---------------------------------------------------------------- TAB: Overview
    donut = svg_donut([
        ("PASS", n_pass, BAR_COLORS["PASS"]),
        ("WARN", n_warn, BAR_COLORS["WARN"]),
        ("FAIL", n_fail, BAR_COLORS["FAIL"]),
    ])
    legend = "".join(
        f'<div class="lg"><span class="dot" style="background:{BAR_COLORS[k]}"></span>'
        f'{k} <strong>{v}</strong> <span class="muted">'
        f'({(v/len(summary)*100 if summary else 0):.0f}%)</span></div>'
        for k, v in (("PASS", n_pass), ("WARN", n_warn), ("FAIL", n_fail))
    )

    comp_edges = [0.50, 0.70, 0.80, 0.90, 0.95, 1.0001]
    comp_labels = ["<50%", "50-70", "70-80", "80-90", "90-95", "95-100"]
    comp_reps = [0.45, 0.60, 0.75, 0.85, 0.925, 0.98]
    comp_counts = _hist(comp_vals, comp_edges, comp_labels)
    comp_hist_cols = [BAR_COLORS[classify(r, pass_t, warn_t)] for r in comp_reps]
    hist_comp = svg_vbars(comp_labels, comp_counts,
                          "Completeness distribution (samples)", colors=comp_hist_cols)

    depth_edges = [1, 20, 100, 500, 1000, float("inf")]
    depth_labels = ["0", "<20", "20-100", "100-500", "500-1k", ">1k"]
    depth_counts = _hist(depth_vals, depth_edges, depth_labels)
    hist_depth = svg_vbars(depth_labels, depth_counts,
                           "Mean depth distribution (samples)",
                           colors=["#2b6cb0"] * len(depth_labels))

    # ---------------------------------------------------------------- TAB: Run Validation
    run_validation_tab = ""
    if any_validation:
        controls = [
            r for _, r in sorted(validation.items())
            if str(r.get("is_negative_control", "")).lower() == "true"
            or r.get("sample_role") == "negative_control"
            or str(r.get("sample", "")).upper().startswith("CN")
        ]
        clean_controls = []
        contaminated_controls = []
        unknown_controls = []
        for r in controls:
            sid = r.get("sample", "")
            status = (r.get("input_status") or "").lower()
            tax = taxonomy.get(sid)
            if status != "valid":
                clean_controls.append((r, None, "No usable reads; no viral contamination was observed."))
            elif tax:
                if ffloat(tax.get("pct_viral", 0)) > 0:
                    contaminated_controls.append((r, tax))
                else:
                    clean_controls.append((r, tax, "No viral contamination was observed."))
            else:
                unknown_controls.append((r, None))

        messages = []
        clean_names = [r.get("sample", "") for r, _, _ in clean_controls]
        contam_names = [r.get("sample", "") for r, _ in contaminated_controls]
        unknown_names = [r.get("sample", "") for r, _ in unknown_controls]
        if not controls:
            messages.append(
                '<div class="notice warn"><strong>No negative control sample was detected for this run.</strong> '
                'Use sample IDs or FASTQ names starting with <code>CN</code> to enable negative-control validation.</div>'
            )
        else:
            if clean_names and not contam_names:
                messages.append(
                    '<div class="notice ok"><strong>No viral contamination was observed in the negative control(s). '
                    'The sequencing run is validated.</strong><br>'
                    f'Validated negative control(s): {html.escape(human_join(clean_names))}.</div>'
                )
            elif clean_names:
                messages.append(
                    '<div class="notice ok"><strong>'
                    f'{html.escape(human_join(clean_names))} showed no viral contamination. '
                    'The sequencing run is validated for these negative controls.</strong></div>'
                )
            if contam_names:
                noun = "negative control" if len(contam_names) == 1 else "negative controls"
                messages.append(
                    '<div class="notice fail"><strong>Attention! Viral contamination was observed in '
                    f'{noun} {html.escape(human_join(contam_names))}.</strong></div>'
                )
            if unknown_names:
                messages.append(
                    '<div class="notice warn"><strong>Negative-control viral contamination could not be assessed for '
                    f'{html.escape(human_join(unknown_names))}.</strong><br>'
                    'No Kraken2 taxonomy result was available for these valid negative-control sample(s).</div>'
                )

        def validation_assessment(r, tax):
            if (r.get("input_status") or "").lower() != "valid":
                return "No usable reads; no viral contamination observed"
            if not tax:
                return "Not assessed"
            return "Viral contamination detected" if ffloat(tax.get("pct_viral", 0)) > 0 else "No viral contamination observed"

        ctrl_rows = []
        for r in controls:
            sid = r.get("sample", "")
            tax = taxonomy.get(sid)
            pv = ffloat(tax.get("pct_viral", 0)) if tax else 0.0
            row_class = ' class="row-fail"' if tax and pv > 0 else ""
            ctrl_rows.append(
                f"<tr{row_class}>"
                f'<td class="mono">{html.escape(sid)}</td>'
                f'<td>{html.escape(r.get("input_status", "-") or "-")}</td>'
                f'<td>{html.escape(r.get("input_issue", "") or "—")}</td>'
                f'<td class="num">{html.escape(tax.get("total_reads", "-") if tax else "-")}</td>'
                f'<td class="num">{pv:.2f}%</td>'
                f'<td>{html.escape(tax.get("top_nonhost_taxon", "-") if tax else "-")}</td>'
                f'<td>{html.escape(validation_assessment(r, tax))}</td>'
                "</tr>"
            )

        skipped = [
            r for _, r in sorted(validation.items())
            if (r.get("input_status") or "").lower() != "valid"
            and not (
                str(r.get("is_negative_control", "")).lower() == "true"
                or r.get("sample_role") == "negative_control"
                or str(r.get("sample", "")).upper().startswith("CN")
            )
        ]
        skipped_rows = []
        for r in skipped:
            skipped_rows.append(
                "<tr>"
                f'<td class="mono">{html.escape(r.get("sample", ""))}</td>'
                f'<td>{html.escape(r.get("input_issue", "") or "-")}</td>'
                f'<td>{html.escape(r.get("fastq_1", "") or "-")}</td>'
                f'<td>{html.escape(r.get("fastq_2", "") or "-")}</td>'
                "</tr>"
            )
        skipped_block = ""
        if skipped_rows:
            skipped_block = f"""
          <h3 style="margin-top:26px">Skipped non-control samples</h3>
          <p class="muted">These samples had empty, truncated or invalid FASTQs and were skipped
          before downstream processing so the rest of the run could continue.</p>
          <div class="table-scroll"><table>
            <thead><tr><th>Sample</th><th>Reason</th><th>FASTQ 1</th><th>FASTQ 2</th></tr></thead>
            <tbody>{''.join(skipped_rows)}</tbody>
          </table></div>"""

        krona_block = ""
        if contaminated_controls and validation_krona_rel:
            krona_block = (
                '<h3 style="margin-top:26px">Negative-control Krona result</h3>'
                '<p class="muted">Interactive taxonomic composition generated from valid CN* negative-control '
                'Kraken2 reports. Use this chart to inspect the viral taxa detected in contaminated controls.</p>'
                f'<p><a href="{html.escape(validation_krona_rel)}" target="_blank" '
                'style="font-weight:600">Open negative-control Krona in a new tab &rarr;</a></p>'
                f'<iframe src="{html.escape(validation_krona_rel)}" style="width:100%;height:640px;'
                'border:1px solid var(--line);border-radius:8px"></iframe>'
            )

        run_validation_tab = f"""
          <p class="muted">Run-level validation of negative controls. Samples whose ID or FASTQ
          filename starts with <code>CN</code> are treated as negative controls. Valid CN* samples
          are evaluated with Kraken2/Krona and are excluded from consensus assembly.</p>
          {''.join(messages)}
          <h3>Negative-control summary</h3>
          <div class="table-scroll"><table id="tbl-run-validation">
            <thead><tr>
              <th>Control</th><th>Input status</th><th>Input issue</th>
              <th class="num">Kraken2 reads</th><th class="num">Viral fraction</th>
              <th>Dominant non-host taxon</th><th>Assessment</th>
            </tr></thead>
            <tbody>{''.join(ctrl_rows) if ctrl_rows else '<tr><td colspan="7">No CN* controls detected.</td></tr>'}</tbody>
          </table></div>
          {krona_block}
          {skipped_block}
        """

    stat_cards = (
        f'<div class="card"><div class="k">Median completeness</div>'
        f'<div class="v">{pct(med_comp)}</div></div>'
        f'<div class="card"><div class="k">Median depth</div>'
        f'<div class="v">{med_depth:.0f}x</div></div>'
        f'<div class="card"><div class="k">Variants (total)</div>'
        f'<div class="v">{total_var}</div></div>'
    )
    if any_aa:
        stat_cards += (f'<div class="card"><div class="k">Unique AA changes</div>'
                       f'<div class="v">{len(uniq_aa)}</div></div>')

    overview = f"""
      <div class="cards">
        <div class="card"><div class="k">Samples</div><div class="v">{len(summary)}</div></div>
        <div class="card pass"><div class="k">Pass</div><div class="v">{n_pass}</div></div>
        <div class="card warn"><div class="k">Warn</div><div class="v">{n_warn}</div></div>
        <div class="card fail"><div class="k">Fail</div><div class="v">{n_fail}</div></div>
      </div>
      <div class="grid2">
        <div class="chart">
          <h3>Sample classification</h3>
          <div class="donut-wrap">{donut}<div class="legend">{legend}</div></div>
        </div>
        <div class="chart"><h3>Aggregate statistics</h3>
          <div class="cards">{stat_cards}</div>
          <p class="muted">Classification criterion based on consensus completeness:
             PASS &ge; {pct(pass_t)}, WARN &ge; {pct(warn_t)}, otherwise FAIL.</p>
        </div>
      </div>
      <div class="grid2">
        <div class="chart">{hist_comp}</div>
        <div class="chart">{hist_depth}</div>
      </div>
    """

    # ---------------------------------------------------------------- TAB: Samples
    # thresholds for flagging suspicious samples in the table
    MIXED_WARN_PER_KB = 1.0   # >1 ambiguous site / kb -> possible contamination
    trows = []
    for s in summary:
        badge = (f'<span class="badge" style="background:{BADGE_COLORS[s["status"]]}">'
                 f'{s["status"]}</span>')
        aa_cell = f'<td class="num">{len(s["aa"])}</td>' if any_aa else ""
        # mixed-sites cell (flagged red when above threshold)
        if any_mixed:
            nm = s["n_mixed"]
            pk = ffloat(s["mixed_per_kb"])
            flag = pk >= MIXED_WARN_PER_KB
            style = ' style="color:#c53030;font-weight:700"' if flag else ""
            tip = f' title="{s["mixed_per_kb"]}/kb, freq. minor. max {s["max_minor_freq"]}"'
            mixed_cell = f'<td class="num"{style}{tip}>{nm}</td>'
        else:
            mixed_cell = ""
        # divergence cell (variants per kb)
        div_cell = f'<td class="num">{fnum(s["div_per_kb"],1)}</td>' if any_aa or variants else ""
        # read-accounting cells (raw / post-fastp / post-deplete)
        reads_cells = ""
        if any_reads:
            reads_cells = (
                f'<td class="num">{fint(s["reads_raw"])}</td>'
                f'<td class="num">{fint(s["reads_post_fastp"])}</td>'
            )
            if any_deplete:
                reads_cells += f'<td class="num">{fint(s["reads_post_deplete"])}</td>'
        trows.append(
            "<tr>"
            f'<td class="mono">{html.escape(s["sample"])}</td>'
            f"<td>{badge}</td>"
            f'{reads_cells}'
            f'<td class="num">{pct(s["completeness"])}</td>'
            f'<td class="num">{pct(s["breadth"])}</td>'
            f'<td class="num">{fnum(s["mean_depth"],0)}x</td>'
            f'<td class="num">{s["length"]}</td>'
            f'<td class="num">{s["n_bases"]}</td>'
            f'<td class="num">{s["nvar"]}</td>'
            f'{div_cell}'
            f'{mixed_cell}'
            f'{aa_cell}'
            "</tr>"
        )
    samples_tab = f"""
      <div class="toolbar">
        <input id="flt" type="text" placeholder="filter by sample..." autocomplete="off">
        <span class="muted">Click a column header to sort.</span>
        <button type="button" class="download-btn" data-table="tbl-samples"
                data-filename="samples_table.csv">Download CSV</button>
      </div>
      <div class="table-scroll">
      <table id="tbl-samples">
        <thead><tr>
          <th>Sample</th><th>Status</th>
          {'<th class="num" title="Total raw reads (R1+R2) before filtering">Reads</th>' if any_reads else ''}
          {'<th class="num" title="Reads retained after fastp quality and adapter filtering">Post-fastp reads</th>' if any_reads else ''}
          {'<th class="num" title="Reads remaining after host-read removal">Post-depletion reads</th>' if any_deplete else ''}
          <th class="num">Completeness</th>
          <th class="num">Breadth (&ge;{min_cov}x)</th><th class="num">Mean depth</th>
          <th class="num">Length</th><th class="num">N bases</th><th class="num">Variants</th>
          {'<th class="num" title="PASS variants per kb of covered reference">Div. (/kb)</th>' if (any_aa or variants) else ''}
          {'<th class="num" title="Sites with ambiguous allele frequency (20-80%): contamination/co-infection signal">Mixed sites</th>' if any_mixed else ''}
          {'<th class="num">Mut. (aa)</th>' if any_aa else ''}
        </tr></thead>
        <tbody>{''.join(trows)}</tbody>
      </table>
      </div>
    """

    # ---------------------------------------------------------------- TAB: Coverage
    chart_comp = svg_barchart([s["sample"] for s in summary], comp_vals,
                              "Consensus completeness (non-N fraction)", is_pct=True, colors=bar_cols)
    chart_depth = svg_barchart([s["sample"] for s in summary], depth_vals,
                               "Mean depth (x)", unit="x", colors=bar_cols)
    coverage_tab = f"""
      <div class="chart">{chart_comp}</div>
      <div class="chart" style="margin-top:16px">{chart_depth}</div>
    """

    # ---------------------------------------------------------------- TAB: Mutations
    mutations_tab = ""
    if any_aa:
        mut_counts = Counter()
        mut_samples = defaultdict(list)     # mutation -> [samples carrying it]
        for s in summary:
            for m in set(s["aa"]):
                mut_counts[m] += 1
                mut_samples[m].append(s["sample"])
        top = mut_counts.most_common(25)
        chart_top = svg_barchart([m for m, _ in top], [c for _, c in top],
                                 "Most recurrent amino-acid changes (number of samples)",
                                 colors=["#2b6cb0"] * len(top), width=720)
        # ---- Heatmap: recurrent mutations (>=2 samples) x samples ----
        recurrent = [(m, c) for m, c in mut_counts.most_common() if c >= 2]
        recurrent = recurrent[:40]                       # limit heatmap height
        heat_block = ""
        if recurrent:
            rec_muts = [m for m, _ in recurrent]
            rec_counts = [c for _, c in recurrent]
            # columns = samples carrying at least one recurrent mutation
            rec_set = set(rec_muts)
            heat_samples = [s["sample"] for s in summary if rec_set.intersection(s["aa"])]
            smp_aa = {s["sample"]: set(s["aa"]) for s in summary}
            hmatrix = [[(m in smp_aa[smp]) for smp in heat_samples] for m in rec_muts]
            heat_svg = svg_heatmap(rec_muts, heat_samples, hmatrix,
                                   "Recurrent mutation heatmap (row = mutation, column = sample)",
                                   row_counts=rec_counts, legend_max=max(rec_counts))
            heat_block = f"""
          <h3 style="margin-top:26px">Recurrence heatmap</h3>
          <p class="muted">Each filled cell indicates that the sample (column) carries the
             mutation (row). Color reflects how many samples carry the mutation; darker cells
             indicate greater recurrence. Hover over a cell for details.</p>
          <div class="chart" style="overflow-x:auto">{heat_svg}</div>"""

        # ---- Unique mutations (present in exactly 1 sample) ----
        uniq_rows = []
        for m, c in sorted(mut_counts.items(), key=lambda kv: (kv[0].split(":",1)[0], kv[0])):
            if c == 1:
                smp = mut_samples[m][0]
                gene = m.split(":", 1)[0] if ":" in m else "-"
                uniq_rows.append(
                    "<tr>"
                    f'<td class="mono">{html.escape(m)}</td>'
                    f"<td>{html.escape(gene)}</td>"
                    f'<td class="mono">{html.escape(smp)}</td>'
                    "</tr>"
                )
        if uniq_rows:
            uniq_block = f"""
          <h3 style="margin-top:26px">Unique mutations ({len(uniq_rows)}) — present in one sample only</h3>
          <p class="muted">Substitutions observed in only one sample in this run, with the
             corresponding sample.</p>
          <table id="tbl-uniq">
            <thead><tr><th>Mutation (AA)</th><th>Gene/protein</th><th>Sample</th></tr></thead>
            <tbody>{''.join(uniq_rows)}</tbody>
          </table>"""
        else:
            uniq_block = ('<h3 style="margin-top:26px">Unique mutations</h3>'
                          '<p class="muted">No mutation was exclusive to a single sample in this run.</p>')
        mut_rows = []
        for s in summary:
            if not s["aa"]:
                chips = '<span class="muted">-</span>'
            else:
                chips = " ".join(f'<span class="mut">{html.escape(m)}</span>' for m in s["aa"])
            badge = (f'<span class="badge" style="background:{BADGE_COLORS[s["status"]]}">'
                     f'{s["status"]}</span>')
            mut_rows.append(
                "<tr>"
                f'<td class="mono">{html.escape(s["sample"])}</td>'
                f"<td>{badge}</td>"
                f'<td class="num">{len(s["aa"])}</td>'
                f'<td class="mut-cell">{chips}</td>'
                "</tr>"
            )
        mutations_tab = f"""
          <p class="muted">Nonsynonymous substitutions only (iVar variants with PASS=TRUE).
             Notation: GENE:REF&lt;position&gt;ALT.</p>
          <div class="chart">{chart_top}</div>
          {heat_block}
          {uniq_block}
          <h3 style="margin-top:26px">Mutations by sample</h3>
          <table id="tbl-mut">
            <thead><tr><th>Sample</th><th>Status</th><th class="num">No. mutations</th>
              <th>Mutations (AA)</th></tr></thead>
            <tbody>{''.join(mut_rows)}</tbody>
          </table>
        """

    # ---------------------------------------------------------------- TAB: Segments
    segments_tab = ""
    if any_segmented:
        seg_rows = []
        seg_labels, seg_comp, seg_cols = [], [], []
        for s in summary:
            for seg in s["segments"]:
                vb = variants.get(s["sample"], {}).get("by_segment", {})
                seg_name = seg.get("segment", "?")
                nvar_seg = vb.get(seg_name, 0)
                status = classify(seg.get("completeness", ""), pass_t, warn_t)
                badge = (f'<span class="badge" style="background:{BADGE_COLORS[status]}">'
                         f'{status}</span>')
                seg_rows.append(
                    "<tr>"
                    f'<td class="mono">{html.escape(s["sample"])}</td>'
                    f'<td class="mono">{html.escape(str(seg_name))}</td>'
                    f"<td>{badge}</td>"
                    f'<td class="num">{pct(seg.get("completeness",""))}</td>'
                    f'<td class="num">{pct(seg.get(breadth_key,""))}</td>'
                    f'<td class="num">{fnum(seg.get("mean_depth",""),0)}x</td>'
                    f'<td class="num">{seg.get("consensus_length","-")}</td>'
                    f'<td class="num">{nvar_seg}</td>'
                    "</tr>"
                )
                seg_labels.append(f'{s["sample"]}|{seg_name}')
                seg_comp.append(ffloat(seg.get("completeness", "")))
                seg_cols.append(BAR_COLORS[status])
        chart_seg = svg_barchart(seg_labels, seg_comp,
                                 "Completeness by segment", is_pct=True,
                                 colors=seg_cols, width=720)
        segments_tab = f"""
          <p class="muted">Segmented viruses (e.g. Oropouche L/M/S): metrics by segment.</p>
          <div class="chart">{chart_seg}</div>
          <table style="margin-top:16px">
            <thead><tr>
              <th>Sample</th><th>Segment</th><th>Status</th>
              <th class="num">Completeness</th><th class="num">Breadth (&ge;{min_cov}x)</th>
              <th class="num">Mean depth</th><th class="num">Length</th><th class="num">Variants</th>
            </tr></thead>
            <tbody>{''.join(seg_rows)}</tbody>
          </table>
        """

    # ---------------------------------------------------------------- TAB: Taxonomy
    taxonomy_tab = ""
    if any_tax:
        tax_rows = []
        for s in summary:
            t = taxonomy.get(s["sample"])
            if not t:
                continue
            ph = ffloat(t.get("pct_human", 0))
            pv = ffloat(t.get("pct_viral", 0))
            pu = ffloat(t.get("pct_unclassified", 0))
            pb = ffloat(t.get("pct_bacterial", 0))
            # flag high host or low viral fraction
            host_flag = ' style="color:#c53030;font-weight:700"' if ph >= 50 else ""
            # composition mini-bar (viral green / human orange / bacterial red / unclass grey)
            def seg(w, col):
                return f'<span style="display:inline-block;height:12px;width:{max(0,w)*1.4:.1f}px;background:{col}"></span>'
            bar = (seg(pv, "#38a169") + seg(ph, "#dd6b20")
                   + seg(pb, "#e53e3e") + seg(pu, "#a0aec0"))
            tax_rows.append(
                "<tr>"
                f'<td class="mono">{html.escape(s["sample"])}</td>'
                f'<td class="num">{t.get("total_reads","-")}</td>'
                f'<td class="num">{pv:.1f}%</td>'
                f'<td class="num"{host_flag}>{ph:.1f}%</td>'
                f'<td class="num">{pb:.1f}%</td>'
                f'<td class="num">{pu:.1f}%</td>'
                f'<td style="min-width:200px">{bar}</td>'
                f'<td>{html.escape(str(t.get("top_nonhost_taxon","-")))} '
                f'({ffloat(t.get("top_nonhost_pct",0)):.1f}%)</td>'
                "</tr>"
            )
        krona_block = ""
        if krona_rel:
            krona_block = (
                '<h3 style="margin-top:26px">Krona — interactive taxonomic composition</h3>'
                '<p class="muted">Interactive sunburst chart generated from Kraken2 results (all samples). '
                'Click the rings to navigate the taxonomic hierarchy.</p>'
                f'<p><a href="{html.escape(krona_rel)}" target="_blank" '
                'style="font-weight:600">Open Krona in a new tab &rarr;</a></p>'
                f'<iframe src="{html.escape(krona_rel)}" style="width:100%;height:640px;'
                'border:1px solid var(--line);border-radius:8px"></iframe>'
            )
        taxonomy_tab = f"""
          <p class="muted">Taxonomic screening of reads (Kraken2) to detect contamination,
          host burden (<b>Homo sapiens</b>), and off-target reads. Bar: <span style="color:#38a169">viral</span> /
          <span style="color:#dd6b20">human</span> / <span style="color:#e53e3e">bacterial</span> /
          <span style="color:#718096">unclassified</span>.</p>
          <table id="tbl-tax">
            <thead><tr>
              <th>Sample</th><th class="num">Reads</th><th class="num">Viral</th>
              <th class="num">Human</th><th class="num">Bacterial</th><th class="num">Unclassified</th>
              <th>Composition</th><th>Dominant non-host taxon</th>
            </tr></thead>
            <tbody>{''.join(tax_rows)}</tbody>
          </table>
          {krona_block}
        """

    # ---------------------------------------------------------------- TAB: Lineages/Genotypes
    typing_tab = ""
    if any_typing:
        def qc_badge(st):
            st = (st or "").lower()
            col = {"good": "#2f855a", "mediocre": "#b7791f", "bad": "#c53030"}.get(st, "#718096")
            lbl = {"good": "good", "mediocre": "mediocre", "bad": "bad"}.get(st, st or "-")
            return (f'<span style="display:inline-block;padding:1px 8px;border-radius:10px;'
                    f'background:{col};color:#fff;font-size:11.5px;font-weight:700">{html.escape(lbl)}</span>')

        nc_note = ""
        if any_nextclade:
            # dominant call column depends on virus: prefer lineage, then pango, then clade, then genotype
            rows_nc = []
            for s in summary:
                sid = s["sample"]
                r = nextclade.get(sid)
                if not r:
                    continue
                if nc_segmented:
                    call = (f'L: {html.escape(r.get("lineage_L","") or "-")}<br>'
                            f'M: {html.escape(r.get("lineage_M","") or "-")}<br>'
                            f'S: {html.escape(r.get("lineage_S","") or "-")}')
                else:
                    call = html.escape(r.get("lineage") or r.get("pango")
                                       or r.get("clade") or r.get("genotype") or "-")
                clade = html.escape(r.get("clade", "") or "-")
                priv = r.get("private_mutations", "") or "-"
                fs = ffloat(r.get("frameshifts", 0))
                stops = ffloat(r.get("stop_codons", 0))
                # flag frameshifts / premature stops (assembly/typing warning)
                flags = []
                if fs > 0:
                    flags.append(f'<span style="color:#c53030">frameshift×{int(fs)}</span>')
                if stops > 0:
                    flags.append(f'<span style="color:#c53030">stop×{int(stops)}</span>')
                flag_html = " ".join(flags) if flags else '<span style="color:#2f855a">—</span>'
                rows_nc.append(
                    "<tr>"
                    f'<td class="mono">{html.escape(sid)}</td>'
                    f'<td>{call}</td>'
                    f'<td>{clade}</td>'
                    f'<td class="num">{r.get("total_substitutions","-") or "-"}</td>'
                    f'<td class="num">{priv}</td>'
                    f'<td>{qc_badge(r.get("qc_status"))}</td>'
                    f'<td>{flag_html}</td>'
                    "</tr>"
                )
            seg_note = (" For Oropouche, lineages for each segment (L/M/S) are "
                        "shown in the same row.") if nc_segmented else ""
            nc_note = f"""
          <div class="section-head">
            <h3>Nextclade — lineages / genotypes</h3>
            <button type="button" class="download-btn" data-table="tbl-typing"
                    data-filename="lineages_genotypes_table.csv">Download CSV</button>
          </div>
          <p class="muted">Typing from the assembled consensus (Nextclade v3).
          The QC column and counts of private mutations, frameshifts, and premature stops
          are Nextclade controls that complement assembly QC.{seg_note}
          The dataset and version are listed in the footer for traceability.</p>
          <table id="tbl-typing">
            <thead><tr>
              <th>Sample</th><th>Lineage / Genotype</th><th>Clade</th>
              <th class="num">Substitutions</th><th class="num">Private mutations</th>
              <th>Nextclade QC</th><th>Alerts</th>
            </tr></thead>
            <tbody>{''.join(rows_nc)}</tbody>
          </table>"""

        blast_note = ""
        if any_blast:
            rows_bl = []
            for s in summary:
                sid = s["sample"]
                r = blast.get(sid)
                if not r:
                    continue
                pid = ffloat(r.get("pct_identity", 0))
                cov = ffloat(r.get("coverage", 0))
                # low-confidence flag
                idflag = ' style="color:#b7791f;font-weight:700"' if (pid < 90 or cov < 80) else ""
                rows_bl.append(
                    "<tr>"
                    f'<td class="mono">{html.escape(sid)}</td>'
                    f'<td>{html.escape(r.get("best_hit_species","-") or "-")}</td>'
                    f'<td class="mono">{html.escape(r.get("accession","-") or "-")}</td>'
                    f'<td class="num"{idflag}>{pid:.1f}%</td>'
                    f'<td class="num"{idflag}>{cov:.0f}%</td>'
                    f'<td class="num">{html.escape(str(r.get("evalue","-")))}</td>'
                    "</tr>"
                )
            blast_note = f"""
          <h3 style="margin-top:26px">BLAST — species confirmation</h3>
          <p class="muted">Best hit for each consensus against the local viral RefSeq database (blastn).
          This provides an independent identity check for sample swaps, incorrect references,
          and viruses outside the Nextclade catalog. Yellow values indicate
          identity &lt; 90% or coverage &lt; 80% and should be reviewed.</p>
          <table id="tbl-blast">
            <thead><tr>
              <th>Sample</th><th>Species (best hit)</th><th>Accession</th>
              <th class="num">% Identity</th><th class="num">Coverage</th><th class="num">E-value</th>
            </tr></thead>
            <tbody>{''.join(rows_bl)}</tbody>
          </table>"""

        typing_tab = nc_note + blast_note

    # provenance line for the footer (dataset/tag + RefSeq build date)
    prov_bits = []
    if any_nextclade and nextclade_info:
        prov_bits.append(f"Nextclade: {html.escape(nextclade_info)}")
    if any_blast and blast_info:
        prov_bits.append(f"BLAST RefSeq viral: {html.escape(blast_info)}")
    typing_prov = (" <br>" + " &middot; ".join(prov_bits)) if prov_bits else ""

    # ---------------------------------------------------------------- tabs assembly
    tabs = []
    if any_validation:
        tabs.append(("run-validation", "Run Validation", run_validation_tab))
    tabs += [("overview", "Overview", overview),
             ("samples", "Samples", samples_tab),
            ("coverage", "Coverage", coverage_tab)]
    if any_aa:
        tabs.append(("mutations", "Mutations", mutations_tab))
    if any_typing:
        tabs.append(("typing", "Lineages / Genotypes", typing_tab))
    if any_tax:
        tabs.append(("taxonomy", "Taxonomy", taxonomy_tab))
    if any_segmented:
        tabs.append(("segments", "Segments", segments_tab))

    btns = "".join(
        f'<button class="tab-btn{" active" if i == 0 else ""}" data-tab="{tid}">{html.escape(tlabel)}</button>'
        for i, (tid, tlabel, _) in enumerate(tabs)
    )
    panels = "".join(
        f'<section id="tab-{tid}" class="tab-panel{" active" if i == 0 else ""}">{tbody}</section>'
        for i, (tid, _, tbody) in enumerate(tabs)
    )

    css = """
    :root { --ink:#1a2b4a; --line:#e2e8f0; }
    * { box-sizing: border-box; }
    body { font-family: -apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;
           color:#222; margin:0; background:#f7fafc; }
    .wrap { max-width: 1400px; margin: 0 auto; padding: 28px 22px 60px; }
    header.top { border-bottom: 3px solid var(--ink); padding-bottom: 12px; margin-bottom: 8px; }
    .brand { font-size: 13px; font-weight: 800; letter-spacing:.08em; text-transform:uppercase;
             color: var(--accent, #2b6cb0); margin: 0 0 4px; }
    h1 { margin: 0 0 2px; font-size: 22px; color: var(--ink); }
    h3 { color: var(--ink); font-size: 15px; margin: 2px 0 12px; }
    .muted { color:#667; font-size: 13px; margin: 2px 0 14px; }
    .cards { display:flex; gap:12px; flex-wrap:wrap; margin: 14px 0; }
    .card { flex:1 1 120px; border:1px solid var(--line); border-radius:8px; padding:12px 14px; background:#fff; }
    .card .k { font-size: 12px; color:#667; text-transform:uppercase; letter-spacing:.03em; }
    .card .v { font-size: 26px; font-weight:700; color:var(--ink); }
    .card.pass .v { color:#2f855a; } .card.warn .v { color:#b7791f; } .card.fail .v { color:#c53030; }
    .tabs { display:flex; gap:4px; flex-wrap:wrap; border-bottom:2px solid var(--ink); margin-top:20px; }
    .tab-btn { background:#edf2f7; border:1px solid var(--line); border-bottom:none; padding:9px 18px;
               cursor:pointer; font-size:14px; font-weight:600; color:var(--ink);
               border-radius:8px 8px 0 0; }
    .tab-btn:hover { background:#e2e8f0; }
    .tab-btn.active { background:#fff; border-top:3px solid var(--ink); padding-top:7px; }
    .tab-panel { display:none; padding:20px 2px 4px; }
    .tab-panel.active { display:block; }
    .grid2 { display:grid; grid-template-columns:1fr 1fr; gap:18px; margin-top:4px; }
    @media (max-width:720px){ .grid2 { grid-template-columns:1fr; } }
    .chart { border:1px solid var(--line); border-radius:8px; background:#fff; padding:12px 12px; }
    .donut-wrap { display:flex; gap:18px; align-items:center; flex-wrap:wrap; }
    .legend { display:flex; flex-direction:column; gap:8px; }
    .lg { font-size:14px; } .lg .dot { display:inline-block; width:12px; height:12px; border-radius:3px;
          margin-right:7px; vertical-align:middle; }
    table { width:100%; border-collapse:collapse; background:#fff; font-size:13.5px;
            border:1px solid var(--line); border-radius:8px; overflow:hidden; }
    /* samples table: never wrap header or value cells; let it grow and scroll
       horizontally instead of squeezing columns into two lines */
    #tbl-samples { width:auto; min-width:100%; }
    #tbl-samples th, #tbl-samples td { white-space:nowrap; padding:8px 14px; }
    .table-scroll { overflow-x:auto; -webkit-overflow-scrolling:touch;
                    border:1px solid var(--line); border-radius:8px; }
    .table-scroll table { border:none; border-radius:0; }
    th, td { padding:8px 10px; text-align:center; vertical-align:middle;
             border-bottom:1px solid var(--line); }
    th { background:#edf2f7; color:var(--ink); font-size:12px; text-transform:uppercase;
         letter-spacing:.02em; cursor:pointer; user-select:none; }
    td.num, th.num { text-align:center; font-variant-numeric: tabular-nums; }
    td.mono { font-family: ui-monospace,SFMono-Regular,Menlo,monospace; }
    tr:hover td { background:#f7fafc; }
    .badge { color:#fff; padding:2px 9px; border-radius:10px; font-size:11.5px; font-weight:700; letter-spacing:.02em; }
    .mut-cell { max-width:520px; }
    .mut { display:inline-block; font-family: ui-monospace,SFMono-Regular,Menlo,monospace;
           font-size:11.5px; background:#ebf4ff; color:#2b6cb0; border:1px solid #c3dafe;
           border-radius:5px; padding:1px 6px; margin:1px 2px; white-space:nowrap; }
    .toolbar { display:flex; gap:14px; align-items:center; margin-bottom:12px; flex-wrap:wrap; }
    #flt { padding:7px 11px; border:1px solid var(--line); border-radius:7px; font-size:13.5px; min-width:240px; }
    .section-head { display:flex; align-items:center; justify-content:space-between; gap:14px; margin-bottom:10px; }
    .section-head h3 { margin-bottom:0; }
    .download-btn { margin-left:auto; border:1px solid #b7c6d8; border-radius:7px; background:#fff;
                    color:var(--ink); cursor:pointer; font-size:12.5px; font-weight:700;
                    padding:7px 11px; white-space:nowrap; }
    .download-btn:hover { background:#edf2f7; }
    .notice { border:1px solid var(--line); border-left-width:6px; border-radius:8px; padding:12px 14px;
              margin:12px 0; background:#fff; }
    .notice.ok { border-left-color:#2f855a; background:#f0fff4; }
    .notice.warn { border-left-color:#b7791f; background:#fffaf0; }
    .notice.fail { border-left-color:#c53030; background:#fff5f5; }
    tr.row-fail td { background:#fff5f5; }
    footer { margin-top:40px; font-size:12px; color:#8a97a8; border-top:1px solid var(--line); padding-top:12px; }
    """

    js = """
    // tab switching
    document.querySelectorAll('.tab-btn').forEach(function(b){
      b.addEventListener('click',function(){
        document.querySelectorAll('.tab-btn').forEach(function(x){x.classList.remove('active');});
        document.querySelectorAll('.tab-panel').forEach(function(x){x.classList.remove('active');});
        b.classList.add('active');
        var p=document.getElementById('tab-'+b.dataset.tab); if(p){p.classList.add('active');}
      });
    });
    // click-to-sort on any table header
    document.querySelectorAll('table').forEach(function(t){
      t.querySelectorAll('th').forEach(function(th,ci){
        th.addEventListener('click',function(){
          var tb=t.tBodies[0], rows=Array.prototype.slice.call(tb.rows);
          var asc=!(th.dataset.asc==='1'); th.dataset.asc=asc?'1':'0';
          rows.sort(function(a,b){
            var x=a.cells[ci].innerText.replace(/[%x\u2009\u00a0]/g,'').trim();
            var y=b.cells[ci].innerText.replace(/[%x\u2009\u00a0]/g,'').trim();
            var nx=parseFloat(x), ny=parseFloat(y);
            if(!isNaN(nx)&&!isNaN(ny)){return asc?nx-ny:ny-nx;}
            return asc?x.localeCompare(y):y.localeCompare(x);
          });
          rows.forEach(function(r){tb.appendChild(r);});
        });
      });
    });
    // text filter on the samples table
    var flt=document.getElementById('flt');
    if(flt){ flt.addEventListener('input',function(){
      var q=this.value.toLowerCase();
      var tb=document.getElementById('tbl-samples').tBodies[0];
      Array.prototype.forEach.call(tb.rows,function(r){
        r.style.display = r.cells[0].innerText.toLowerCase().indexOf(q)>=0 ? '' : 'none';
      });
    }); }
    function csvCell(txt){
      txt = (txt || '').replace(/\s+/g,' ').trim();
      return '"' + txt.replace(/"/g,'""') + '"';
    }
    function downloadTable(tableId, filename){
      var table=document.getElementById(tableId);
      if(!table){ return; }
      var rows=[];
      var head=table.tHead ? table.tHead.rows[0] : null;
      if(head){
        rows.push(Array.prototype.map.call(head.cells,function(c){return csvCell(c.innerText);}).join(','));
      }
      var body=table.tBodies[0];
      if(body){
        Array.prototype.forEach.call(body.rows,function(r){
          if(r.style.display==='none'){ return; }
          rows.push(Array.prototype.map.call(r.cells,function(c){return csvCell(c.innerText);}).join(','));
        });
      }
      var blob=new Blob(["\ufeff" + rows.join('\n') + '\n'], {type:'text/csv;charset=utf-8'});
      var url=URL.createObjectURL(blob);
      var a=document.createElement('a');
      a.href=url;
      a.download=filename || (tableId + '.csv');
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    }
    document.querySelectorAll('.download-btn').forEach(function(b){
      b.addEventListener('click',function(){
        downloadTable(b.dataset.table, b.dataset.filename);
      });
    });
    """

    doc = f"""<!DOCTYPE html>
<html lang="pt-br"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Dashboard - {html.escape(run_name)}</title>
<style>{css}</style>
<noscript><style>.tab-panel{{display:block !important;}} .tabs{{display:none;}}</style></noscript>
</head>
<body><div class="wrap">
  <header class="top">
    <div class="brand">MK_Viral-Assembly</div>
    <h1>Genomic surveillance dashboard — consensus assembly</h1>
    <div class="muted">Run: <strong>{html.escape(run_name)}</strong> &middot; generated on {now}
      &middot; MK_Viral-Assembly pipeline &middot; criterion: PASS &ge; {pct(pass_t)}, WARN &ge; {pct(warn_t)}
      (consensus completeness) &middot; min_cov = {min_cov}x</div>
  </header>

  <div class="tabs">{btns}</div>
  {panels}

  <footer>
    Self-contained report (no server or CDN required). Each sample is classified by consensus
    completeness (fraction of non-N bases). Variants are counted from iVar tables
    (PASS=TRUE); amino-acid changes include nonsynonymous substitutions only. Automatically
    generated by the MK_Viral-Assembly DASHBOARD module.{typing_prov}
  </footer>
</div>
<script>{js}</script>
</body></html>"""
    return doc


def main():
    ap = argparse.ArgumentParser(description="Build a self-contained HTML surveillance dashboard.")
    ap.add_argument("--qc-dir", required=True, help="directory of *.consensus_qc.tsv files")
    ap.add_argument("--variants-dir", default=None, help="directory of iVar *.variants.tsv files")
    ap.add_argument("--out", default="surveillance_dashboard.html")
    ap.add_argument("--run-name", default="viral-assembly run")
    ap.add_argument("--pass", dest="pass_t", type=float, default=0.90,
                    help="min completeness for PASS [0.90]")
    ap.add_argument("--warn", dest="warn_t", type=float, default=0.70,
                    help="min completeness for WARN [0.70]")
    ap.add_argument("--min-cov", type=int, default=20, help="min coverage used (for labels)")
    ap.add_argument("--mixed-dir", default=None,
                    help="directory of *.mixed_sites.tsv files (intra-sample heterozygosity)")
    ap.add_argument("--taxonomy", default=None,
                    help="taxonomy_summary.py TSV (per-sample Kraken2 composition)")
    ap.add_argument("--nextclade", default=None,
                    help="nextclade_summary.tsv (lineage/genotype typing)")
    ap.add_argument("--nextclade-info", default=None,
                    help="human-readable 'dataset @ tag' string for the report footer")
    ap.add_argument("--blast", default=None,
                    help="blast_summary.tsv (species confirmation)")
    ap.add_argument("--blast-info", default=None,
                    help="human-readable RefSeq build info string for the report footer")
    ap.add_argument("--krona", default=None,
                    help="relative path/filename of the Krona HTML to link (e.g. krona/krona.html)")
    ap.add_argument("--read-stats-dir", dest="read_stats_dir", default=None,
                    help="directory of *.read_stats.tsv (raw / post-fastp / post-deplete read counts)")
    ap.add_argument("--validation-dir", dest="validation_dir", default=None,
                    help="directory of *.sample_validation.tsv files for Run Validation")
    ap.add_argument("--validation-krona", dest="validation_krona", default=None,
                    help="relative path/filename of the CN-only Krona HTML for Run Validation")
    args = ap.parse_args()

    samples, breadth_key = load_qc(args.qc_dir)
    if not samples:
        sys.exit(f"ERROR: no QC tables found in {args.qc_dir}")
    variants = load_variants(args.variants_dir)
    mixed = load_mixed_sites(args.mixed_dir)
    taxonomy = load_taxonomy(args.taxonomy)
    nextclade = load_nextclade(args.nextclade)
    blast = load_blast(args.blast)
    read_stats = load_read_stats(args.read_stats_dir)
    validation = load_validation(args.validation_dir)

    doc = build_html(args.run_name, samples, variants, breadth_key,
                     args.pass_t, args.warn_t, args.min_cov,
                     mixed=mixed, taxonomy=taxonomy, krona_rel=args.krona,
                     nextclade=nextclade, blast=blast,
                     nextclade_info=args.nextclade_info, blast_info=args.blast_info,
                     read_stats=read_stats, validation=validation,
                     validation_krona_rel=args.validation_krona)
    with open(args.out, "w") as fh:
        fh.write(doc)
    print(f"Wrote dashboard for {len(samples)} sample(s) -> {args.out}")


if __name__ == "__main__":
    main()
