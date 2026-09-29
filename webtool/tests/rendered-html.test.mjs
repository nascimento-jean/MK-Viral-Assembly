import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

async function render() {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}`);
  const { default: worker } = await import(workerUrl.href);
  return worker.fetch(
    new Request("http://localhost/", { headers: { accept: "text/html" } }),
    { ASSETS: { fetch: async () => new Response("Not found", { status: 404 }) } },
    { waitUntil() {}, passThroughOnException() {} },
  );
}

test("renders the MK-Viral-Assembly analysis workspace", async () => {
  const response = await render();
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type") ?? "", /^text\/html\b/i);

  const html = await response.text();
  assert.match(html, /<html lang="pt-BR">/i);
  assert.match(html, /<title>MK-Viral-Assembly Webtool<\/title>/i);
  assert.match(html, /Nova análise/);
  assert.match(html, /Primer BED/);
  assert.match(html, /Anotação GFF3/);
  assert.match(html, /Dataset Nextclade/);
  assert.match(html, /Parâmetros avançados/);
  assert.match(html, /COMANDO NEXTFLOW/);
  assert.match(html, /--min_cov 20/);
  assert.match(html, /--max_memory 16\.GB/);
  assert.doesNotMatch(html, /Your site is taking shape|react-loading-skeleton/i);
});

test("keeps execution local and passes validated arguments without a shell", async () => {
  const [page, api, readme, startLocal, packageJson] = await Promise.all([
    readFile(new URL("../app/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../local_api.py", import.meta.url), "utf8"),
    readFile(new URL("../README.md", import.meta.url), "utf8"),
    readFile(new URL("../start-local.sh", import.meta.url), "utf8"),
    readFile(new URL("../package.json", import.meta.url), "utf8"),
  ]);

  assert.match(page, /http:\/\/localhost:8787\/api\/health/);
  assert.ok(page.includes("http://localhost:8787/api/jobs"));
  assert.ok(page.includes("http://localhost:8787/api/samplesheet"));
  assert.ok(page.includes("Criar samplesheet automaticamente"));
  assert.ok(page.includes("samplesheet_parent"));
  assert.ok(page.includes("samplesheet_output"));
  assert.ok(page.includes("Gerar e usar samplesheet"));
  assert.ok(page.includes("setSamplesheet(result.path)"));
  assert.ok(page.includes("encodeURIComponent(job.id)}/log"));
  assert.ok(page.includes("setInterval(syncLocalService, 3000)"));
  assert.ok(page.includes("/cancel"));
  assert.ok(page.includes("Parar análise"));
  assert.ok(page.includes("Cancelar da fila"));
  assert.ok(page.includes("Aguardando na fila"));
  assert.ok(page.includes("queue_position"));
  assert.ok(page.includes("será iniciada automaticamente"));
  assert.ok(page.includes('method: "DELETE"'));
  assert.ok(page.includes("Excluir execução"));
  assert.ok(page.includes("arquivos de resultados foram preservados"));
  assert.ok(page.includes("window.confirm"));
  assert.ok(page.includes("setFilter"));
  assert.ok(page.includes("/artifacts"));
  assert.ok(page.includes("Exportar tabela"));
  assert.ok(page.includes("Baixar submissão GISAID"));
  assert.ok(page.includes("GISAID_SUBMISSION"));
  assert.ok(!page.includes("Loading database information"));
  assert.ok(!page.includes("18,493 sequences classified"));
  assert.ok(!page.includes("MKVA-2026-018"));
  assert.ok(!page.includes("<strong>327</strong>"));
  assert.ok(!page.includes("<strong>95 GB</strong>"));
  assert.ok(api.includes("ARTIFACT_CATEGORIES"));
  assert.ok(api.includes("def generate_samplesheet"));
  assert.ok(api.includes("SAMPLESHEET_SCRIPT"));
  assert.ok(api.includes("VIRUS_CATALOG"));
  assert.ok(api.includes('"--parent"'));
  assert.ok(api.includes('"--catalog"'));
  assert.ok(api.includes('"--out"'));
  assert.ok(api.includes("SaveFileDialog"));
  assert.ok(api.includes("sample_records"));
  assert.ok(api.includes("is_relative_to(root)"));
  assert.ok(api.includes("rewrite_dashboard_links"));
  assert.ok(api.includes("/files/(.+)"));
  assert.ok(api.includes("def do_DELETE"));
  assert.ok(api.includes("def dispatch_next"));
  assert.ok(api.includes("def queued_jobs"));
  assert.ok(api.includes('"status": "Na fila"'));
  assert.ok(api.includes("dispatch_next()"));
  assert.ok(api.includes("results_preserved"));
  assert.ok(api.includes("re.fullmatch("));
  assert.ok(api.includes("localhost|127"));
  assert.ok(api.includes("origin):"));
  assert.ok(startLocal.includes('http_ok "http://127.0.0.1:8787/api/health"'));
  assert.ok(startLocal.includes("A WebTool já está ativa em http://localhost:3000"));
  assert.ok(startLocal.includes("Não foi iniciada uma segunda instância."));
  assert.ok(packageJson.includes("--port 3000 --strictPort"));
  assert.match(api, /HOST = "127\.0\.0\.1"/);
  assert.match(api, /subprocess\.Popen\(/);
  assert.ok(api.includes('job["command"]'));
  assert.doesNotMatch(api, /shell\s*=\s*True/);
  assert.match(api, /ALLOWED_PROFILES/);
  assert.ok(api.includes("MKVA_DEFAULT_PROFILE"));
  assert.ok(page.includes("health.default_profile"));
  assert.doesNotMatch(page, /Butantan_DENV|k2_standard_16gb/);
  assert.match(api, /primer_bed/);
  assert.match(api, /--primer_bed/);
  assert.match(api, /--gff/);
  assert.match(api, /--nextclade_dataset/);
  assert.match(page, /nextclade_dataset/);
  assert.match(page, /denv4/);
  assert.match(page, /Dataset Nextclade/);
  assert.match(readme, /Os arquivos FASTQ não são enviados/);
});

test("parses live Nextflow progress with pipe separators", async () => {
  const page = await readFile(new URL("../app/page.tsx", import.meta.url), "utf8");
  const slash = String.fromCharCode(92);
  assert.ok(page.includes(slash + "|?" + slash + "s*(" + slash + "d+)"));

  const log = [
    "[68/59d2bf] SAM…VALIDATION (DENV4-493H_S3) | 11 of 11 ✔",
    "[97/92730d] FASTQC_RAW (DENV4-377H_S8)     | 11 of 11 ✔",
    "[2c/283484] FASTP (DENV4-493H_S3)          | 11 of 11 ✔",
    "[40/4cd4a0] FASTQC_TRIM (DENV4-493H_S3)    | 11 of 11 ✔",
    "[0d/62aaf3] KRAKEN2 (DENV4-322H_S5)        | 2 of 11",
    "[b1/791ffe] KREPORT2KRONA (DENV4-322H_S5)  | 2 of 2",
  ].join(String.fromCharCode(10));
  const processLine = /^\[[^\]]+\]\s+([A-Z][A-Z0-9_:.…]*)(?:\s+\(([^)]+)\))?\s+(?:\[[^\]]+\]\s*)?\|?\s*(\d+)\s+of\s+(\d+)/gm;
  const counts = new Map(Array.from(log.matchAll(processLine), match => [
    match[1].includes("ALIDATION") ? "SAMPLE_VALIDATION" : match[1],
    { done: Number(match[3]), total: Number(match[4]) },
  ]));
  assert.deepEqual(counts.get("SAMPLE_VALIDATION"), { done: 11, total: 11 });
  assert.deepEqual(counts.get("FASTQC_RAW"), { done: 11, total: 11 });
  assert.deepEqual(counts.get("KRAKEN2"), { done: 2, total: 11 });
  assert.equal(counts.size, 6);
});
test("expands abbreviated Nextflow process names before calculating stages", async () => {
  const page = await readFile(new URL("../app/page.tsx", import.meta.url), "utf8");
  assert.ok(page.includes("process.startsWith(prefix) && process.endsWith(suffix)"));
  const known = ["SAMPLE_VALIDATION", "FASTQC_RAW", "FASTP", "FASTQC_TRIM", "KRAKEN2", "KREPORT2KRONA"];
  const normalize = name => {
    const [prefix, suffix] = name.toUpperCase().split(/…|\.\.\./);
    const matches = known.filter(process => process.startsWith(prefix) && process.endsWith(suffix));
    return matches.length === 1 ? matches[0] : name;
  };
  assert.equal(normalize("SAM…ON"), "SAMPLE_VALIDATION");
  assert.equal(normalize("FAS…RAW"), "FASTQC_RAW");
  assert.equal(normalize("FAS…IM"), "FASTQC_TRIM");
  assert.equal(normalize("KRA…N2"), "KRAKEN2");
  assert.equal(normalize("KRE…ONA"), "KREPORT2KRONA");
});
