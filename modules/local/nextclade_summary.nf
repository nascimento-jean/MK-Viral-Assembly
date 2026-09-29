process NEXTCLADE_SUMMARY {
    tag "$vdir"
    label 'process_single'

    conda "conda-forge::python=3.10"
    container "${ workflow.containerEngine == 'singularity' ? 'https://depot.galaxyproject.org/singularity/python:3.10' : 'quay.io/biocontainers/python:3.10' }"

    input:
    tuple val(vdir), path(tsvs, stageAs: "nc/*")

    output:
    tuple val(vdir), path("nextclade_summary.tsv"), emit: tsv
    path 'versions.yml'         , emit: versions

    script:
    """
    nextclade_summary.py --nextclade-dir nc --out nextclade_summary.tsv

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        python: \$(python --version | sed 's/Python //')
    END_VERSIONS
    """
}
