process CONSENSUS_QC {
    tag "$meta.id"
    label 'process_single'

    conda "conda-forge::python=3.10"
    container "quay.io/biocontainers/python:3.10"

    input:
    // depth is the `samtools depth -a` file produced by SAMTOOLS_STATS
    tuple val(meta), path(consensus), path(depth)

    output:
    tuple val(meta), path('*.consensus_qc.tsv'), emit: tsv
    path 'versions.yml'                        , emit: versions

    script:
    """
    consensus_qc.py \\
        --sample ${meta.id} \\
        --fasta ${consensus} \\
        --depth ${depth} \\
        --min-depth ${params.min_cov} \\
        --out ${meta.id}.consensus_qc.tsv

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        python: \$(python --version | sed 's/Python //')
    END_VERSIONS
    """
}
