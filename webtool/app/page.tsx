"use client";

import { useEffect, useMemo, useRef, useState } from "react";

type View = "overview" | "new" | "runs" | "samples" | "results";
type InputMode = "single" | "mixed";
type PickerTarget = "fastq_dir" | "reference" | "primer_bed" | "gff" | "samplesheet" | "samplesheet_parent" | "samplesheet_output" | "metadata" | "outdir" | "kraken_db";
type RunFilter = "all" | "running" | "completed" | "error";
type RunStage = { label: string; progress: number };
type SampleRecord = {
  run_id: string; run_name: string; sample: string; virus: string; qc: string;
  reads: string; depth: string; coverage: string; lineage_genotype: string; status: string;
};
type Artifact = {
  key: string; title: string; available: boolean; count: number; files: string[];
  url: string; opens_inline: boolean;
};
type SamplesheetResult = {
  path: string; samples: number; viruses: Record<string, number>; warnings: string[]; catalog: string;
};
type Run = {
  id: string; name: string; virus: string; samples: number; progress: number;
  status: string; started: string; createdAt: string; currentProcess: string; stages: RunStage[];
  log: string; sampleIds: string[]; sampleRows: SampleRecord[]; outdir: string; queuePosition: number | null;
};
type ApiJob = {
  id: string; name: string; virus: string; status: string; created_at: string;
  started_at?: string | null; queue_position?: number | null;
  nextclade?: boolean; blast?: boolean; kraken?: boolean; deplete?: boolean;
  metadata?: string; outdir?: string; nextclade_dataset?: string;
};

const viruses = ["SARS-CoV-2", "Dengue", "CHIKV", "VSR", "Oropouche", "Outro"];
const nextcladeDatasetAliases = ["sars-cov-2", "dengue", "denv1", "denv2", "denv3", "denv4", "chikv", "rsv-a", "rsv-b", "zika", "yellow-fever", "oropouche"];
const nextcladeDatasetDefaults: Record<string, string> = {
  "SARS-CoV-2": "sars-cov-2",
  "Dengue": "dengue",
  "CHIKV": "chikv",
  "VSR": "",
  "Oropouche": "oropouche",
  "Outro": "",
};
const stageDefinitions = [
  { label: "Validação", processes: ["SAMPLE_VALIDATION"] },
  { label: "Qualidade", processes: ["FASTQC_RAW", "FASTP", "FASTQC_TRIM"] },
  { label: "Taxonomia", processes: ["KRAKEN2", "TAXONOMY_SUMMARY", "KREPORT2KRONA", "KRONA", "KRONA_VALIDATION"], enabled: (job: ApiJob) => Boolean(job.kraken) },
  { label: "Alinhamento", processes: ["HOST_DEPLETE", "ALIGN:BWA_MEM", "IVAR_TRIM", "SAMTOOLS_STATS"], optional: (name: string, job: ApiJob) => name === "HOST_DEPLETE" && !job.deplete },
  { label: "Consenso", processes: ["IVAR_VARIANTS", "ANNOTATE_AA", "MIXED_SITES", "IVAR_CONSENSUS", "CONSENSUS_QC", "READ_STATS"] },
  { label: "Classificação", processes: ["NEXTCLADE_DATASET_GET", "NEXTCLADE_RUN", "NEXTCLADE_SUMMARY", "BLAST_DB_PREP", "BLASTN_ID", "BLAST_SUMMARY"], optional: (name: string, job: ApiJob) => name.startsWith("NEXTCLADE") ? !job.nextclade : name.startsWith("BLAST") && !job.blast },
  { label: "Relatórios", processes: ["CAT_CONSENSUS", "MULTIQC", "METADATA_XLSX", "GISAID_SUBMISSION", "DASHBOARD"], optional: (name: string, job: ApiJob) => ["METADATA_XLSX", "GISAID_SUBMISSION"].includes(name) && !job.metadata },
] as const;

const knownProcessNames = Array.from(new Set(stageDefinitions.flatMap(definition => definition.processes)));

function normalizeProcessName(name: string) {
  const raw = name.toUpperCase();
  const abbreviated = raw.split(/…|\.\.\./);
  if (abbreviated.length === 2) {
    const [prefix, suffix] = abbreviated;
    const candidates = knownProcessNames.filter(process => process.startsWith(prefix) && process.endsWith(suffix));
    if (candidates.length === 1) return candidates[0];
  }
  const normalized = raw.replace(/…|\.\.\./g, "");  if (normalized.includes("ALIDATION")) return "SAMPLE_VALIDATION";
  if (normalized.startsWith("SAM") && normalized.endsWith("OLS_STATS")) return "SAMTOOLS_STATS";
  if (normalized.startsWith("IVA") && normalized.endsWith("CONSENSUS")) return "IVAR_CONSENSUS";
  return normalized;
}

function runFromJob(job: ApiJob, rawLog: string, sampleRows: SampleRecord[] = []): Run {
  const cleanLog = rawLog.replace(/\x1B\[[0-?]*[ -/]*[@-~]/g, "").replace(/\r/g, "\n");
  const marker = cleanLog.lastIndexOf("executor >");
  const snapshot = marker >= 0 ? cleanLog.slice(marker) : cleanLog;
  const counts = new Map<string, { done: number; total: number }>();
  const sampleIds = new Set<string>();
  const processLine = /^\[[^\]]+\]\s+([A-Z][A-Z0-9_:.…]*)(?:\s+\(([^)]+)\))?\s+(?:\[[^\]]+\]\s*)?\|?\s*(\d+)\s+of\s+(\d+)/gm;
  for (const match of snapshot.matchAll(processLine)) {
    const process = normalizeProcessName(match[1]);
    counts.set(process, { done: Number(match[3]), total: Number(match[4]) });
    if (match[2] && !process.includes("DATASET") && !process.includes("SUMMARY") && !process.includes("DB_PREP")) sampleIds.add(match[2]);
  }
  const isComplete = job.status === "Concluída";
  const parsedStages = stageDefinitions.map(definition => {
    if (definition.enabled && !definition.enabled(job)) return { label: definition.label, progress: 100 };
    const expected = definition.processes.filter(name => !(definition.optional?.(name, job)));
    if (!expected.length) return { label: definition.label, progress: 100 };
    const progress = expected.reduce((sum, name) => {
      const count = counts.get(name);
      return sum + (count?.total ? Math.min(100, count.done / count.total * 100) : 0);
    }, 0) / expected.length;
    return { label: definition.label, progress: Math.round(progress) };
  });
  const stages = isComplete ? parsedStages.map(stage => ({ ...stage, progress: 100 })) : parsedStages;
  const progress = isComplete ? 100 : Math.round(stages.reduce((sum, stage) => sum + stage.progress, 0) / stages.length);
  const currentStage = stages.find(stage => stage.progress < 100);
  const currentProcess = job.status === "Na fila"
    ? `Aguardando na fila${job.queue_position ? ` · posição ${job.queue_position}` : ""}`
    : isComplete ? "Execução concluída" : Array.from(counts.entries()).find(([, count]) => count.done < count.total)?.[0]
      ?? currentStage?.label ?? job.status;
  const validation = counts.get("SAMPLE_VALIDATION");
  const samples = validation?.total ?? (sampleRows.length || Math.max(0, ...Array.from(counts.values(), value => value.total)));
  const terminalLines = snapshot.split("\n").filter(Boolean).slice(-55).join("\n");
  return {
    id: job.id, name: job.name, virus: job.virus, samples, progress,
    status: job.status, createdAt: job.created_at,
    started: job.status === "Na fila" ? "Aguardando" : new Date(job.started_at ?? job.created_at).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" }),
    currentProcess, stages, log: terminalLines,
    sampleIds: sampleRows.length ? sampleRows.map(row => row.sample) : Array.from(sampleIds).sort(),
    sampleRows, outdir: job.outdir ?? "", queuePosition: job.queue_position ?? null,
  };
}

