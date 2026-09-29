#!/usr/bin/env python3
"""Build metadata_<virus>.xlsx for PASS/WARN assembled samples.

The input metadata table supplies epidemiological/sample fields. Pipeline TSVs
supply read counts, mean depth, coverage breadth and lineage/genotype calls.
The script is stdlib-only so it can run in the minimal python container.
"""
import argparse
import csv
import os
import re
import sys
import zipfile
from datetime import datetime, timezone
from xml.sax.saxutils import escape

BASE_HEADERS = [
    "Vírus", "Código Amostra", "CT", "Município", "UF município solicitante",
    "Data Coleta", "Tipo Amostra", "Idade", "Tipo Idade", "Sexo",
    "Tecnologia de Sequenciamento", "Submissor", "Lab_Origem", "Lab_Submissão", "Endereço", "Autores", "Código da Região",
    "Software Montagem", "Versão software", "Versão primer", "Versão Pangolin",
    "Reads", "Profundidade Média", "Cobertura",
]
FINAL_HEADERS = ["Nome da Sequencia"]
META_FIELDS = [
    "Código Amostra", "CT", "Município", "UF município solicitante",
    "Data Coleta", "Tipo Amostra", "Idade", "Tipo Idade", "Sexo",
    "Tecnologia de Sequenciamento", "Submissor", "Lab_Origem", "Lab_Submissão", "Endereço", "Autores", "Código da Região",
]


def normalized_token(value):
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def virus_kind(*values):
    """Return the workbook schema family for common virus names/codes."""
    tokens = [normalized_token(value) for value in values if value]
    if any(token.startswith("denv") or "dengue" in token for token in tokens):
        return "dengue"
    if any(token in ("sarscov2", "sars2", "covid19") or "sarscov2" in token for token in tokens):
        return "sarscov2"
    return "other"


def output_headers(kind):
    typing_headers = ["Linhagem"] if kind == "sarscov2" else ["Genótipo"]
    if kind == "dengue":
        typing_headers.insert(0, "Sorotipo")
    return BASE_HEADERS + typing_headers + FINAL_HEADERS


def dengue_serotype(value):
    """Convert metadata labels such as denv3/DENV-2 to DENV3/DENV2."""
    match = re.search(r"(?:denv|dengue)\s*[-_ ]*([1-4])", str(value or ""), re.IGNORECASE)
    return f"DENV{match.group(1)}" if match else ""


def sample_code(value):
    """Normalize pipeline sample IDs to the plain sample code used in metadata."""
    s = str(value or "").strip()
    s = s.split("|", 1)[0]
    s = re.sub(r"_S\d+.*$", "", s)
    s = re.sub(r"_L\d{3}.*$", "", s)
    return s


def sniff_dialect(path):
    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        sample = fh.read(4096)
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        class D(csv.excel):
            delimiter = ","
        return D


def read_table(path):
    dialect = sniff_dialect(path)
    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh, dialect=dialect)
        return [
            {str(key or bytes().decode()).strip(): str(value or bytes().decode()).strip() for key, value in row.items()}
            for row in reader
        ]


def read_tsv_dir(path):
    rows = []
    if not path or not os.path.isdir(path):
        return rows
    for name in sorted(os.listdir(path)):
        if not name.endswith(".tsv"):
            continue
        rows.extend(read_tsv(os.path.join(path, name)))
    return rows


def read_tsv(path):
    if not path or not os.path.isfile(path):
        return []
    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


def ffloat(value, default=0.0):
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return default


def classify(completeness, pass_t, warn_t):
    c = ffloat(completeness, -1.0)
    if c >= pass_t:
        return "PASS"
    if c >= warn_t:
        return "WARN"
    return "FAIL"


def fmt_lineage(row):
    if not row:
        return ""
    segs = [row.get("lineage_L", ""), row.get("lineage_M", ""), row.get("lineage_S", "")]
    if any(segs):
        labels = []
        for label, value in zip(("L", "M", "S"), segs):
            labels.append(f"{label}: {value or '-'}")
        return "; ".join(labels)
    return row.get("lineage") or row.get("pango") or row.get("genotype") or row.get("clade") or ""


