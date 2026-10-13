process PROVENANCE_SUMMARY {
    tag "run provenance"
    label 'process_single'

    conda "conda-forge::python=3.10"
    container "${ workflow.containerEngine == 'singularity' ? 'https://depot.galaxyproject.org/singularity/python:3.10' : 'quay.io/biocontainers/python:3.10' }"

    input:
    path module_files, stageAs: 'modules/*'
    path blast_date
    path helper

    output:
    path 'run_provenance.tsv', emit: tsv
    path 'versions.yml', emit: versions

    script:
    def profile = workflow.profile ?: ''
    def nc_dataset = params.nextclade_dataset ?: ''
    def nc_tag = params.nextclade_tag ?: 'latest'
    def blast_db = params.blast_id ? params.blast_db_dir : ''
    def kraken_db = params.kraken2_db ?: ''
    """
    python3 ${helper} --output run_provenance.tsv \
        --pipeline-version "${workflow.manifest.version}" \
        --nextflow-version "${nextflow.version}" \
        --profile "${profile}" --module-dir modules \
        --nextclade-dataset "${nc_dataset}" --nextclade-tag "${nc_tag}" \
        --blast-date ${blast_date} --blast-db "${blast_db}" \
        --kraken-db "${kraken_db}" --snpeff-enabled "${params.snpeff}"

    printf '"${task.process}":\n    python: %s\n' "\$(python3 --version | sed 's/Python //')" > versions.yml
    """
}