function emptyRun(job: ApiJob): Run {
  return runFromJob(job, "");
}

function Toggle({ checked, onChange, label, description }: { checked: boolean; onChange: () => void; label: string; description: string }) {
  return <button type="button" className={`toggle-row ${checked ? "is-on" : ""}`} onClick={onChange} aria-pressed={checked}>
    <span className="toggle-copy"><strong>{label}</strong><small>{description}</small></span><span className="toggle-control"><span /></span>
  </button>;
}
function Status({ value }: { value: string }) {
  const slug = value.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase().replace(" ", "-");
  return <span className={`status status-${slug}`}>{value}</span>;
}
function VirusBadge({ virus }: { virus: string }) {
  return <span className="virus-badge">{virus === "SARS-CoV-2" ? "SC2" : virus.slice(0, 4).toUpperCase()}</span>;
}

export default function Home() {
  const [view, setView] = useState<View>("new");
  const [virus, setVirus] = useState("Dengue");
  const [profile, setProfile] = useState("singularity");
  const profileInitialized = useRef(false);
  const [inputMode, setInputMode] = useState<InputMode>("single");
  const [rawDataDir, setRawDataDir] = useState("");
  const [reference, setReference] = useState("");
  const [primerBed, setPrimerBed] = useState("");
  const [gff, setGff] = useState("");
  const [samplesheet, setSamplesheet] = useState("");
  const [samplesheetParent, setSamplesheetParent] = useState("");
  const [samplesheetOutput, setSamplesheetOutput] = useState("");
  const [samplesheetResult, setSamplesheetResult] = useState<SamplesheetResult | null>(null);
  const [metadata, setMetadata] = useState("");
  const [outdir, setOutdir] = useState("");
  const [krakenDb, setKrakenDb] = useState("");
  const [runName, setRunName] = useState("");
  const [minCov, setMinCov] = useState(20), [minFreq, setMinFreq] = useState(0.75);
  const [minQual, setMinQual] = useState(20), [mapQual, setMapQual] = useState(20);
  const [cpus, setCpus] = useState(8), [memory, setMemory] = useState(16);
  const [nextclade, setNextclade] = useState(true), [blast, setBlast] = useState(false);
  const [nextcladeDataset, setNextcladeDataset] = useState(nextcladeDatasetDefaults.Dengue);
  const [kraken, setKraken] = useState(false), [deplete, setDeplete] = useState(false);
  const [advanced, setAdvanced] = useState(false), [notice, setNotice] = useState("");
  const [runs, setRuns] = useState<Run[]>([]);
  const [selectedRunId, setSelectedRunId] = useState("");
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [backendOnline, setBackendOnline] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [creatingSamplesheet, setCreatingSamplesheet] = useState(false);
  const [pickingPath, setPickingPath] = useState<PickerTarget | "">("");

  const command = useMemo(() => [
    "nextflow run main.nf", `-profile ${profile}`,
    `--input ${inputMode === "single" ? rawDataDir || "<fastq_folder>" : samplesheet || "<samplesheet.csv>"}`,
    inputMode === "single" ? `--reference ${reference || "<reference.fasta>"}` : "",
    inputMode === "single" ? `--virus ${virus}` : "",
    inputMode === "single" && primerBed ? `--primer_bed ${primerBed}` : "",
    inputMode === "single" && gff ? `--gff ${gff}` : "",
    `--outdir ${outdir || "<results>"}`, `--run_name ${runName || "<run_name>"}`, `--min_cov ${minCov}`,
    `--min_freq ${minFreq}`, `--min_qual ${minQual}`, `--min_map_qual ${mapQual}`,
    `--max_cpus ${cpus}`, `--max_memory ${memory}.GB`, `--nextclade ${nextclade}`,
    inputMode === "single" && nextclade && nextcladeDataset ? `--nextclade_dataset ${nextcladeDataset}` : "",
    `--blast_id ${blast}`, metadata ? `--metadata ${metadata}` : "", kraken && krakenDb ? `--kraken2_db ${krakenDb}` : "",
    deplete && kraken ? "--deplete_host true" : "", "-resume"
  ].filter(Boolean).join(" \\\n  "), [profile, inputMode, rawDataDir, reference, primerBed, gff, samplesheet, virus, outdir, runName, minCov, minFreq, minQual, mapQual, cpus, memory, nextclade, nextcladeDataset, blast, metadata, kraken, krakenDb, deplete]);

  useEffect(() => {
    let active = true;
    async function syncLocalService() {
      try {
        const [healthResponse, jobsResponse] = await Promise.all([
          fetch("http://localhost:8787/api/health", { cache: "no-store" }),
          fetch("http://localhost:8787/api/jobs", { cache: "no-store" }),
        ]);
        if (!healthResponse.ok || !jobsResponse.ok) throw new Error();
        const health = await healthResponse.json() as { default_profile?: string };
        const jobs = await jobsResponse.json() as ApiJob[];
        const enrichedRuns = await Promise.all(jobs.map(async job => {
          try {
            const [logResponse, samplesResponse] = await Promise.all([
              fetch(`http://localhost:8787/api/jobs/${encodeURIComponent(job.id)}/log`, { cache: "no-store" }),
              fetch(`http://localhost:8787/api/jobs/${encodeURIComponent(job.id)}/samples`, { cache: "no-store" }),
            ]);
            const payload = logResponse.ok ? await logResponse.json() as { log?: string } : {};
            const samplePayload = samplesResponse.ok ? await samplesResponse.json() as { samples?: SampleRecord[] } : {};
            return runFromJob(job, payload.log ?? "", samplePayload.samples ?? []);
          } catch {
            return emptyRun(job);
          }
        }));
        if (!active) return;
        setBackendOnline(true);
        if (!profileInitialized.current && ["conda", "singularity", "docker"].includes(health.default_profile ?? "")) {
          setProfile(health.default_profile!);
          profileInitialized.current = true;
        }
        setRuns(enrichedRuns);
        setLastUpdated(new Date());
        setSelectedRunId(current => current && enrichedRuns.some(run => run.id === current)
          ? current
          : enrichedRuns.find(run => ["Executando", "Na fila"].includes(run.status))?.id ?? enrichedRuns[0]?.id ?? "");
      } catch {
        if (active) setBackendOnline(false);
      }
    }
    syncLocalService();
    const timer = window.setInterval(syncLocalService, 3000);
    return () => { active = false; window.clearInterval(timer); };
  }, []);

  async function selectLocalPath(picker: PickerTarget, current: string, setValue: (value: string) => void) {
    setPickingPath(picker);
    setNotice("");
    try {
      const response = await fetch("http://localhost:8787/api/picker", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ picker, current }),
      });
      const result = await response.json() as { cancelled?: boolean; path?: string; error?: string };
      if (!response.ok) throw new Error(result.error || "Não foi possível abrir o seletor");
      if (!result.cancelled && result.path) setValue(result.path);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Não foi possível abrir o seletor nativo");
    } finally {
      setPickingPath("");
    }
  }
  async function createSamplesheet() {
    if (!samplesheetParent.trim() || !samplesheetOutput.trim()) {
      setNotice("Selecione a pasta-pai dos dados brutos e o arquivo CSV de destino.");
      return;
    }
    setCreatingSamplesheet(true);
    setNotice("");
    setSamplesheetResult(null);
    try {
      const response = await fetch("http://localhost:8787/api/samplesheet", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ parent: samplesheetParent, output: samplesheetOutput }),
      });
      const result = await response.json() as SamplesheetResult & { error?: string };
      if (!response.ok) throw new Error(result.error || "Não foi possível criar a samplesheet");
      setSamplesheet(result.path);
      setSamplesheetOutput(result.path);
      setSamplesheetResult(result);
      const warningText = result.warnings.length ? ` Há ${result.warnings.length} aviso(s) para revisar.` : "";
      setNotice(`Samplesheet criada com ${result.samples} amostra(s) e selecionada para a análise Mixed.${warningText}`);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Não foi possível criar a samplesheet");
    } finally {
      setCreatingSamplesheet(false);
    }
  }
  async function startAnalysis() {
    setSubmitting(true);
    setNotice("");
    try {
      const response = await fetch("http://localhost:8787/api/jobs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ run_name: runName, virus, profile, input_mode: inputMode,
          raw_data_dir: rawDataDir, reference, primer_bed: primerBed, gff, samplesheet, metadata, outdir,
          kraken_db: krakenDb, min_cov: minCov, min_freq: minFreq, min_qual: minQual,
          min_map_qual: mapQual, max_cpus: cpus, max_memory: memory,
          nextclade, nextclade_dataset: inputMode === "single" ? nextcladeDataset : "", blast, kraken, deplete }),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || "Não foi possível iniciar a análise");
      const run = emptyRun(result as ApiJob);
      setRuns(current => [run, ...current.filter(item => item.id !== run.id)]);
      setSelectedRunId(run.id);
      setNotice(result.status === "Na fila"
        ? `Execução ${result.id} adicionada à fila${result.queue_position ? ` na posição ${result.queue_position}` : ""}.`
        : `Execução ${result.id} iniciada pelo serviço local.`);
      setView("runs");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Serviço local indisponível");
    } finally {
      setSubmitting(false);
    }
  }

  async function cancelAnalysis(runId: string) {
    const response = await fetch("http://localhost:8787/api/jobs/" + encodeURIComponent(runId) + "/cancel", { method: "POST" });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "Não foi possível parar a análise");
    setRuns(current => current.map(run => run.id === runId
      ? { ...run, status: "Cancelada", currentProcess: "Execução cancelada" }
      : run));
    setNotice("Execução " + runId + " cancelada.");
  }
  async function deleteAnalysis(runId: string) {
    const response = await fetch("http://localhost:8787/api/jobs/" + encodeURIComponent(runId), { method: "DELETE" });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "Não foi possível excluir a execução");
    setRuns(current => current.filter(run => run.id !== runId));
    setSelectedRunId(current => current === runId ? "" : current);
    setNotice("Execução " + runId + " excluída do histórico. Os arquivos de resultados foram preservados.");
  }
  const nav: { id: View; label: string; icon: string }[] = [
    { id: "overview", label: "Visão geral", icon: "⌂" }, { id: "new", label: "Nova análise", icon: "+" },
    { id: "runs", label: "Execuções", icon: "↻" }, { id: "samples", label: "Amostras", icon: "▦" }, { id: "results", label: "Resultados", icon: "↗" },
  ];
  const titles: Record<View, [string, string]> = {
    overview: ["Visão geral", "Acompanhe a operação do laboratório em um só lugar."], new: ["Nova análise", "Configure dados, métodos e recursos antes de executar."],
    runs: ["Execuções", "Monitore o progresso e retome análises interrompidas."], samples: ["Amostras", "Explore as amostras processadas e seus indicadores."],
    results: ["Resultados", "Acesse dashboards, consensos e relatórios finais."],
  };

  return <div className="app-shell">
    <aside className="sidebar">
      <div className="brand"><div className="brand-mark" aria-hidden="true"><i/><i/><i/><i/></div><div><strong>MK Viral</strong><span>Assembly</span></div></div>
      <div className="workspace-label">PLATAFORMA LOCAL</div>
      <nav aria-label="Navegação principal">{nav.map(item => <button key={item.id} className={view === item.id ? "active" : ""} onClick={() => setView(item.id)}><span className="nav-icon">{item.icon}</span>{item.label}{item.id === "runs" && runs.filter(run => ["Executando", "Na fila"].includes(run.status)).length > 0 && <em>{runs.filter(run => ["Executando", "Na fila"].includes(run.status)).length}</em>}</button>)}</nav>
      <div className="sidebar-bottom"><button><span className="nav-icon">?</span>Documentação</button><button><span className="nav-icon">⚙</span>Configurações</button><div className={`local-card ${backendOnline ? "" : "offline"}`}><span className="pulse-dot"/><div><strong>Ambiente local</strong><small>{backendOnline ? "Serviço local · operacional" : "API local · desconectada"}</small></div></div><div className="version">MK-Viral-Assembly <span>v1.2.4</span></div></div>
    </aside>
    <main>
      <header className="topbar"><div><p>MK-VIRAL-ASSEMBLY</p><h1>{titles[view][0]}</h1><span>{titles[view][1]}</span></div><div className="machine"><b>MK</b><span><strong>Usuário local</strong><small>Este computador</small></span></div></header>
      <div className="content">
        {notice && <div className="notice"><span>✓</span>{notice}<button onClick={() => setNotice("")}>×</button></div>}
        {view === "overview" && <Overview runs={runs} setView={setView} setSelectedRunId={setSelectedRunId}/>}
        {view === "new" && <section className="analysis-layout">
          <div className="analysis-main">
            <div className="stepper"><span className="done"><b>1</b>Dados</span><i/><span className="current"><b>2</b>Parâmetros</span><i/><span><b>3</b>Revisar e executar</span></div>
            <article className="panel form-panel"><PanelHeading number="01" title="Dados da análise" text="Selecione pastas e arquivos diretamente neste computador." aside="Os dados não saem do computador"/>
              <div className="form-grid">
                <label className="field full"><span>Nome da execução</span><input value={runName} onChange={e => setRunName(e.target.value)}/></label>
                <div className="input-mode-picker full" role="group" aria-label="Modo de entrada"><button type="button" className={inputMode === "single" ? "selected" : ""} aria-pressed={inputMode === "single"} onClick={() => setInputMode("single")}><span>01</span><div><strong>Single Analysis</strong><small>Um vírus e uma referência por execução</small></div></button><button type="button" className={inputMode === "mixed" ? "selected" : ""} aria-pressed={inputMode === "mixed"} onClick={() => setInputMode("mixed")}><span>02</span><div><strong>Mixed Virus Analysis</strong><small>Vírus e referências definidos por amostra</small></div></button></div>
                {inputMode === "single" ? <>
                  <PathField label="Pasta dos dados brutos" required value={rawDataDir} setValue={setRawDataDir} picker="fastq_dir" picking={pickingPath} onPick={selectLocalPath} placeholder="Selecione a pasta com os FASTQ.GZ" help="Pasta com pares R1/R2 em FASTQ.GZ ou FQ.GZ." full/>
                  <PathField label="Referência FASTA global" required value={reference} setValue={setReference} picker="reference" picking={pickingPath} onPick={selectLocalPath} placeholder="Selecione a referência .fasta, .fa ou .fna" help="Usada para todas as amostras desta execução single-virus." full/>
                  <PathField label="Primer BED" value={primerBed} setValue={setPrimerBed} picker="primer_bed" picking={pickingPath} onPick={selectLocalPath} placeholder="Selecione o arquivo .bed" help="Opcional: remove regiões de primers em dados de amplicons."/>
                  <PathField label="Anotação GFF3" value={gff} setValue={setGff} picker="gff" picking={pickingPath} onPick={selectLocalPath} placeholder="Selecione o arquivo .gff ou .gff3" help="Opcional: adiciona a anotação de alterações de aminoácidos."/>
                </> : <>
                  <PathField label="Samplesheet CSV" required value={samplesheet} setValue={setSamplesheet} picker="samplesheet" picking={pickingPath} onPick={selectLocalPath} placeholder="Selecione uma samplesheet existente ou crie uma abaixo" help="CSV com amostras, reads, vírus e referências por amostra." full/>
                  <section className="samplesheet-builder full" aria-labelledby="samplesheet-builder-title">
                    <div className="samplesheet-builder-head">
                      <span>CSV</span>
                      <div><strong id="samplesheet-builder-title">Criar samplesheet automaticamente</strong><small>A pasta-pai deve conter uma subpasta para cada vírus, com os FASTQ pareados.</small></div>
                    </div>
                    <div className="form-grid samplesheet-builder-fields">
                      <PathField label="Pasta-pai dos dados brutos" required value={samplesheetParent} setValue={setSamplesheetParent} picker="samplesheet_parent" picking={pickingPath} onPick={selectLocalPath} placeholder="Selecione a pasta que contém as subpastas dos vírus" help="Ex.: run17/chikv, run17/denv2 e run17/sarscov2."/>
                      <PathField label="Salvar samplesheet em" required value={samplesheetOutput} setValue={setSamplesheetOutput} picker="samplesheet_output" picking={pickingPath} onPick={selectLocalPath} placeholder="Escolha a pasta e o nome do arquivo .csv" help="A janela Salvar como usa o caminho local selecionado."/>
                    </div>
                    <div className="samplesheet-builder-actions">
                      <div className="catalog-note"><b>Catálogo automático</b><span>assets/virus_catalog.tsv do MK-Viral-Assembly</span></div>
                      <button type="button" className="create-samplesheet" onClick={createSamplesheet} disabled={creatingSamplesheet || !backendOnline || !samplesheetParent.trim() || !samplesheetOutput.trim()}>{creatingSamplesheet ? "Criando..." : "Gerar e usar samplesheet"}</button>
                    </div>
                    {samplesheetResult && <div className="samplesheet-result">
                      <strong>{samplesheetResult.samples} amostra(s) encontrada(s)</strong>
                      <span>{Object.entries(samplesheetResult.viruses).map(([name, count]) => `${name}: ${count}`).join(" · ") || "Nenhum vírus identificado"}</span>
                      {samplesheetResult.warnings.length > 0 && <ul>{samplesheetResult.warnings.map((warning, index) => <li key={index}>{warning}</li>)}</ul>}
                    </div>}
                  </section>
                </>}
                <div className="metadata-template-block full">
                  <PathField label="Metadados" value={metadata} setValue={setMetadata} picker="metadata" picking={pickingPath} onPick={selectLocalPath} placeholder="Selecione os metadados em XLSX, CSV ou TSV" full/>
                  <div className="metadata-template-links"><span>Comece pelo modelo:</span><a href="http://localhost:8787/api/metadata-template?format=xlsx">XLSX</a><a href="http://localhost:8787/api/metadata-template?format=csv">CSV</a><a href="http://localhost:8787/api/metadata-template?format=tsv">TSV</a><small>Preencha uma linha por amostra sem alterar os títulos das colunas.</small></div>
                </div>
                <PathField label="Diretório de resultados" value={outdir} setValue={setOutdir} picker="outdir" picking={pickingPath} onPick={selectLocalPath} placeholder="Selecione onde salvar os resultados" full/>
              </div>
            </article>            <article className="panel form-panel"><PanelHeading number="02" title="Organismo e ambiente" text={inputMode === "single" ? "Escolha um preset e o mecanismo de execução." : "Os vírus e as referências serão lidos do samplesheet."}/>
              {inputMode === "single" ? <div className="virus-options">{viruses.map(v => <button type="button" key={v} className={virus === v ? "selected" : ""} onClick={() => { setVirus(v); setNextcladeDataset(nextcladeDatasetDefaults[v] ?? ""); }}><VirusBadge virus={v}/>{v}</button>)}</div> : <div className="mixed-mode-note"><span>CSV</span><div><strong>Configuração por amostra</strong><small>As colunas virus e reference do samplesheet controlam cada amostra.</small></div></div>}
              <div className="form-grid compact-grid"><label className="field"><span>Perfil de execução</span><select value={profile} onChange={e => setProfile(e.target.value)}><option value="conda">Conda — recomendado no Windows</option><option value="singularity">Singularity / Apptainer</option><option value="docker">Docker</option></select></label><div className={`environment-ok ${backendOnline ? "" : "unavailable"}`}><span>{backendOnline ? "✓" : "!"}</span><div><strong>{backendOnline ? "Ambiente disponível" : "Serviço local desligado"}</strong><small>{backendOnline ? "WebTool e Nextflow detectados" : "Abra o aplicativo MK-Viral-Assembly"}</small></div></div></div>
            </article>
            <article className="panel form-panel"><PanelHeading number="03" title="Etapas opcionais" text="Ative somente as análises necessárias para este lote."/>
              <div className="toggle-grid"><Toggle checked={nextclade} onChange={() => setNextclade(!nextclade)} label="Nextclade" description="Linhagem, genótipo e controle de qualidade"/><Toggle checked={blast} onChange={() => setBlast(!blast)} label="Identificação por BLAST" description="Confirmação contra RefSeq Viral local"/><Toggle checked={kraken} onChange={() => setKraken(!kraken)} label="Triagem Kraken2" description="Composição taxonômica das leituras"/><Toggle checked={deplete} onChange={() => setDeplete(!deplete)} label="Depleção do hospedeiro" description="Remove leituras humanas antes do alinhamento"/></div>
              {inputMode === "single" && nextclade && <label className="field database-field"><span>Dataset Nextclade <em>obrigatório no modo Single</em></span><input list="nextclade-dataset-aliases" value={nextcladeDataset} placeholder="Ex.: denv4 ou nextstrain/dengue/all" onChange={event => setNextcladeDataset(event.target.value)} required/><datalist id="nextclade-dataset-aliases">{nextcladeDatasetAliases.map(alias => <option key={alias} value={alias}/>)}</datalist><small>Informe um alias do pipeline ou o caminho completo no catálogo Nextclade. Para VSR, escolha rsv-a ou rsv-b.</small></label>}
              {kraken && <PathField label="Banco Kraken2" value={krakenDb} setValue={setKrakenDb} picker="kraken_db" picking={pickingPath} onPick={selectLocalPath} placeholder="Selecione o diretório do banco Kraken2" className="database-field"/>}
            </article>
            <article className="panel form-panel advanced-panel"><button className="advanced-trigger" type="button" onClick={() => setAdvanced(!advanced)}><span><b>04</b><span><strong>Parâmetros avançados</strong><small>Qualidade, consenso e recursos computacionais</small></span></span><em>{advanced ? "−" : "+"}</em></button>
              {advanced && <div className="advanced-content"><div className="parameter-grid"><NumberField label="Cobertura mínima" value={minCov} setValue={setMinCov} help="Profundidade mínima para chamar uma base."/><NumberField label="Frequência mínima" value={minFreq} setValue={setMinFreq} step="0.05" help="Frequência mínima do alelo alternativo."/><NumberField label="Qualidade da base" value={minQual} setValue={setMinQual}/><NumberField label="Qualidade de mapeamento" value={mapQual} setValue={setMapQual}/></div><div className="resource-grid"><Range label="CPUs" value={cpus} setValue={setCpus} min={2} max={16} suffix=""/><Range label="Memória" value={memory} setValue={setMemory} min={8} max={60} suffix=" GB"/></div></div>}
            </article>
          </div>
          <aside className="run-summary"><div className="summary-head"><span>RESUMO DA EXECUÇÃO</span><b>Pronta</b></div><div className="summary-virus"><VirusBadge virus={inputMode === "single" ? virus : "Mixed viruses"}/><div><strong>{inputMode === "single" ? virus : "Mixed viruses"}</strong><small>{profile} · Illumina paired-end</small></div></div><dl><Summary label="Execução" value={runName || "Sem nome"}/><Summary label="Entrada" value={inputMode === "single" ? "Single · pasta FASTQ" : "Mixed · samplesheet CSV"}/>{inputMode === "single" && primerBed && <Summary label="Primers" value="BED ativado"/>}{inputMode === "single" && gff && <Summary label="Anotação" value="GFF3 ativado"/>}<Summary label="Recursos" value={`${cpus} CPUs · ${memory} GB`}/><Summary label="Classificação" value={nextclade ? (inputMode === "single" ? "Nextclade · " + (nextcladeDataset || "dataset pendente") : "Nextclade · por samplesheet") : "Desativada"}/><Summary label="Identificação" value={blast ? "BLAST RefSeq" : "Desativada"}/><Summary label="Taxonomia" value={kraken ? "Kraken2" : "Desativada"}/></dl><div className="command-box"><div><span>COMANDO NEXTFLOW</span><button type="button" onClick={() => navigator.clipboard?.writeText(command)}>Copiar</button></div><pre>{command}</pre></div><button className="launch" onClick={startAnalysis} disabled={submitting || !backendOnline || (inputMode === "single" && nextclade && !nextcladeDataset.trim())}><span>▶</span>{submitting ? "Iniciando..." : !backendOnline ? "Serviço local indisponível" : inputMode === "single" && nextclade && !nextcladeDataset.trim() ? "Informe o dataset Nextclade" : "Iniciar análise"}</button><p className="launch-note">A execução continuará enquanto o computador e o aplicativo permanecerem ligados.</p></aside>
        </section>}
        {view === "runs" && <RunsPage runs={runs} setView={setView} selectedRunId={selectedRunId} setSelectedRunId={setSelectedRunId} lastUpdated={lastUpdated} onCancel={cancelAnalysis} onDelete={deleteAnalysis}/>} {view === "samples" && <SamplesPage runs={runs} lastUpdated={lastUpdated}/>} {view === "results" && <ResultsPage runs={runs} selectedRunId={selectedRunId} setSelectedRunId={setSelectedRunId}/>}
      </div>
    </main>
  </div>;
}

