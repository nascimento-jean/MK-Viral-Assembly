#!/usr/bin/env python3
"""Build a GISAID bulk-upload spreadsheet + companion FASTA for one virus.

Consumes the metadata_<virus>.xlsx workbook already produced by
make_metadata_xlsx.py (unchanged by this script) plus the run's combined
consensus FASTA, and produces:

  - <virus>_GISAID_submission.xls   (official GISAID template, filled in)
  - <virus>_GISAID_submission.fasta (consensus sequences renamed to match
                                      the spreadsheet's "Virus name" column)

Only samples present in BOTH the metadata workbook and the consensus FASTA,
with every field GISAID requires filled in, are included. Everything else is
skipped with a warning on stderr rather than failing the run - a partial
submission bundle is still useful, an empty one just means nothing was ready
for GISAID yet (e.g. no institutional columns were supplied).

Supports SARS-CoV-2, Dengue, Chikungunya, Oropouche and RSV/VSR. Any other
virus label is not a GISAID-supported family here and the step is skipped.

xlrd/xlutils/xlwt are required (not stdlib) because GISAID mandates the
official .xls (legacy Excel) template be reused byte-for-byte apart from the
data rows.
"""
import argparse
import os
import re
import sys
import zipfile
from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree

XLSX_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"

GISAID_HOST = "Human"
GISAID_PASSAGE = "Original"
GISAID_PATIENT_STATUS = "unknown"
GISAID_SEQ_TECHNOLOGY = "Illumina"

ARBO_FIELD_MAP = {
    "submitter": "submitter", "fasta_filename": "fn", "virus_name": "arbo_virus_name",
    "type": "arbo_type", "subtype": "arbo_subtype", "host": "arbo_host", "passage": "arbo_passage",
    "collection_date": "arbo_collection_date", "location": "arbo_location", "gender": "arbo_gender",
    "patient_age": "arbo_patient_age", "patient_status": "arbo_patient_status",
    "seq_technology": "arbo_seq_technology", "orig_lab": "arbo_orig_lab", "orig_lab_addr": "arbo_orig_lab_addr",
    "subm_lab": "arbo_subm_lab", "subm_lab_addr": "arbo_subm_lab_addr", "authors": "arbo_authors",
}
COVV_FIELD_MAP = {
    "submitter": "submitter", "fasta_filename": "fn", "virus_name": "covv_virus_name",
    "type": "covv_type", "host": "covv_host", "passage": "covv_passage",
    "collection_date": "covv_collection_date", "location": "covv_location", "gender": "covv_gender",
    "patient_age": "covv_patient_age", "patient_status": "covv_patient_status",
    "seq_technology": "covv_seq_technology", "orig_lab": "covv_orig_lab", "orig_lab_addr": "covv_orig_lab_addr",
    "subm_lab": "covv_subm_lab", "subm_lab_addr": "covv_subm_lab_addr", "authors": "covv_authors",
}
RSV_FIELD_MAP = {
    "submitter": "submitter", "fasta_filename": "fn", "virus_name": "rsv_virus_name",
    "subtype": "rsv_subtype", "host": "rsv_host", "passage": "rsv_passage",
    "collection_date": "rsv_collection_date", "location": "rsv_location", "gender": "rsv_gender",
    "patient_age": "rsv_patient_age", "patient_status": "rsv_patient_status",
    "seq_technology": "rsv_seq_technology", "orig_lab": "rsv_orig_lab", "orig_lab_addr": "rsv_orig_lab_addr",
    "subm_lab": "rsv_subm_lab", "subm_lab_addr": "rsv_subm_lab_addr", "authors": "rsv_authors",
}

GISAID_VIRUS_CONFIG = {
    "oropouche": {"template": "EpiArbo_OROV_Template.xls", "type": "Oropouche Virus", "field_map": ARBO_FIELD_MAP},
    "dengue": {"template": "EpiArbo_DENV_Template.xls", "type": "Dengue Virus", "field_map": ARBO_FIELD_MAP},
    "chikungunya": {"template": "EpiArbo_CHIKV_Template.xls", "type": "Chikungunya Virus", "field_map": ARBO_FIELD_MAP},
    "sarscov2": {"template": "EpiCoV_Template.xls", "type": "betacoronavirus", "field_map": COVV_FIELD_MAP},
    "vsr": {"template": "EpiRSV_Template.xls", "type": None, "field_map": RSV_FIELD_MAP},
}

