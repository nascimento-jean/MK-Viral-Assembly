process SAMTOOLS_STATS {
    tag "$meta.id"
    label 'process_low'

    conda "bioconda::samtools=1.20"
    container "quay.io/biocontainers/samtools:1.20--h50ea8bc_0"

    input:
    tuple val(meta), path(bam), path(bai), path(reference)

    output:
    tuple val(meta), path('*.flagstat'), emit: flagstat
    tuple val(meta), path('*.stats')   , emit: stats
    tuple val(meta), path('*.depth.txt'), emit: depth
    path 'versions.yml'                , emit: versions

    script:
    """
    samtools flagstat ${bam} > ${meta.id}.flagstat
    samtools stats ${bam}    > ${meta.id}.stats
    samtools depth -a ${bam} > ${meta.id}.depth.txt

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        samtools: \$(samtools --version | head -n1 | sed 's/samtools //')
    END_VERSIONS
    """
}