function PathField({ label, required = false, value, setValue, picker, picking, onPick, placeholder = "", help, full = false, className = "" }: {
  label: string; required?: boolean; value: string; setValue: (value: string) => void; picker: PickerTarget;
  picking: PickerTarget | ""; onPick: (picker: PickerTarget, current: string, setValue: (value: string) => void) => Promise<void>;
  placeholder?: string; help?: string; full?: boolean; className?: string;
}) {
  return <label className={`field ${full ? "full " : ""}${className}`.trim()}>
    <span>{label} <em>{required ? "obrigatório" : "opcional"}</em></span>
    <div className="path-input"><input value={value} placeholder={placeholder} onChange={event => setValue(event.target.value)}/><button type="button" disabled={Boolean(picking)} onClick={() => onPick(picker, value, setValue)}>{picking === picker ? "Abrindo..." : "Selecionar..."}</button></div>
    {help && <small>{help}</small>}
  </label>;
}
function PanelHeading({ number, title, text, aside }: { number: string; title: string; text: string; aside?: string }) { return <div className="panel-heading"><div><span className="section-number">{number}</span><div><h2>{title}</h2><p>{text}</p></div></div>{aside && <span className="local-only">{aside}</span>}</div>; }
function NumberField({ label, value, setValue, step, help }: { label: string; value: number; setValue: (n:number)=>void; step?: string; help?: string }) { return <label className="field"><span>{label}</span><input type="number" step={step} value={value} onChange={e => setValue(Number(e.target.value))}/>{help && <small>{help}</small>}</label>; }
function Range({ label, value, setValue, min, max, suffix }: { label:string; value:number; setValue:(n:number)=>void; min:number; max:number; suffix:string }) { return <label><span><strong>{label}</strong><em>{value}{suffix}</em></span><input type="range" min={min} max={max} value={value} onChange={e => setValue(Number(e.target.value))}/></label>; }
function Summary({ label, value }: { label:string; value:string }) { return <div><dt>{label}</dt><dd>{value}</dd></div>; }

