process HOST_DEPLETE {
    tag "$meta.id"
    label 'process_medium'

    conda "bioconda::krakentools=1.2.1"
    container "quay.io/biocontainers/krakentools:1.2.1--pyh7e72e81_0"

    input:
    tuple val(meta), path(reads), path(kraken_output), path(kraken_report)

    output:
    tuple val(meta), path('*.dehost_*.fastq.gz'), emit: reads
    path 'versions.yml'                          , emit: versions

    script:
    // Remove host reads (default taxid 9606 = Homo sapiens) and their children
    // BEFORE alignment. Uses the per-read Kraken2 classification (.out.txt) and
    // the report (needed for --include-children). Reads NOT matching the host
    // clade are kept (--exclude keeps everything except the requested taxa).
    def taxid = params.host_taxid ?: 9606
    """
    extract_kraken_reads.py \\
        -k ${kraken_output} \\
        -r ${kraken_report} \\
        -s1 ${reads[0]} -s2 ${reads[1]} \\
        -o ${meta.id}.dehost_1.fastq -o2 ${meta.id}.dehost_2.fastq \\
        --taxid ${taxid} --include-children --exclude --fastq-output

    gzip -f ${meta.id}.dehost_1.fastq ${meta.id}.dehost_2.fastq

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        krakentools: 1.2.1
    END_VERSIONS
    """
}
