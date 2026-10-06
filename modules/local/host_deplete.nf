process HOST_DEPLETE {
    tag "$meta.id"
    label 'process_medium'

    conda "bioconda::krakentools=1.2.1"
    container "${ workflow.containerEngine == 'singularity' ? 'https://depot.galaxyproject.org/singularity/krakentools:1.2.1--pyh7e72e81_0' : 'quay.io/biocontainers/krakentools:1.2.1--pyh7e72e81_0' }"

    input:
    tuple val(meta), path(reads), path(kraken_output), path(kraken_report)

    output:
    tuple val(meta), path('*.dehost*.fastq.gz'), emit: reads
    path 'versions.yml'                         , emit: versions

    script:
    def taxid = params.host_taxid ?: 9606
    def input_args = meta.single_end ? "-s ${reads[0]}" : "-s1 ${reads[0]} -s2 ${reads[1]}"
    def output_args = meta.single_end ? "-o ${meta.id}.dehost.fastq" : "-o ${meta.id}.dehost_1.fastq -o2 ${meta.id}.dehost_2.fastq"
    def gzip_args = meta.single_end ? "${meta.id}.dehost.fastq" : "${meta.id}.dehost_1.fastq ${meta.id}.dehost_2.fastq"
    """
    extract_kraken_reads.py \\
        -k ${kraken_output} \\
        -r ${kraken_report} \\
        ${input_args} \\
        ${output_args} \\
        --taxid ${taxid} --include-children --exclude --fastq-output

    gzip -f ${gzip_args}

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        krakentools: 1.2.1
    END_VERSIONS
    """
}
