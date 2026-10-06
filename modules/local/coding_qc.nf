process CODING_QC {
    tag "$meta.id"
    label 'process_single'

    conda "conda-forge::python=3.10"
    container "${ workflow.containerEngine == 'singularity' ? 'https://depot.galaxyproject.org/singularity/python:3.10' : 'quay.io/biocontainers/python:3.10' }"

    input:
    tuple val(meta), path(consensus), path(gff)
    path helper

    output:
    tuple val(meta), path('*.coding_qc.tsv'), emit: tsv
    path 'versions.yml', emit: versions

    script:
    """
    python ${helper} --sample ${meta.id} --fasta ${consensus} --gff ${gff} \\
        --out ${meta.id}.coding_qc.tsv
    printf '"${task.process}":\n    python: %s\n' "\$(python --version | sed 's/Python //')" > versions.yml
    """
}