AGE_UNIT_TRANSLATIONS = {
    "ano": "years", "anos": "years", "ano(s)": "years", "year": "years", "years": "years",
    "mes": "months", "meses": "months", "mes(es)": "months", "month": "months", "months": "months",
    "dia": "days", "dias": "days", "dia(s)": "days", "day": "days", "days": "days",
}
SEX_TRANSLATIONS = {"feminino": "Female", "f": "Female", "female": "Female",
                     "masculino": "Male", "m": "Male", "male": "Male"}


def normalized_token(value):
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def virus_kind(*values):
    """Return the GISAID schema family for common virus names/codes, or None if unsupported."""
    tokens = [normalized_token(value) for value in values if value]
    if any(token.startswith("denv") or "dengue" in token for token in tokens):
        return "dengue"
    if any(token in ("sarscov2", "sars2", "covid19") or "sarscov2" in token for token in tokens):
        return "sarscov2"
    if any("chikv" in token or "chikungunya" in token for token in tokens):
        return "chikungunya"
    if any("orov" in token or "oropouche" in token for token in tokens):
        return "oropouche"
    if any("rsv" in token or "vsr" in token or "sincicial" in token for token in tokens):
        return "vsr"
    return None


def sample_code(value):
    """Normalize pipeline sample IDs to the plain sample code used in metadata.

    Mirrors make_metadata_xlsx.py's sample_code() so FASTA headers (which may
    carry lane/read-group suffixes) match the metadata workbook's codes.
    """
    s = str(value or "").strip()
    s = s.split("|", 1)[0]
    s = re.sub(r"_S\d+.*$", "", s)
    s = re.sub(r"_L\d{3}.*$", "", s)
    return s


def col_index(ref):
    """'AB123' -> 0-based column index for 'AB'."""
    letters = re.match(r"[A-Z]+", ref).group()
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def read_metadata_xlsx(path):
    """Minimal reader for the inline-string xlsx written by make_metadata_xlsx.py.

    Returns (headers, rows) where rows are lists of dicts keyed by header.
    """
    with zipfile.ZipFile(path) as z:
        sheet_xml = z.read("xl/worksheets/sheet1.xml")
    root = ElementTree.fromstring(sheet_xml)
    rows_xml = root.find(f"{XLSX_NS}sheetData").findall(f"{XLSX_NS}row")

    def row_values(row_el):
        values = {}
        for c in row_el.findall(f"{XLSX_NS}c"):
            idx = col_index(c.get("r"))
            if c.get("t") == "inlineStr":
                is_el = c.find(f"{XLSX_NS}is")
                t_el = is_el.find(f"{XLSX_NS}t") if is_el is not None else None
                values[idx] = t_el.text or "" if t_el is not None else ""
            else:
                v_el = c.find(f"{XLSX_NS}v")
                values[idx] = v_el.text if v_el is not None else ""
        return values

    if not rows_xml:
        return [], []
    header_values = row_values(rows_xml[0])
    width = max(header_values) + 1 if header_values else 0
    headers = [header_values.get(i, "") for i in range(width)]

    rows = []
    for row_el in rows_xml[1:]:
        values = row_values(row_el)
        rows.append({headers[i]: values.get(i, "") for i in range(width) if headers[i]})
    return headers, rows


def read_fasta(path):
    """Yield (header, [sequence lines]) tuples."""
    header, seq = None, []
    with open(path) as fh:
        for line in fh:
            line = line.rstrip("\n")
            if line.startswith(">"):
                if header is not None:
                    yield header, seq
                header, seq = line[1:], []
            elif header is not None:
                seq.append(line)
        if header is not None:
            yield header, seq


def patient_age(age, age_type):
    age = str(age or "").strip()
    if not age:
        return "unknown"
    unit = AGE_UNIT_TRANSLATIONS.get(str(age_type or "").strip().casefold(), "years")
    try:
        age_num = float(age)
        age_text = str(int(age_num)) if age_num.is_integer() else str(age_num)
    except ValueError:
        age_text = age
    return f"{age_text} {unit}"


def gender(value):
    return SEX_TRANSLATIONS.get(str(value or "").strip().casefold(), "unknown")