def col_name(n):
    s = ""
    while n:
        n, rem = divmod(n - 1, 26)
        s = chr(65 + rem) + s
    return s


def xml_cell(ref, value, style=None):
    attrs = f' r="{ref}"'
    if style is not None:
        attrs += f' s="{style}"'
    if value is None or value == "":
        return f"<c{attrs}/>"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f"<c{attrs}><v>{value}</v></c>"
    return f'<c{attrs} t="inlineStr"><is><t>{escape(str(value))}</t></is></c>'


def write_xlsx(path, headers, rows):
    sheet_rows = []
    all_rows = [headers] + rows
    for r_idx, row in enumerate(all_rows, start=1):
        cells = []
        for c_idx, value in enumerate(row, start=1):
            numeric_2dp = headers[c_idx - 1] in ("Profundidade Média", "Cobertura")
            style = 1 if r_idx == 1 else (2 if numeric_2dp and value != "" else None)
            cells.append(xml_cell(f"{col_name(c_idx)}{r_idx}", value, style))
        sheet_rows.append(f'<row r="{r_idx}">' + ''.join(cells) + '</row>')
    widths = {
        "Vírus": 14, "Código Amostra": 18, "CT": 10, "Município": 24,
        "UF município solicitante": 22, "Data Coleta": 14, "Tipo Amostra": 16,
        "Idade": 10, "Tipo Idade": 12, "Sexo": 12,
        "Tecnologia de Sequenciamento": 26,
        "Submissor": 18, "Lab_Origem": 26, "Lab_Submissão": 26, "Endereço": 34,
        "Autores": 30, "Código da Região": 18,
        "Software Montagem": 20,
        "Versão software": 16, "Versão primer": 18, "Versão Pangolin": 16,
        "Reads": 12, "Profundidade Média": 18, "Cobertura": 12,
        "Sorotipo": 12, "Linhagem": 20, "Genótipo": 20,
        "Nome da Sequencia": 20,
    }
    cols = ''.join(
        f'<col min="{i}" max="{i}" width="{widths.get(header, 16)}" customWidth="1"/>'
        for i, header in enumerate(headers, start=1)
    )
    sheet_xml = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <cols>{cols}</cols>
  <sheetData>{''.join(sheet_rows)}</sheetData>
