process FASTP {
    tag "$meta.id"
    label 'process_medium'

    conda "bioconda::fastp=0.23.4"
    container "quay.io/biocontainers/fastp:0.23.4--h5f740d0_0"

    input:
    tuple val(meta), path(reads)

    output:
    tuple val(meta), path('*.trim.fastq.gz'), emit: reads
    tuple val(meta), path('*.fastp.json')   , emit: json
    tuple val(meta), path('*.fastp.html')   , emit: html
    path 'versions.yml'                      , emit: versions

    script:
    def args = task.ext.args ?: ''
    """
    fastp \\
        --in1 ${reads[0]} \\
        --in2 ${reads[1]} \\
        --out1 ${meta.id}_1.trim.fastq.gz \\
        --out2 ${meta.id}_2.trim.fastq.gz \\
        --json ${meta.id}.fastp.json \\
        --html ${meta.id}.fastp.html \\
        --thread $task.cpus \\
        $args \\
        2> ${meta.id}.fastp.log

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        fastp: \$(fastp --version 2>&1 | sed -e "s/fastp //g")
    END_VERSIONS
    """
}