function Overview({ runs, setView, setSelectedRunId }: { runs: Run[]; setView:(v:View)=>void; setSelectedRunId:(id:string)=>void }) {
  const now = new Date();
  const thisMonth = runs.filter(run => {
    const date = new Date(run.createdAt);
    return date.getFullYear() === now.getFullYear() && date.getMonth() === now.getMonth();
  }).length;
  const sampleCount = runs.reduce((sum, run) => sum + run.samples, 0);
  const running = runs.filter(run => ["Executando", "Na fila"].includes(run.status));
  const errors = runs.filter(run => ["Com erro", "Interrompida", "Cancelada"].includes(run.status));
  return <section>
    <div className="metric-grid">
      <article><span>EXECUÇÕES ESTE MÊS</span><strong>{thisMonth}</strong><small>lidas do histórico local</small></article>
      <article><span>AMOSTRAS IDENTIFICADAS</span><strong>{sampleCount}</strong><small>total informado pelos logs</small></article>
      <article><span>EM PROCESSAMENTO</span><strong>{running.length}</strong><small>{running[0]?.name ?? "nenhuma execução ativa"}</small></article>
      <article><span>COM ERRO</span><strong>{errors.length}</strong><small>{errors[0]?.name ?? "nenhuma falha registrada"}</small></article>
    </div>
    <div className="panel welcome-panel"><div><span className="eyebrow">PIPELINE LOCAL, CONTROLE TOTAL</span><h2>Da leitura bruta ao consenso, com cada decisão visível.</h2><p>Configure parâmetros, acompanhe cada etapa e mantenha seus dados inteiramente na sua máquina.</p><button className="primary" onClick={() => setView("new")}>Criar nova análise <span>→</span></button></div><div className="helix-art" aria-hidden="true">{Array.from({length:9}).map((_,i)=><i key={i}/>)}</div></div>
    <RunsTable runs={runs.slice(0,3)} onOpen={() => setView("runs")} onSelect={id => { setSelectedRunId(id); setView("runs"); }}/>
  </section>;
}