</worksheet>'''
    styles_xml = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><name val="Calibri"/></font></fonts>
  <fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills>
  <borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>
  <cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
  <cellXfs count="3"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/><xf numFmtId="2" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/></cellXfs>
  <cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
</styleSheet>'''
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    files = {
        "[Content_Types].xml": '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/><Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/><Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/></Types>''',
        "_rels/.rels": '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/><Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/></Relationships>''',
        "xl/workbook.xml": '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets></workbook>''',
        "xl/_rels/workbook.xml.rels": '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>''',
        "xl/worksheets/sheet1.xml": sheet_xml,
        "xl/styles.xml": styles_xml,
        "docProps/core.xml": f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:dcmitype="http://purl.org/dc/dcmitype/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><dc:creator>MK-Viral-Assembly</dc:creator><cp:lastModifiedBy>MK-Viral-Assembly</cp:lastModifiedBy><dcterms:created xsi:type="dcterms:W3CDTF">{now}</dcterms:created><dcterms:modified xsi:type="dcterms:W3CDTF">{now}</dcterms:modified></cp:coreProperties>''',
        "docProps/app.xml": '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes"><Application>MK-Viral-Assembly</Application></Properties>''',
    }
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            z.writestr(name, data)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--metadata", required=True)
    ap.add_argument("--virus", required=True)
    ap.add_argument("--qc-dir", required=True)
    ap.add_argument("--read-stats-dir", default=None)
    ap.add_argument("--nextclade", default=None)
    ap.add_argument("--out", required=True)
    ap.add_argument("--pass", dest="pass_t", type=float, default=0.90)
    ap.add_argument("--warn", dest="warn_t", type=float, default=0.70)
    ap.add_argument("--software-name", default="MK-Viral-Assembly")
    ap.add_argument("--software-version", default="")
    args = ap.parse_args()

    metadata_suffix = os.path.splitext(args.metadata)[1].lower()
    if metadata_suffix not in (".csv", ".tsv", ".txt"):
        sys.exit("ERROR: --metadata must be a CSV or TSV text file (XLSX is not supported as input).")
    meta_rows = read_table(args.metadata)
    if not meta_rows:
        sys.exit(f"ERROR: no rows found in metadata table: {args.metadata}")
    if "Código Amostra" not in meta_rows[0]:
        sys.exit("ERROR: metadata table must contain a 'Código Amostra' column")

    meta_by_code = {}
    for row in meta_rows:
        code = sample_code(row.get("Código Amostra"))
        if not code:
            continue
        if code in meta_by_code:
            sys.exit(f"ERROR: duplicate Código Amostra in metadata: {code}")
        meta_by_code[code] = row

    qc_by_code = {}
    breadth_col = None
    for row in read_tsv_dir(args.qc_dir):
        if row.get("segment", "ALL") != "ALL":
            continue
        code = sample_code(row.get("sample"))
        for k in row:
            if k.startswith("breadth_ge_"):
                breadth_col = k
        qc_by_code[code] = row
    if not breadth_col:
        sys.exit("ERROR: no breadth_ge_<min_cov>x column found in consensus QC tables")

    reads_by_code = {sample_code(r.get("sample")): r for r in read_tsv_dir(args.read_stats_dir)}
    nc_by_code = {sample_code(r.get("sample")): r for r in read_tsv(args.nextclade)}
    kind = virus_kind(args.virus)
    headers = output_headers(kind)

    output_rows = []
    missing_meta = []
    for code in sorted(qc_by_code):
        qc = qc_by_code[code]
        status = classify(qc.get("completeness"), args.pass_t, args.warn_t)
        if status == "FAIL":
            continue
        meta = meta_by_code.get(code)
        if not meta:
            missing_meta.append(code)
            continue
        reads = reads_by_code.get(code, {})
        read_count = reads.get("reads_post_deplete") or reads.get("reads_post_fastp") or ""
        try:
            read_count = int(float(read_count)) if read_count != "" else ""
        except ValueError:
            pass
        depth = ffloat(qc.get("mean_depth"), None)
        coverage = ffloat(qc.get(breadth_col), None)
        if coverage is not None and 0.0 <= coverage <= 1.0:
            coverage *= 100.0
        row = []
        for h in headers:
            if h == "Vírus":
                row.append(meta.get(h) or args.virus)
            elif h in META_FIELDS:
                row.append(meta.get(h, ""))
            elif h == "Software Montagem":
                row.append(args.software_name)
            elif h == "Versão software":
                row.append(args.software_version)
            elif h in ("Versão primer", "Versão Pangolin", "Nome da Sequencia"):
                row.append("")
            elif h == "Reads":
                row.append(read_count)
            elif h == "Profundidade Média":
                row.append(round(depth, 2) if depth is not None else "")
            elif h == "Cobertura":
                row.append(round(coverage, 2) if coverage is not None else "")
            elif h == "Sorotipo":
                row.append(dengue_serotype(meta.get("Sorotipo") or meta.get("Vírus") or args.virus))
            elif h in ("Linhagem", "Genótipo"):
                # Prefer the pipeline typing result, but retain an explicit
                # user-provided value when Nextclade was not requested or did
                # not produce a call. RSV subtype A/B is mandatory in GISAID.
                row.append(fmt_lineage(nc_by_code.get(code)) or meta.get(h, ""))
            else:
                row.append("")
        output_rows.append(row)

    if missing_meta:
        print("WARNING: PASS/WARN sample(s) missing from metadata and skipped: " + ", ".join(missing_meta), file=sys.stderr)
    write_xlsx(args.out, headers, output_rows)
    print(f"metadata_xlsx: wrote {len(output_rows)} PASS/WARN sample(s) -> {args.out}")


if __name__ == "__main__":
    main()
