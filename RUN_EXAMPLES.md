# MK_Viral-Assembly run examples

Run these commands from the repository root. Replace example paths with paths
available on your system.

## Single-virus run

```bash
nextflow run main.nf \
    -profile docker \
    --input /data/run17/sars-cov-2/ \
    --virus sars-cov-2 \
    --reference /refs/SARS-CoV-2.fasta \
    --primer_bed /refs/SARS-CoV-2_primers.bed \
    --gff /refs/SARS-CoV-2.gff3 \
    --kraken2_db /databases/kraken2_standard \
    --deplete_host true \
    --nextclade true \
    --nextclade_dataset sars-cov-2 \
    --blast_id true \
    --run_name run17 \
    --outdir results_run17
```

## Multi-virus samplesheet

The parent directory must contain one subdirectory per virus. Subdirectory
names must match keys in `assets/virus_catalog.tsv`.

```bash
python3 bin/make_samplesheet.py \
    --parent /data/run17 \
    --catalog assets/virus_catalog.tsv \
    --out samplesheet_run17.csv
```

## Multi-virus run with Docker

```bash
nextflow run main.nf \
    -profile docker \
    --input samplesheet_run17.csv \
    --outdir results_run17 \
    --nextclade true \
    --blast_id true \
    --deplete_host true \
    --kraken2_db /databases/kraken2_standard \
    --run_name run17 \
    --max_cpus 10 \
    --max_memory 32.GB \
    -resume
```

## Multi-virus run with Singularity/Apptainer

```bash
nextflow run main.nf \
    -profile singularity \
    --input samplesheet_run17.csv \
    --outdir results_run17 \
    --nextclade true \
    --blast_id true \
    --deplete_host true \
    --kraken2_db /databases/kraken2_standard \
    --run_name run17 \
    --max_cpus 10 \
    --max_memory 32.GB \
    -resume
```

Consensus bases require 20x coverage by default. Change this threshold with
`--min_cov`.