function RunsTable({ runs, onOpen, onSelect, selectedId, onDelete, deletingId }: { runs: Run[]; onOpen?:()=>void; onSelect?:(id:string)=>void; selectedId?:string; onDelete?:(run:Run)=>void; deletingId?:string }) {
  const showActions = Boolean(onDelete);
  return <article className="panel data-panel">
    <div className="table-title"><div><h2>Execuções recentes</h2><p>Atividade real registrada pelo serviço local.</p></div>{onOpen && <button onClick={onOpen}>Ver todas →</button>}</div>
    <div className="table-wrap"><table><thead><tr><th>Execução</th><th>Vírus</th><th>Amostras</th><th>Progresso estimado</th><th>Status</th><th>Início</th>{showActions && <th className="actions-column">Ações</th>}</tr></thead>
      <tbody>{runs.length ? runs.map(run => {
        const active = ["Executando", "Na fila"].includes(run.status);
        return <tr key={run.id} className={(onSelect ? "selectable " : "") + (selectedId === run.id ? "selected-run" : "")} onClick={() => onSelect?.(run.id)} onKeyDown={event => { if (onSelect && (event.key === "Enter" || event.key === " ")) onSelect(run.id); }} tabIndex={onSelect ? 0 : undefined}>
          <td><strong>{run.name}</strong><small>{run.id}</small></td><td>{run.virus}</td><td>{run.samples || "—"}</td><td><div className="progress"><i style={{width:run.progress + "%"}}/></div><small>{run.progress}%</small></td><td><Status value={run.status}/>{run.status === "Na fila" && <small className="queue-position">Posição {run.queuePosition ?? "—"}</small>}</td><td>{run.started}</td>
          {showActions && <td className="run-actions"><button type="button" className="delete-run" disabled={active || deletingId === run.id} title={active ? "Pare a análise antes de excluir" : "Excluir execução do histórico"} aria-label={"Excluir execução " + run.name} onClick={event => { event.stopPropagation(); onDelete?.(run); }}>{deletingId === run.id ? "…" : "🗑"}</button></td>}
        </tr>;
      }) : <tr><td colSpan={showActions ? 7 : 6} className="empty-table">Nenhuma execução registrada pelo serviço local.</td></tr>}</tbody>
    </table></div>
  </article>;
}

