process ISNV_FILTER {
    tag "$meta.id"
    label 'process_single'

    conda "conda-forge::python=3.10"
    container "${ workflow.containerEngine == 'singularity' ? 'https://depot.galaxyproject.org/singularity/python:3.10' : 'quay.io/biocontainers/python:3.10' }"

    input:
    tuple val(meta), path(raw_tsv)
    path helper

    output:
    tuple val(meta), path('*.isnv.tsv'), emit: tsv
    path 'versions.yml', emit: versions

    script:
    """
    python3 ${helper} --sample ${meta.id} --input ${raw_tsv} \
        --output ${meta.id}.isnv.tsv --min-depth ${params.isnv_min_depth} \
        --min-alt-reads ${params.isnv_min_alt_reads} \
        --min-frequency ${params.isnv_min_freq} --max-frequency ${params.isnv_max_freq} \
        --min-quality ${params.isnv_min_qual} --min-strand-reads ${params.isnv_min_strand_reads} \
        --min-strand-balance ${params.isnv_min_strand_balance}

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        python: \$(python3 --version | sed 's/Python //')
    END_VERSIONS
    """
}
