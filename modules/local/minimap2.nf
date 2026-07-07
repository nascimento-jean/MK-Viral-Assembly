process MINIMAP2 {
    tag "$meta.id"
    label 'process_high'

    conda "bioconda::minimap2=2.28 bioconda::samtools=1.20"
    container "quay.io/biocontainers/mulled-v2-66534bcbb7031a148b13e2ad42583020b9cd25c4:1679e915ddb9d6b4abda91880c4b48857d471bd8-0"

    input:
    tuple val(meta), path(reads), path(reference)

    output:
    tuple val(meta), path('*.sorted.bam'), path('*.sorted.bam.bai'), path(reference), emit: bam
    path 'versions.yml'                                                              , emit: versions

    script:
    def rg = "@RG\\tID:${meta.id}\\tSM:${meta.id}\\tPL:ILLUMINA"
    """
    minimap2 -ax sr -t $task.cpus -R "${rg}" ${reference} ${reads[0]} ${reads[1]} \\
        | samtools sort -@ $task.cpus -o ${meta.id}.sorted.bam -
    samtools index -@ $task.cpus ${meta.id}.sorted.bam

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        minimap2: \$(minimap2 --version)
        samtools: \$(samtools --version | head -n1 | sed 's/samtools //')
    END_VERSIONS
    """
}