function LiveTerminal({ text }: { text:string }) {
  const terminalRef = useRef<HTMLPreElement>(null);
  useEffect(() => {
    if (terminalRef.current) terminalRef.current.scrollTop = terminalRef.current.scrollHeight;
  }, [text]);
  return <pre ref={terminalRef} className="terminal terminal-live">{text || "Aguardando a primeira saída do Nextflow..."}</pre>;
}

function RunsPage({ runs, setView, selectedRunId, setSelectedRunId, lastUpdated, onCancel, onDelete }: { runs:Run[]; setView:(v:View)=>void; selectedRunId:string; setSelectedRunId:(id:string)=>void; lastUpdated:Date|null; onCancel:(id:string)=>Promise<void>; onDelete:(id:string)=>Promise<void> }) {
  const [filter, setFilter] = useState<RunFilter>("all");
  const [stoppingId, setStoppingId] = useState("");
  const [deletingId, setDeletingId] = useState("");
  const filteredRuns = runs.filter(run => filter === "all"
    || (filter === "running" && ["Executando", "Na fila"].includes(run.status))
    || (filter === "completed" && run.status === "Concluída")
    || (filter === "error" && ["Com erro", "Interrompida", "Cancelada"].includes(run.status)));
  const selected = filteredRuns.find(run => run.id === selectedRunId) ?? filteredRuns[0];
  const tabs: Array<[RunFilter, string]> = [["all","Todas"],["running","Em andamento"],["completed","Concluídas"],["error","Com erro"]];
  const activeStage = selected?.stages.findIndex(stage => stage.progress < 100) ?? -1;
  async function stopSelected() {
    if (!selected) return;
    const message = selected.status === "Na fila"
      ? "Cancelar a análise " + selected.name + " que está aguardando na fila?"
      : "Parar a análise " + selected.name + "? As tarefas em execução serão encerradas.";
    if (!window.confirm(message)) return;
    setStoppingId(selected.id);
    try { await onCancel(selected.id); }
    catch (error) { window.alert(error instanceof Error ? error.message : "Não foi possível parar a análise"); }
    finally { setStoppingId(""); }
  }
  async function deleteRun(run: Run) {
    if (["Executando", "Na fila"].includes(run.status)) {
      window.alert("Pare a análise antes de excluí-la.");
      return;
    }
    if (!window.confirm("Excluir a execução " + run.name + " do histórico?\n\nOs arquivos de resultados serão preservados.")) return;
    setDeletingId(run.id);
    try { await onDelete(run.id); }
    catch (error) { window.alert(error instanceof Error ? error.message : "Não foi possível excluir a execução"); }
    finally { setDeletingId(""); }
  }
  return <section>
    <div className="page-actions"><div className="segmented">{tabs.map(([id,label])=><button key={id} className={filter === id ? "active" : ""} aria-pressed={filter === id} onClick={() => setFilter(id)}>{label}</button>)}</div><button className="primary" onClick={() => setView("new")}>+ Nova análise</button></div>
    <RunsTable runs={filteredRuns} onSelect={setSelectedRunId} selectedId={selected?.id} onDelete={deleteRun} deletingId={deletingId}/>
    {selected ? <article className="panel live-panel">
      <div className="live-head"><div><span className={["Executando","Na fila"].includes(selected.status) ? "pulse-dot" : "status-dot"}/><div><strong>{selected.currentProcess}</strong><small>{selected.name} · {selected.virus} · {selected.status}</small></div></div><div className="live-actions"><b>{selected.progress}%</b>{["Executando","Na fila"].includes(selected.status) && <button type="button" className="stop-analysis" disabled={stoppingId === selected.id} onClick={stopSelected}>{stoppingId === selected.id ? "Cancelando..." : selected.status === "Na fila" ? "Cancelar da fila" : "Parar análise"}</button>}</div></div>
      {selected.status === "Na fila" && <div className="queue-banner"><strong>Execução aguardando</strong><span>Posição {selected.queuePosition ?? "—"} · será iniciada automaticamente quando a análise atual terminar.</span></div>}
      <div className="stage-track">{selected.stages.map((stage,index)=><span key={stage.label} className={stage.progress === 100 ? "complete" : index === activeStage ? "active" : ""} title={stage.progress + "% concluído"}><i>{stage.progress === 100 ? "✓" : index + 1}</i>{stage.label}</span>)}</div>
      <div className="live-note"><span>Atualização automática a cada 3 segundos</span><span>Progresso estimado a partir das tarefas do log Nextflow</span><span>{lastUpdated ? "Última leitura: " + lastUpdated.toLocaleTimeString("pt-BR") : "Sincronizando..."}</span></div>
      <LiveTerminal text={selected.status === "Na fila" ? `Aguardando na fila. Posição atual: ${selected.queuePosition ?? "—"}.\nA execução será iniciada automaticamente.` : selected.log}/>
    </article> : <article className="panel empty-state"><h2>Nenhuma execução nesta categoria</h2><p>Escolha outra aba ou inicie uma nova análise.</p></article>}
  </section>;
}

