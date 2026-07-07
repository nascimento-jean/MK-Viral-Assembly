process READ_STATS {
    tag "$meta.id"
    label 'process_single'

    conda "conda-forge::python=3.10"
    container "quay.io/biocontainers/python:3.10"

    input:
    // fastp JSON (raw + post-filter counts) and the dehosted reads (a NO_FILE
    // sentinel when host depletion is off). Both staged so read_stats.py can
    // read them without python living in any tool container.
    tuple val(meta), path(fastp_json), path(dehost, stageAs: "dehost/*")

    output:
    tuple val(meta), path("*.read_stats.tsv"), emit: tsv
    path 'versions.yml'                       , emit: versions

    script:
    """
    read_stats.py \\
        --sample ${meta.id} \\
        --fastp-json ${fastp_json} \\
        --dehost-dir dehost \\
        --out ${meta.id}.read_stats.tsv

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        python: \$(python --version | sed 's/Python //')
    END_VERSIONS
    """
}
