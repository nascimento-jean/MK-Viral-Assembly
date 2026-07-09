# MK_Viral-Assembly parameters and execution guide

MK_Viral-Assembly is a virus-agnostic Nextflow pipeline for reference-based
assembly of viral genomes from paired-end Illumina short reads. The reference
is a parameter, so the same code can be used for any RNA or DNA virus with an
appropriate reference FASTA.

## 1. Nextflow and pipeline options

- Pipeline parameters use two hyphens: `--input`, `--reference`, `--min_cov`.
- Nextflow options use one hyphen: `-profile`, `-resume`, `-c`, `-params-file`.
- Option order does not matter.

Minimal samplesheet run:

```bash
nextflow run main.nf \
    --input samplesheet.csv \
    --reference reference.fasta \
    --outdir results \
    -profile docker
```

Folder-input run:

```bash
nextflow run main.nf \
    --input /data/fastqs/ \
    --reference reference.fasta \
    --virus chikv \
    --outdir results \
    -profile docker
```

Display the built-in help:

```bash
nextflow run main.nf --help
```

## 2. Input and output

### `--input <samplesheet.csv | directory>` — required

Two input modes are supported:

1. A CSV samplesheet with at least `sample,fastq_1,fastq_2`.
2. A directory containing paired FASTQ files.

Folder mode automatically detects `_R1/_R2` or `_1/_2` pairs with
`.fastq.gz` or `.fq.gz` extensions. Lane tokens such as `_L001` are removed
from sample identifiers. Folder mode requires a global `--reference`.

Use `--fastq_pattern` if filenames do not match the automatic pattern.

### Input FASTQ validation

Every FASTQ pair is checked before the first processing step. Empty files,
valid gzip files with no reads, truncated gzip files and malformed FASTQ records
are marked as `skipped` and do not enter downstream modules. The run continues
with the remaining valid samples.

Per-sample validation files are written to:

```text
results/<virus>/sample_validation/
```

### Negative controls (`CN*`)

Samples whose sample ID or FASTQ filename starts with `CN` are treated as
negative controls. Valid `CN*` controls run through initial read processing and,
when `--kraken2_db` is provided, Kraken2/Krona taxonomic screening. They are
excluded from host depletion, reference mapping, variant calling, consensus
generation, Nextclade, BLAST and combined FASTA outputs.

In the dashboard, the **Run Validation** tab reports each negative control
separately. Controls without viral signal are named as validated; controls with
viral signal trigger an attention message and show the negative-control Krona
result. Empty/problematic `CN*` inputs are skipped and reported as having no
observed viral contamination.

### `--reference <reference.fasta>`

Global reference FASTA. It is required unless every samplesheet row provides
its own `reference`. Per-sample values override this option.

For segmented viruses such as Oropouche, supply one multi-FASTA containing all
segments. Mapping, variant calling, consensus generation, and QC are performed
per contig automatically.

Influenza is outside this pipeline's scope and should be processed with a
dedicated influenza workflow.

### `--outdir <directory>` — default: `results`

Directory where published results are written.

### `--virus <label>` — folder mode only

Names the per-virus output directory and dashboard in folder mode. In
samplesheet mode, the per-row `virus` column takes precedence. Labels are
lowercased and sanitized with `[^a-z0-9._-] -> _`; an empty label becomes
`unspecified_virus`.

### `--fastq_pattern <glob>`

Custom Nextflow glob for folder mode. Example:

```bash
--fastq_pattern '/data/run17/*_{R1,R2}_001.fastq.gz'
```

## 3. Alignment and consensus thresholds

### `--aligner <bwa|minimap2>` — default: `bwa`

- `bwa`: BWA-MEM, the established default for Illumina short reads.
- `minimap2`: uses the `-ax sr` short-read preset.

### `--min_cov <integer>` — default: `20`

Minimum depth required to call a consensus base. Positions below this value
become `N`. The same threshold is used for coverage breadth and primer
trimming. Suggested values:

- Routine surveillance: `20`
- Low viral load: `10` or `5`
- More stringent calling: `30`

`--min_depth` is retained as a deprecated alias; use `--min_cov` in new runs.

### `--min_freq <0-1>` — default: `0.75`

Minimum alternate-allele frequency used for the consensus call.

### `--min_qual <integer>` — default: `20`

Minimum Phred base quality used by iVar.

### `--min_map_qual <integer>` — default: `20`

Minimum mapping quality used by samtools/iVar.

## 4. Primer trimming and amino-acid annotation

### `--primer_bed <primers.bed>`

