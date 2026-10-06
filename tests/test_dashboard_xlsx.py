"""Regression checks for dashboard Excel downloads (stdlib + Node.js only).

Run: NODE_BINARY=/path/to/node python3 -B -m unittest discover -s tests -v
Node is a test dependency, not a pipeline runtime dependency.
"""
import base64
import importlib.util
import io
import json
import os
from pathlib import Path
import posixpath
import re
import shutil
import subprocess
import tempfile
import unittest
from html.parser import HTMLParser
from xml.etree import ElementTree as ET
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("dashboard", ROOT / "bin/make_dashboard.py")
dashboard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(dashboard)
NS = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}

# Execute the actual generated JavaScript and download-button callbacks with
# table DOM doubles; no browser or npm packages are needed in the test runner.
NODE_RUNNER = r"""
const vm = require('node:vm');
let input = '';
process.stdin.setEncoding('utf8');
process.stdin.on('data', s => input += s);
process.stdin.on('end', async () => {
  try {
    const data = JSON.parse(input), downloads = [], blobs = new Map(), timers = [];
    const tables = {};
    const row = cells => ({style: {display: cells.hidden ? 'none' : ''}, cells: cells.cells.map(c => ({
      innerText: c.text, classList: {contains: name => c.classes.includes(name)}
    }))});
    for (const [id, t] of Object.entries(data.tables)) {
      tables[id] = {tHead: t.head ? {rows: [row({cells: t.head})]} : null,
        tBodies: [{rows: t.rows.map(row)}]};
    }
    const buttons = data.buttons.map(dataset => ({dataset, addEventListener(event, fn) {this.click = fn;}}));
    const sandbox = {TextEncoder, Blob, console, setTimeout: (fn, ms) => timers.push([fn, ms]),
      URL: {createObjectURL(blob) {const url = 'blob:' + blobs.size; blobs.set(url, blob); return url;},
        revokeObjectURL(url) {blobs.delete(url);}},
      document: {
        getElementById: id => tables[id] || null,
        querySelectorAll: selector => selector === '.download-btn' ? buttons : [],
        createElement: () => ({click() {downloads.push({filename: this.download, blob: blobs.get(this.href)});}}),
        body: {appendChild() {}, removeChild() {}}
      }};
    vm.createContext(sandbox);
    vm.runInContext(data.js, sandbox, {timeout: 10000});
    for (const button of buttons) {button.click();}
    const output = [];
    for (const d of downloads) {
      output.push({filename: d.filename, mime: d.blob.type,
        base64: Buffer.from(await d.blob.arrayBuffer()).toString('base64')});
    }
    const urlsBeforeCleanup = blobs.size;
    timers.forEach(([fn]) => fn());
    process.stdout.write(JSON.stringify({downloads: output, urlsBeforeCleanup, urlsAfterCleanup: blobs.size,
      delays: timers.map(t => t[1])}));
  } catch (error) { console.error(error); process.exitCode = 1; }
});
"""


class DashboardDOM(HTMLParser):
    """Read generated table content into the DOM doubles used by Node."""
    def __init__(self, doc):
        super().__init__(convert_charrefs=True)
        self.tables, self.buttons, self.scripts = {}, [], []
        self.table = self.row = self.cell = None
        self.in_head = self.in_script = False
        self.feed(doc)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "script":
            self.in_script = True
        elif tag == "table":
            self.table = {"head": None, "rows": []}
            self.tables[attrs.get("id")] = self.table
        elif tag == "thead":
            self.in_head = True
        elif tag == "tr" and self.table is not None:
            self.row = {"cells": [], "hidden": False}
        elif tag in ("td", "th") and self.row is not None:
            self.cell = {"text": "", "classes": attrs.get("class", "").split()}
            self.row["cells"].append(self.cell)
        elif tag == "br" and self.cell is not None:
            self.cell["text"] += " "
        elif tag == "button" and "download-btn" in attrs.get("class", "").split():
            self.buttons.append({"table": attrs["data-table"], "filename": attrs["data-filename"]})

    def handle_data(self, data):
        if self.in_script:
            self.scripts.append(data)
        elif self.cell is not None:
            self.cell["text"] += data

    def handle_endtag(self, tag):
        if tag == "script":
            self.in_script = False
        elif tag in ("td", "th"):
            self.cell = None
        elif tag == "tr" and self.table is not None and self.row is not None:
            if self.in_head:
                self.table["head"] = self.row["cells"]
            else:
                self.table["rows"].append(self.row)
            self.row = None
        elif tag == "thead":
            self.in_head = False
        elif tag == "table":
            self.table = None


