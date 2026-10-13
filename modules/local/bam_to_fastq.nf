process BAM_TO_FASTQ {
    tag "$meta.id"
    label 'process_medium'

    conda "bioconda::samtools=1.20"
    container "${ workflow.containerEngine == 'singularity' ? 'https://depot.galaxyproject.org/singularity/samtools:1.20--h50ea8bc_0' : 'quay.io/biocontainers/samtools:1.20--h50ea8bc_0' }"

    input:
    tuple val(meta), path(bam), path(bai), path(reference)

    output:
    tuple val(meta), path('*_R{1,2}.fastq.gz'), path(reference), emit: reads
    path 'versions.yml', emit: versions

    script:
    """
    samtools collate -u -O ${bam} \
      | samtools fastq -@ $task.cpus -1 ${meta.id}_R1.fastq.gz -2 ${meta.id}_R2.fastq.gz \
          -0 /dev/null -s /dev/null -n -

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        samtools: \$(samtools --version | head -n1 | sed 's/samtools //')
    END_VERSIONS
    """
}
