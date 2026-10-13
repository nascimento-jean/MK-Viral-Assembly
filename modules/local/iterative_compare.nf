process ITERATIVE_COMPARE {
    tag "$meta.id"
    label 'process_single'

    conda "conda-forge::python=3.10"
    container "${ workflow.containerEngine == 'singularity' ? 'https://depot.galaxyproject.org/singularity/python:3.10' : 'quay.io/biocontainers/python:3.10' }"

    input:
    tuple val(meta), path(first_qc), path(second_qc)
    path helper

    output:
    tuple val(meta), path('*.iterative_comparison.tsv'), emit: tsv
    path 'versions.yml', emit: versions

    script:
    """
    python3 ${helper} --sample ${meta.id} --first-qc ${first_qc} --second-qc ${second_qc} \
        --min-gain ${params.iterative_min_completeness_gain} \
        --max-breadth-loss ${params.iterative_max_breadth_loss} \
        --output ${meta.id}.iterative_comparison.tsv
    printf '"${task.process}":\n    python: %s\n' "\$(python3 --version | sed 's/Python //')" > versions.yml
    """
}