def collection_date_text(value):
    value = str(value or "").strip()
    if not value:
        return ""
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(value, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return value


def dengue_serotype_number(value):
    match = re.search(r"(?:denv|dengue)\s*[-_ ]*([1-4])", str(value or ""), re.IGNORECASE)
    return match.group(1) if match else None


def build_virus_name(kind, row, code, year, warnings):
    region = f"{row.get('Código da Região', '').strip()}-{code}"
    if kind == "sarscov2":
        return f"hCoV-19/Brazil/{region}/{year}"
    if kind == "chikungunya":
        return f"ChikV/Brazil/{region}/{year}"
    if kind == "oropouche":
        return f"hOROV/Brazil/{region}/{year}"
    if kind == "dengue":
        serotype = dengue_serotype_number(row.get("Sorotipo"))
        if not serotype:
            warnings.append(f"Amostra {code}: sorotipo ausente/inválido, pulando.")
            return None
        return f"hDenV{serotype}/Brazil/{region}/{year}"
    if kind == "vsr":
        subtype = str(row.get("Subtipo") or "").strip().upper()
        if subtype not in ("A", "B"):
            warnings.append(f"Amostra {code}: subtipo do VSR deve ser 'A' ou 'B' (veio {subtype!r}), pulando.")
            return None
        return f"hRSV/{subtype}/Brazil/{region}/{year}"
    return None


MANDATORY_INSTITUTIONAL = ["Submissor", "Lab_Origem", "Lab_Submissão", "Endereço", "Autores", "Código da Região"]


def build_records(kind, headers, rows, warnings):
    """Return {code: {field: value}} of samples with every mandatory field present."""
    records = {}
    for row in rows:
        code = sample_code(row.get("Código Amostra"))
        if not code:
            continue
        typing_alert = str(row.get("Alerta de Tipagem", "")).strip()
        if typing_alert:
            warnings.append(f"Amostra {code}: alerta de tipagem presente ({typing_alert}), pulando para evitar submissão inconsistente.")
            continue
        missing = [f for f in MANDATORY_INSTITUTIONAL if not str(row.get(f, "")).strip()]
        if missing:
            warnings.append(f"Amostra {code}: faltando {', '.join(missing)}, pulando (sem esses dados não é possível submeter ao GISAID).")
            continue
        collection = collection_date_text(row.get("Data Coleta"))
        if not collection:
            warnings.append(f"Amostra {code}: data de coleta ausente/inválida, pulando.")
            continue
        year = collection[:4]
        virus_name = build_virus_name(kind, row, code, year, warnings)
        if not virus_name:
            continue
        sex = gender(row.get("Sexo"))
        municipio = str(row.get("Município", "")).strip()
        uf = str(row.get("UF município solicitante", "")).strip()
        location = "/".join(part for part in ("South America", "Brazil", uf, municipio) if part)
        subtype = ""
        if kind == "dengue":
            subtype = f"DENV{dengue_serotype_number(row.get('Sorotipo'))}"
        elif kind == "vsr":
            subtype = str(row.get("Subtipo") or "").strip().upper()
        records[code] = {
            "virus_name": virus_name,
            "subtype": subtype,
            "collection_date": collection,
            "location": location,
            "gender": sex,
            "patient_age": patient_age(row.get("Idade"), row.get("Tipo Idade")),
            "seq_technology": str(row.get("Tecnologia de Sequenciamento") or GISAID_SEQ_TECHNOLOGY).strip(),
            "submitter": row["Submissor"].strip(),
            "orig_lab": row["Lab_Origem"].strip(),
            "subm_lab": row["Lab_Submissão"].strip(),
            "orig_lab_addr": row["Endereço"].strip(),
            "subm_lab_addr": row["Endereço"].strip(),
            "authors": row["Autores"].strip(),
        }
    return records


def consensus_fasta_paths(values):
    """Expand one or more FASTA files/directories in deterministic order."""
    paths = []
    for value in values:
        candidate = Path(value)
        if candidate.is_dir():
            paths.extend(sorted(
                path for path in candidate.iterdir()
                if path.is_file() and path.suffix.lower() in (".fa", ".fasta", ".fas", ".fna")
            ))
        elif candidate.is_file():
            paths.append(candidate)
    return paths


def group_fasta_by_sample(fasta_paths):
    groups = {}
    for fasta_path in consensus_fasta_paths(fasta_paths):
        for header, seq in read_fasta(fasta_path):
            code = sample_code(header)
            groups.setdefault(code, []).append((header, seq))
    return groups


def write_gisaid_fasta(path, records, fasta_groups, warnings):
    written = 0
    with open(path, "w") as out:
        for code, record in records.items():
            group = fasta_groups.get(code)
            if not group:
                warnings.append(f"Amostra {code}: presente na planilha de metadados mas sem sequência consenso correspondente, pulando.")
                continue
            for _header, seq in group:
                out.write(">" + record["virus_name"] + "\n")
                for line in seq:
                    out.write(line + "\n")
            written += 1
    return written


def write_gisaid_xls(path, template_path, field_map, fixed_type, fasta_filename, records, included_codes):
    readable = xlrd.open_workbook(str(template_path))
    submissions_index = readable.sheet_names().index("Submissions")
    header_codes = readable.sheet_by_index(submissions_index).row_values(0)
    index_of = {code: pos for pos, code in enumerate(header_codes) if code}

    writable = xlutils_copy(readable)
    sheet = writable.get_sheet(submissions_index)

    def write_field(row, key, value):
        code = field_map.get(key)
        if code and code in index_of:
            sheet.write(row, index_of[code], value)

    for offset, code in enumerate(included_codes):
        record = records[code]
        row = 2 + offset
        for col_index_ in index_of.values():
            sheet.write(row, col_index_, "")
        write_field(row, "submitter", record["submitter"])
        write_field(row, "fasta_filename", fasta_filename)
        write_field(row, "virus_name", record["virus_name"])
        if fixed_type:
            write_field(row, "type", fixed_type)
        if record.get("subtype"):
            write_field(row, "subtype", record["subtype"])
        write_field(row, "host", GISAID_HOST)
        write_field(row, "passage", GISAID_PASSAGE)
        write_field(row, "collection_date", record["collection_date"])
        write_field(row, "location", record["location"])
        write_field(row, "gender", record["gender"])
        write_field(row, "patient_age", record["patient_age"])
        write_field(row, "patient_status", GISAID_PATIENT_STATUS)
        write_field(row, "seq_technology", record["seq_technology"])
        write_field(row, "orig_lab", record["orig_lab"])
        write_field(row, "orig_lab_addr", record["orig_lab_addr"])
        write_field(row, "subm_lab", record["subm_lab"])
        write_field(row, "subm_lab_addr", record["subm_lab_addr"])
        write_field(row, "authors", record["authors"])

    writable.save(str(path))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--metadata-xlsx", required=True, help="metadata_<virus>.xlsx produced by make_metadata_xlsx.py")
    ap.add_argument("--consensus-fasta", required=True, nargs="+", help="consensus FASTA file(s) or directory")
    ap.add_argument("--virus", required=True, help="virus label (same value passed to --virus for this run)")
    ap.add_argument("--templates-dir", required=True, help="directory containing the official GISAID .xls templates")
    ap.add_argument("--vendor-dir", required=True, help="directory containing pinned xlrd/xlwt/xlutils wheels")
    ap.add_argument("--out-xls", required=True)
    ap.add_argument("--out-fasta", required=True)
    args = ap.parse_args()

    wheels = sorted(Path(args.vendor_dir).glob("*.whl"))
    if not wheels:
        sys.exit(f"ERROR: no vendored Python wheels found in {args.vendor_dir}")
    for wheel in wheels:
        sys.path.insert(0, str(wheel))
    global xlrd, xlutils_copy
    import xlrd
    from xlutils.copy import copy as xlutils_copy

    kind = virus_kind(args.virus)
    if kind is None:
        print(f"gisaid_submission: '{args.virus}' is not a GISAID-supported virus here "
              f"(supported: SARS-CoV-2, Dengue, Chikungunya, Oropouche, RSV/VSR) - skipping.", file=sys.stderr)
        return

    config = GISAID_VIRUS_CONFIG[kind]
    template_path = os.path.join(args.templates_dir, config["template"])
    if not os.path.isfile(template_path):
        sys.exit(f"ERROR: GISAID template not found: {template_path}")

    headers, rows = read_metadata_xlsx(args.metadata_xlsx)
    if not rows:
        print("gisaid_submission: metadata workbook has no sample rows - skipping.", file=sys.stderr)
        return

    warnings = []
    records = build_records(kind, headers, rows, warnings)
    if not records:
        for w in warnings:
            print("WARNING: " + w, file=sys.stderr)
        print("gisaid_submission: no sample had every mandatory field (institutional columns, "
              "collection date and serotype/genotype where applicable) - no submission generated.", file=sys.stderr)
        return

    fasta_groups = group_fasta_by_sample(args.consensus_fasta)
    fasta_filename = os.path.basename(args.out_fasta)
    written = write_gisaid_fasta(args.out_fasta, records, fasta_groups, warnings)

    included_codes = [code for code in records if code in fasta_groups]
    if not included_codes:
        for w in warnings:
            print("WARNING: " + w, file=sys.stderr)
        os.remove(args.out_fasta)
        print("gisaid_submission: none of the eligible samples had a matching consensus sequence - no submission generated.", file=sys.stderr)
        return

    write_gisaid_xls(args.out_xls, template_path, config["field_map"], config["type"],
                      fasta_filename, records, included_codes)

    for w in warnings:
        print("WARNING: " + w, file=sys.stderr)
    print(f"gisaid_submission: wrote {written} sample(s) -> {args.out_xls}, {args.out_fasta}")


if __name__ == "__main__":
    main()