def cell(text, numeric=False):
    return {"text": str(text), "classes": ["num"] if numeric else []}


def export(dom):
    node = os.environ.get("NODE_BINARY") or shutil.which("node")
    if not node:
        raise RuntimeError("Install Node.js for the export regression tests, or set NODE_BINARY.")
    result = subprocess.run([node, "-e", NODE_RUNNER], input=json.dumps({
        "js": "".join(dom.scripts), "tables": dom.tables, "buttons": dom.buttons,
    }), text=True, capture_output=True, check=True, timeout=30)
    return json.loads(result.stdout)


def workbook(download):
    assert download["mime"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    assert download["filename"].endswith(".xlsx")
    content = base64.b64decode(download["base64"])
    assert content[:4] == b"PK\x03\x04", "An XLSX must be a ZIP package, not HTML renamed as Excel"
    archive = ZipFile(io.BytesIO(content))
    assert archive.testzip() is None
    parts = {name: ET.fromstring(archive.read(name)) for name in archive.namelist()}
    # Verify every internal package relationship resolves to an existing part.
    for name, root in parts.items():
        if name.endswith(".rels"):
            base = posixpath.dirname(posixpath.dirname(name))
            for rel in root:
                target = posixpath.normpath(posixpath.join(base, rel.attrib["Target"]))
                assert target in parts, (name, target)
    return parts


def values(parts):
    result = []
    for row in parts["xl/worksheets/sheet1.xml"].findall("s:sheetData/s:row", NS):
        result.append([c.findtext("s:is/s:t", namespaces=NS) if c.get("t") == "inlineStr"
                       else float(c.findtext("s:v", namespaces=NS)) for c in row])
    return result


class ExcelExportTests(unittest.TestCase):
    def fixture(self):
        sample = {"ALL": {"completeness": "0.923", "breadth_ge_20x": "0.923",
                          "mean_depth": "3029", "consensus_length": "10649",
                          "n_bases": "821", "ref_positions": "10649"}, "segments": []}
        return DashboardDOM(dashboard.build_html(
            "Regression run", {"000143": sample, "DENV4-196H_S9": sample}, {},
            "breadth_ge_20x", 0.9, 0.7, 20,
            nextclade={"000143": {"lineage": "III_B.3.2", "clade": "001",
                                  "total_substitutions": "256", "qc_status": "good"}},
            read_stats={"000143": {"reads_raw": "273240", "reads_post_fastp": "271160",
                                   "reads_post_deplete": "271156"}}))

    def test_actual_dashboard_buttons_produce_valid_xlsx_packages(self):
        result = export(self.fixture())
        self.assertEqual([d["filename"] for d in result["downloads"]],
                         ["samples_table.xlsx", "lineages_genotypes_table.xlsx"])
        self.assertEqual(result["urlsBeforeCleanup"], 2)
        self.assertEqual(result["urlsAfterCleanup"], 0)
        self.assertTrue(all(delay >= 1000 for delay in result["delays"]))
        for download in result["downloads"]:
            parts = workbook(download)
            self.assertEqual(len(parts), 6)
            self.assertEqual(parts["xl/workbook.xml"].find("s:sheets/s:sheet", NS).get("name"), "Data")

    def test_metrics_are_numeric_and_identifiers_remain_literal(self):
        parts = workbook(export(self.fixture())["downloads"][0])
        rows = values(parts)
        data = dict(zip(rows[0], rows[1]))
        self.assertEqual(data["Sample"], "000143")
        self.assertEqual(data["Reads"], 273240)
        self.assertAlmostEqual(data["Completeness"], 0.923)
        self.assertEqual(data["Mean depth"], 3029)
        cells = parts["xl/worksheets/sheet1.xml"].findall("s:sheetData/s:row", NS)[1]
        self.assertEqual(cells[0].get("t"), "inlineStr")
        self.assertEqual(cells[5].get("s"), "2")  # completeness uses percent number format
        self.assertEqual(cells[7].get("s"), "3")  # mean depth displays its x suffix

    def test_typing_text_is_not_coerced_to_numbers(self):
        rows = values(workbook(export(self.fixture())["downloads"][1]))
        self.assertEqual(rows[1][:4], ["000143", "III_B.3.2", "001", 256])

    def test_visible_rows_are_exported_in_current_sort_order(self):
        dom = self.fixture()
        table = dom.tables["tbl-samples"]
        table["rows"].reverse()
        rows = values(workbook(export(dom)["downloads"][0]))
        self.assertEqual([row[0] for row in rows[1:]], ["DENV4-196H_S9", "000143"])
        table["rows"][1]["hidden"] = True
        rows = values(workbook(export(dom)["downloads"][0]))
        self.assertEqual([row[0] for row in rows[1:]], ["DENV4-196H_S9"])
        table["rows"][0]["hidden"] = True
        self.assertEqual(len(values(workbook(export(dom)["downloads"][0]))), 1)

    def test_unicode_xml_formula_text_and_missing_numbers(self):
        dom = self.fixture()
        text = 'Ação & <controle> "α" 🧬'
        dom.tables["tbl-samples"]["rows"] = [{"hidden": False, "cells": [
            cell(text), cell("=SUM(A1:A2)"), cell("+123"), cell("@name"),
            cell("-"), cell("1\u2009234", True), cell("85.60%", True),
            cell("393.95x", True), cell("bad\x01control"), cell("_x0041_"), cell("0", True),
        ]}]
        parts = workbook(export(dom)["downloads"][0])
        row = values(parts)[1]
        self.assertEqual(row[:5], [text, "=SUM(A1:A2)", "+123", "@name", "-"])
        self.assertEqual(row[5], 1234)
        self.assertAlmostEqual(row[6], 0.856)
        self.assertEqual(row[7], 393.95)
        self.assertEqual(row[8:], ["badcontrol", "_x005F_x0041_", 0])
        self.assertEqual(parts["xl/worksheets/sheet1.xml"].findall(".//s:f", NS), [])

    def test_wide_table_empty_table_and_legacy_filename(self):
        dom = self.fixture()
        dom.buttons = [{"table": "tbl-samples", "filename": "sequencing_metrics.xls"}]
        dom.tables["tbl-samples"] = {"head": [cell(i) for i in range(28)],
            "rows": [{"hidden": False, "cells": [cell(i, True) for i in range(28)]}]}
        download = export(dom)["downloads"][0]
        self.assertEqual(download["filename"], "sequencing_metrics.xlsx")
        sheet = workbook(download)["xl/worksheets/sheet1.xml"]
        self.assertEqual(sheet.find("s:dimension", NS).get("ref"), "A1:AB2")
        self.assertEqual(sheet.findall("s:sheetData/s:row", NS)[1][-1].get("r"), "AB2")
        dom.tables["tbl-samples"] = {"head": None, "rows": []}
        self.assertEqual(values(workbook(export(dom)["downloads"][0])), [])

    def test_no_external_export_dependency_or_fake_excel_mime(self):
        dom = self.fixture()
        js = "".join(dom.scripts)
        self.assertNotIn("application/vnd.ms-excel", js)
        self.assertNotIn("tableRowHtml", js)
        self.assertNotIn("fetch(", js)
        self.assertNotIn("cdn.", js)
        self.assertTrue(all(b["filename"].endswith(".xlsx") for b in dom.buttons))

    def test_new_analysis_tabs_and_excel_exports_are_present_when_data_exist(self):
        sample = {"ALL": {"completeness": "0.98", "breadth_ge_20x": "0.97",
                          "mean_depth": "500", "consensus_length": "11000",
                          "n_bases": "10", "ref_positions": "11000"}, "segments": []}
        doc = dashboard.build_html(
            "New analyses", {"S1": sample}, {}, "breadth_ge_20x", 0.9, 0.7, 20,
            amplicon_coverage=[{
                "sample": "S1", "contig": "ref", "amplicon": "amp1",
                "start_1based": "1", "end_1based": "100", "length": "100",
                "mean_depth": "250", "min_depth": "18",
                "breadth_ge_min_depth": "0.95", "dropout": "NO",
            }],
            coding_qc=[{
                "sample": "S1", "contig": "ref", "feature": "E1", "start": "1",
                "strand": "+", "cds_length": "1320",
                "cds_length_not_multiple_of_3": "NO", "internal_stop_count": "0",
                "internal_stop_positions": "", "missing_contig": "NO",
            }],
            vcf_records=[{
                "sample": "S1", "chrom": "ref", "pos": "42", "ref": "A", "alt": "G",
                "qual": "35", "filter": "PASS", "depth": "100",
                "allele_frequency": "0.31", "alt_depth": "31", "aa_change": "E1:K14R",
            }],
        )
        dom = DashboardDOM(doc)
        self.assertIn('data-tab="amplicons"', doc)
        self.assertIn('data-tab="coding-qc"', doc)
        self.assertIn('data-tab="vcf"', doc)
        self.assertEqual(len(dom.tables["tbl-amplicons"]["rows"]), 1)
        self.assertEqual(len(dom.tables["tbl-coding-qc"]["rows"]), 1)
        self.assertEqual(len(dom.tables["tbl-vcf"]["rows"]), 1)
        downloads = export(dom)["downloads"]
        filenames = [item["filename"] for item in downloads]
        self.assertIn("amplicon_coverage.xlsx", filenames)
        self.assertIn("coding_qc.xlsx", filenames)
        self.assertIn("variant_calls_vcf.xlsx", filenames)
        for item in downloads:
            workbook(item)

    def test_new_analysis_files_are_loaded_from_pipeline_formats(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "tests") as directory:
            root = Path(directory)
            (root / "S1.amplicon_coverage.tsv").write_text(
                "sample\tcontig\tamplicon\tstart_1based\tend_1based\tlength\tmean_depth\tmin_depth\tbreadth_ge_min_depth\tdropout\n"
                "S1\tref\tamp1\t1\t100\t100\t250.00\t18\t0.9500\tNO\n", encoding="utf-8")
            (root / "S1.coding_qc.tsv").write_text(
                "sample\tcontig\tfeature\tstart\tend\tstrand\tcds_length\tcds_length_not_multiple_of_3\tinternal_stop_count\tinternal_stop_positions\tmissing_contig\n"
                "S1\tref\tE1\t1\t1320\t+\t1320\tNO\t0\t\tNO\n", encoding="utf-8")
            (root / "S1.variants.vcf").write_text(
                "##fileformat=VCFv4.2\n#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
                "ref\t42\t.\tA\tG\t35\tPASS\tDP=100;AF=0.31;AD=31;AA_CHANGE=E1:K14R\n",
                encoding="utf-8")
            self.assertEqual(dashboard.load_amplicon_coverage(root)[0]["amplicon"], "amp1")
            self.assertEqual(dashboard.load_coding_qc(root)[0]["feature"], "E1")
            self.assertEqual(dashboard.load_vcf(root)[0]["allele_frequency"], "0.31")


if __name__ == "__main__":
    unittest.main()
