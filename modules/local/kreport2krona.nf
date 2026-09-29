process KREPORT2KRONA {
    tag "$meta.id"
    label 'process_single'

    conda "conda-forge::python=3.10"
    container "${ workflow.containerEngine == 'singularity' ? 'https://depot.galaxyproject.org/singularity/python:3.10' : 'quay.io/biocontainers/python:3.10' }"

    input:
    tuple val(meta), path(report)

    output:
    tuple val(meta), path("*.krona.txt"), emit: txt
    path 'versions.yml', emit: versions

    script:
    """
    kreport2krona.py --report ${report} --out ${meta.id}.krona.txt

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        python: \$(python --version | sed 's/Python //')
    END_VERSIONS
    """
}
