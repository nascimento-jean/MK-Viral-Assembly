process BLAST_SUMMARY {
    tag "$vdir"
    label 'process_single'

    conda "conda-forge::python=3.10"
    container "quay.io/biocontainers/python:3.10"

    input:
    tuple val(vdir), path(raw, stageAs: "blast_raw.tsv")

    output:
    tuple val(vdir), path("blast_summary.tsv"), emit: tsv
    tuple val(vdir), path("blast_raw.tsv")    , emit: raw
    path 'versions.yml'     , emit: versions

    script:
    """
    blast_summary.py --raw blast_raw.tsv --out blast_summary.tsv

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        python: \$(python --version | sed 's/Python //')
    END_VERSIONS
    """
}