function SamplesPage({ runs, lastUpdated }: { runs:Run[]; lastUpdated:Date|null }) {
  const [search, setSearch] = useState("");
  const [virusFilter, setVirusFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState("all");
  const rows = useMemo(() => {
    const collected = runs.flatMap(run => run.sampleRows.length ? run.sampleRows : run.sampleIds.map(sample => ({
      run_id: run.id, run_name: run.name, sample, virus: run.virus, qc: "—",
      reads: "", depth: "", coverage: "", lineage_genotype: "", status: run.status,
    })));
    return Array.from(new Map(collected.map(row => [row.run_id + ":" + row.sample, row])).values());
  }, [runs]);
  const virusesFound = Array.from(new Set(rows.map(row => row.virus))).sort();
  const statusesFound = Array.from(new Set(rows.map(row => row.status))).sort();
  const visibleRows = rows.filter(row => {
    const query = search.trim().toLowerCase();
    return (!query || [row.sample,row.virus,row.lineage_genotype,row.run_name].some(value => value.toLowerCase().includes(query)))
      && (virusFilter === "all" || row.virus === virusFilter)
      && (statusFilter === "all" || row.status === statusFilter);
  });
  function exportCsv() {
    const headers = ["Execução","Código da amostra","Vírus / Sorotipo","Status","Reads","Profundidade média","Cobertura","Linhagem / Genótipo"];
    const values = visibleRows.map(row => [row.run_name,row.sample,row.virus,row.status,row.reads,row.depth,row.coverage,row.lineage_genotype]);
    const encode = (value: string) => '"' + String(value ?? "").replace(/"/g, '""') + '"';
    const csv = [headers, ...values].map(row => row.map(encode).join(";")).join(String.fromCharCode(13,10));
    const url = URL.createObjectURL(new Blob(["﻿" + csv], { type: "text/csv;charset=utf-8" }));
    const anchor = document.createElement("a");
    anchor.href = url; anchor.download = "mkva_amostras.csv"; anchor.click();
    URL.revokeObjectURL(url);
  }
  return <section>
    <div className="sample-toolbar"><div className="search"><span>⌕</span><input value={search} onChange={event => setSearch(event.target.value)} placeholder="Buscar código, vírus, execução ou genótipo..."/></div>
      <select value={virusFilter} onChange={event => setVirusFilter(event.target.value)}><option value="all">Todos os vírus</option>{virusesFound.map(value=><option key={value}>{value}</option>)}</select>
      <select value={statusFilter} onChange={event => setStatusFilter(event.target.value)}><option value="all">Todos os status</option>{statusesFound.map(value=><option key={value}>{value}</option>)}</select>
      <button onClick={exportCsv} disabled={!visibleRows.length}>Exportar tabela</button>
    </div>
    <article className="panel data-panel samples-panel"><div className="table-title"><div><h2>Amostras disponíveis</h2><p>{rows.length} amostras lidas de {runs.length} execuções locais.</p></div><span className="updated">{lastUpdated ? "Atualizado às " + lastUpdated.toLocaleTimeString("pt-BR") : "Sincronizando..."}</span></div>
      <div className="table-wrap"><table><thead><tr><th>Código da amostra</th><th>Execução</th><th>Vírus / Sorotipo</th><th>Status</th><th>Reads</th><th>Profundidade média</th><th>Cobertura</th><th>Linhagem / Genótipo</th></tr></thead>
        <tbody>{visibleRows.length ? visibleRows.map(row=><tr key={row.run_id + row.sample}><td><strong className="sample-id">{row.sample}</strong></td><td>{row.run_name}</td><td>{row.virus}</td><td><Status value={row.status}/></td><td>{row.reads || "—"}</td><td>{row.depth || "—"}</td><td>{row.coverage || "—"}</td><td><strong>{row.lineage_genotype || "—"}</strong></td></tr>) : <tr><td colSpan={8} className="empty-table">Nenhuma amostra real disponível para os filtros atuais.</td></tr>}</tbody>
      </table></div>
    </article>
  </section>;
}

const resultCards: Record<string, { description:string; type:string; action:string }> = {
  dashboard: { description:"Visão interativa da execução, qualidade e variantes.", type:"HTML", action:"Abrir dashboard" },
  consensus: { description:"FASTA individual e multifasta produzidos pelo pipeline.", type:"FASTA", action:"Baixar sequências" },
  metadata: { description:"Planilha consolidada gerada quando metadados são informados.", type:"XLSX", action:"Baixar planilha" },
  gisaid: { description:"Planilha (.xls) e FASTA renomeado para envio em lote ao GISAID, gerados quando os dados institucionais são informados.", type:"GISAID", action:"Baixar submissão GISAID" },
  quality: { description:"Relatório MultiQC produzido pela execução.", type:"HTML", action:"Abrir relatório" },
  variants: { description:"Arquivos TSV de variantes por amostra.", type:"TSV", action:"Baixar variantes" },
  taxonomy: { description:"Visualização Krona da classificação taxonômica.", type:"HTML", action:"Explorar Krona" },
};

function ResultsPage({ runs, selectedRunId, setSelectedRunId }: { runs:Run[]; selectedRunId:string; setSelectedRunId:(id:string)=>void }) {
  const selected = runs.find(run => run.id === selectedRunId) ?? runs[0];
  const activeRunId = selected?.id ?? "";
  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const [loading, setLoading] = useState(false);
  useEffect(() => {
    let active = true;
    async function loadArtifacts() {
      if (!activeRunId) { setArtifacts([]); return; }
      setLoading(true);
      try {
        const response = await fetch("http://localhost:8787/api/jobs/" + encodeURIComponent(activeRunId) + "/artifacts", { cache:"no-store" });
        const payload = response.ok ? await response.json() as { artifacts?:Artifact[] } : {};
        if (active) setArtifacts(payload.artifacts ?? []);
      } catch {
        if (active) setArtifacts([]);
      } finally {
        if (active) setLoading(false);
      }
    }
    loadArtifacts();
    const timer = window.setInterval(loadArtifacts, 3000);
    return () => { active = false; window.clearInterval(timer); };
  }, [activeRunId]);
  if (!selected) return <article className="panel empty-state"><h2>Nenhuma execução disponível</h2><p>Inicie uma análise para que os resultados reais apareçam aqui.</p></article>;
  return <section>
    <div className="result-selector"><div><span>RESULTADOS DA EXECUÇÃO</span><strong>{selected.name} · {selected.status}</strong><small>{selected.outdir}</small></div><select value={selected.id} onChange={event => setSelectedRunId(event.target.value)}>{runs.map(run=><option key={run.id} value={run.id}>{run.id} · {run.status}</option>)}</select></div>
    {loading && !artifacts.length ? <article className="panel empty-state"><p>Localizando os arquivos reais da execução...</p></article> : <div className="result-grid">{Object.entries(resultCards).map(([key, card],index) => {
      const artifact = artifacts.find(item => item.key === key);
      const available = Boolean(artifact?.available);
      const unavailableMessage = selected.status === "Concluída" ? "Este artefato não foi gerado nesta execução." : "Aguardando o pipeline produzir este artefato.";
      return <article className={"panel result-card " + (!available ? "result-unavailable" : "")} key={key}><div className={"file-icon file-" + index}>{card.type}</div><div><h3>{artifact?.title ?? key}</h3><p>{card.description}</p>{available ? <a className="result-action" href={artifact?.url} target={artifact?.opens_inline ? "_blank" : undefined} rel="noreferrer">{card.action} <span>→</span></a> : <button disabled title={unavailableMessage}>Indisponível</button>}<small className="artifact-count">{available ? artifact?.count + (artifact?.count === 1 ? " arquivo real" : " arquivos reais") : unavailableMessage}</small></div></article>;
    })}</div>}
  </section>;
}
