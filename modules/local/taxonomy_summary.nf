process TAXONOMY_SUMMARY {
    label 'process_single'

    conda "conda-forge::python=3.10"
    container "quay.io/biocontainers/python:3.10"

    tag "$vdir"

    input:
    tuple val(vdir), path(reports, stageAs: "kraken/*")

    output:
    tuple val(vdir), path("taxonomy_summary.tsv"), emit: tsv
    path 'versions.yml'        , emit: versions

    script:
    """
    taxonomy_summary.py --kraken-dir kraken --out taxonomy_summary.tsv

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        python: \$(python --version | sed 's/Python //')
    END_VERSIONS
    """
}
