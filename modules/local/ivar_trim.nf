process IVAR_TRIM {
    tag "$meta.id"
    label 'process_medium'

    conda "bioconda::ivar=1.4.3 bioconda::samtools=1.20"
    container "quay.io/biocontainers/ivar:1.4.3--h43eeafb_0"

    input:
    tuple val(meta), path(bam), path(bai), path(reference), path(primer_bed)

    output:
    tuple val(meta), path('*.trim.sorted.bam'), path('*.trim.sorted.bam.bai'), path(reference), emit: bam
    path 'versions.yml'                                                                        , emit: versions

    script:
    """
    ivar trim -e \\
        -i ${bam} \\
        -b ${primer_bed} \\
        -m ${params.min_cov} \\
        -q ${params.min_qual} \\
        -p ${meta.id}.trim

    samtools sort -@ $task.cpus -o ${meta.id}.trim.sorted.bam ${meta.id}.trim.bam
    samtools index -@ $task.cpus ${meta.id}.trim.sorted.bam

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        ivar: \$(ivar version | sed -n 's/iVar version //p')
        samtools: \$(samtools --version | head -n1 | sed 's/samtools //')
    END_VERSIONS
    """
}
