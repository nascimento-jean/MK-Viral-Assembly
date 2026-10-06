process AMPLICON_COVERAGE {
    tag "$meta.id"
    label 'process_single'

    conda "conda-forge::python=3.10"
    container "${ workflow.containerEngine == 'singularity' ? 'https://depot.galaxyproject.org/singularity/python:3.10' : 'quay.io/biocontainers/python:3.10' }"

    input:
    tuple val(meta), path(depth), path(bed)
    path helper

    output:
    tuple val(meta), path('*.amplicon_coverage.tsv'), emit: tsv
    path 'versions.yml', emit: versions

    script:
    """
    python ${helper} --sample ${meta.id} --bed ${bed} --depth ${depth} \\
        --min-depth ${params.min_cov} --min-breadth ${params.amplicon_min_breadth} \\
        --out ${meta.id}.amplicon_coverage.tsv
    printf '"${task.process}":\n    python: %s\n' "\$(python --version | sed 's/Python //')" > versions.yml
    """
}