Optional amplicon-primer BED file. When supplied, `ivar trim` removes primer
regions before variant calling. Use it for tiled-amplicon schemes such as ARTIC
or Midnight, but not for shotgun/metagenomic or capture data.

BED coordinates must match the selected reference. A samplesheet `bed_file`
value overrides the global BED for that sample.

### `--gff <annotation.gff3>`

Optional reference GFF3 containing CDS features. When supplied, the variants
table gains an `aa_change` column such as `S:N501Y`. Synonymous changes use
notation such as `N:R203=` and are omitted from the dashboard's nonsynonymous
mutation list.

GFF sequence identifiers and coordinates must match the reference. A
samplesheet `gff` value overrides the global GFF for that sample.

## 5. Optional analyses

### `--kraken2_db <directory>`

Enables Kraken2 taxonomic screening, the dashboard Taxonomy tab, Krona, and
optional host depletion. The database is not bundled with the pipeline.

Use a database containing the host genome when enabling `--deplete_host`.

### `--deplete_host <true|false>` — default: `false`

Removes host-classified reads before alignment. Requires `--kraken2_db`.

### `--host_taxid <integer>` — default: `9606`

NCBI taxon removed by host depletion, including child taxa. `9606` is
*Homo sapiens*.

### `--mixed_min_freq <0-1>` — default: `0.20`

### `--mixed_max_freq <0-1>` — default: `0.80`

Define the allele-frequency interval for mixed sites. Mixed sites per kb are
reported as a contamination/co-infection indicator and are highlighted at
`>=1.0/kb`.

### `--nextclade <true|false>` — default: `false`

Enables Nextclade clade, lineage, or genotype assignment.

### `--nextclade_dataset <catalog path|alias>`

Global fallback dataset. Supported aliases include:

`sars-cov-2`, `dengue`, `denv1`, `denv2`, `denv3`, `denv4`, `chikv`,
`rsv-a`, `rsv-b`, `zika`, `yellow-fever`, and `oropouche`.

The `oropouche` alias detects segments and runs the L/M/S Tefé datasets.
Per-sample `nextclade_dataset` values override this option.

### `--nextclade_tag <tag>`

Pins the Nextclade dataset version for reproducibility. If omitted, the latest
version is used and recorded in the report.

### `--nextclade_datasets_dir <directory>`

Persistent dataset cache. Default: `assets/nextclade_datasets`.

### `--blast_id <true|false>` — default: `false`

Confirms consensus identity with BLAST against a local viral RefSeq database.
The best species hit, accession, identity, and coverage are shown in the
dashboard.

### `--blast_db_dir <directory>`

Persistent local viral RefSeq BLAST database. Default:
`assets/blast_refseq_viral`.

### `--blast_db_max_age_days <integer>` — default: `7`

Rebuilds the local RefSeq database on the first run after it exceeds this age.

## 6. Skipping steps and dashboard settings

- `--skip_fastqc`: skip raw and trimmed-read FastQC.
- `--skip_multiqc`: skip the aggregate MultiQC report.
- `--skip_mixed_sites`: skip intra-sample heterozygosity screening.
- `--skip_dashboard`: skip dashboard generation.
- `--skip_combine`: skip combined multi-FASTA generation.

### `--combine_min_status <PASS|WARN|FAIL>` — default: `WARN`

Lowest QC class retained in combined multi-FASTAs:

- `PASS`: retain PASS only.
- `WARN`: retain PASS and WARN; exclude FAIL.
- `FAIL`: retain all samples.

Excluded samples are recorded in `excluded_samples[.<run>].txt`. Individual
sample consensus FASTAs are never filtered.

### `--run_name <label>`

Run label displayed in the dashboard header and used in combined FASTA names.

### `--dash_pass <0-1>` — default: `0.90`

Minimum consensus completeness for PASS.

### `--dash_warn <0-1>` — default: `0.70`

Minimum consensus completeness for WARN; lower values are FAIL.

### `--publish_dir_mode <copy|symlink|link|move>` — default: `copy`

Controls how results are published. `copy` is safest because outputs remain
valid after deleting the Nextflow work directory.

## 7. Resource ceilings

- `--max_cpus <integer>` — default: `16`
- `--max_memory <value>` — default: `60.GB`
- `--max_time <value>` — default: `24.h`

Laptop example:

```bash
--max_cpus 4 --max_memory 7.GB
```

## 8. Samplesheet format

All columns after `fastq_2` are optional and can vary by sample:

```csv
sample,fastq_1,fastq_2,virus,reference,gff,bed_file,nextclade_dataset
chikv_01,/data/chikv_01_R1.fastq.gz,/data/chikv_01_R2.fastq.gz,chikv,/refs/CHIKV.fasta,/refs/CHIKV.gff3,/refs/chikv.bed,chikv
denv2_02,/data/denv2_02_R1.fastq.gz,/data/denv2_02_R2.fastq.gz,denv2,/refs/DENV2.fasta,,/refs/denv2.bed,denv2
orov_03,/data/orov_03_R1.fastq.gz,/data/orov_03_R2.fastq.gz,orov,/refs/OROV.fasta,/refs/OROV.gff3,,oropouche
```

- `sample`: unique identifier used in output filenames and FASTA headers.
- `fastq_1`, `fastq_2`: paired gzipped FASTQs.
- `virus`: label and virus-catalog key.
- `reference`: per-sample reference override.
- `gff`: per-sample annotation override.
- `bed_file`: per-sample primer BED override.
- `nextclade_dataset`: per-sample Nextclade dataset override.

Generate a multi-virus samplesheet from one subfolder per virus:

```bash
python3 bin/make_samplesheet.py \
    --parent /data/run17 \
    --catalog assets/virus_catalog.tsv \
    -o samplesheet.csv
```

Generate a single-virus samplesheet:

```bash
python3 bin/make_samplesheet.py \
    --indir /data/run17/chikv \
    --virus chikv \
    -o samplesheet.csv
```

## 9. Nextflow execution options

- `-profile docker`: run with Docker.
- `-profile singularity`: run with Singularity/Apptainer.
- `-profile conda`: create per-process Conda environments.
- `-profile test,docker`: run the bundled test dataset.
- `-profile standalone`: use tools already installed in `PATH`.
- `-resume`: reuse valid cached results.
- `-params-file params.yaml`: load pipeline parameters from YAML/JSON.
- `-c custom.config`: load an additional Nextflow configuration.
- `-work-dir <directory>`: set the intermediate work directory.

## 10. Virus-specific examples

### SARS-CoV-2

```bash
nextflow run main.nf \
    --input samplesheet_sc2.csv \
    --reference refs/SARSCoV2_MN908947.3.fasta \
    --primer_bed refs/ARTIC_v5.3.2_primers.bed \
    --outdir results_sc2 \
    --min_cov 20 \
    -profile docker
```

### Dengue

Common references: DENV-1 `NC_001477`, DENV-2 `NC_001474`, DENV-3
`NC_001475`, and DENV-4 `NC_002640`. Mixed-serotype runs can set a different
reference in each samplesheet row.

### Chikungunya

```bash
nextflow run main.nf \
    --input samplesheet_chikv.csv \
    --reference refs/CHIKV_NC_004162.fasta \
    --outdir results_chikv \
    --min_cov 10 \
    -profile docker
```

### Oropouche

Combine the L (`NC_005776`), M (`NC_005775`), and S (`NC_005777`) segments
into one multi-FASTA:

```bash
cat NC_005776.fasta NC_005775.fasta NC_005777.fasta > OROV_LMS.fasta

nextflow run main.nf \
    --input samplesheet_orov.csv \
    --reference refs/OROV_LMS.fasta \
    --outdir results_orov \
    --nextclade true \
    --nextclade_dataset oropouche \
    -profile docker
```

### Respiratory syncytial virus

Common references: RSV-A `NC_038235` and RSV-B `NC_001781`.

### Any other virus

Supply a compatible reference FASTA:

```bash
nextflow run main.nf \
    --input samplesheet.csv \
    --reference refs/MY_VIRUS.fasta \
    --outdir results_my_virus \
    -profile docker
```

## 11. Outputs

Results are nested by virus:

```text
outdir/
├── <virus>/
│   ├── fastqc/{raw,trimmed}/
│   ├── fastp/<sample>/
│   ├── alignment/
│   ├── variants/
│   ├── mixed_sites/
│   ├── read_stats/
│   ├── consensus/
│   ├── consensus_qc/
│   ├── kraken2/
│   ├── krona/
│   ├── nextclade/
│   ├── blast/
│   └── <virus>_dashboard.html
├── multiqc/
└── pipeline_info/
```

The dashboard tabs are Overview, Samples, Coverage, Mutations,
Lineages/Genotypes, Taxonomy, and Segments. Optional tabs appear only when
their corresponding analyses are enabled.

## 12. Reproducibility recommendations

- Prefer Docker or Singularity/Apptainer profiles with pinned tool versions.
- Store the run's parameter file alongside the results.
- Keep `pipeline_info/` as the execution provenance record.
- Use `-resume` after interruptions or parameter adjustments.
