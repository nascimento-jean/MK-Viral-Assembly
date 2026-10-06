process BLAST_SUMMARY {
    tag "$vdir"
    label 'process_single'

    conda "conda-forge::python=3.10"
    container "${ workflow.containerEngine == 'singularity' ? 'https://depot.galaxyproject.org/singularity/python:3.10' : 'quay.io/biocontainers/python:3.10' }"

    input:
    tuple val(vdir), path(raw, stageAs: "blast_raw.tsv"), path(status, stageAs: "blast_status.tsv")

    output:
    tuple val(vdir), path("blast_summary.tsv"), emit: tsv
    tuple val(vdir), path("blast_raw.tsv")    , emit: raw
    tuple val(vdir), path("blast_status.tsv") , emit: status
    path 'versions.yml', emit: versions

    script:
    """
    blast_summary.py --raw blast_raw.tsv --status blast_status.tsv --out blast_summary.tsv

    printf '"${task.process}":\n    python: %s\n' \
        "\$(python --version | sed 's/Python //')" > versions.yml
    """
}
