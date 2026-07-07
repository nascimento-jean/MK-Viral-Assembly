process BWA_MEM {
    tag "$meta.id"
    label 'process_high'

    conda "bioconda::bwa=0.7.18 bioconda::samtools=1.20"
    container "quay.io/biocontainers/mulled-v2-fe8faa35dbf6dc65a0f7f5d4ea12e31a79f73e40:66ed1b38d280722529bb8a0167b0cf02f8a0b488-0"

    input:
    tuple val(meta), path(reads), path(reference)

    output:
    tuple val(meta), path('*.sorted.bam'), path('*.sorted.bam.bai'), path(reference), emit: bam
    path 'versions.yml'                                                              , emit: versions

    script:
    def rg = "@RG\\tID:${meta.id}\\tSM:${meta.id}\\tPL:ILLUMINA"
    """
    bwa index ${reference}
    bwa mem -t $task.cpus -R "${rg}" ${reference} ${reads[0]} ${reads[1]} \\
        | samtools sort -@ $task.cpus -o ${meta.id}.sorted.bam -
    samtools index -@ $task.cpus ${meta.id}.sorted.bam

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        bwa: \$(bwa 2>&1 | sed -n 's/^Version: //p')
        samtools: \$(samtools --version | head -n1 | sed 's/samtools //')
    END_VERSIONS
    """
}
