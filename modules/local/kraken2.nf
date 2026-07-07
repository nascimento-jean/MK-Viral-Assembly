process KRAKEN2 {
    tag "$meta.id"
    label 'process_high'

    conda "bioconda::kraken2=2.1.3"
    container "quay.io/biocontainers/kraken2:2.1.3--pl5321hdcf5f25_0"

    input:
    tuple val(meta), path(reads)
    path db

    output:
    tuple val(meta), path('*.kraken2.report.txt'), emit: report
    tuple val(meta), path('*.kraken2.out.txt')   , emit: output
    path 'versions.yml'                           , emit: versions

    script:
    """
    kraken2 \\
        --db ${db} \\
        --threads $task.cpus \\
        --paired ${reads[0]} ${reads[1]} \\
        --report ${meta.id}.kraken2.report.txt \\
        --output ${meta.id}.kraken2.out.txt

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        kraken2: \$(kraken2 --version | head -n1 | sed 's/Kraken version //')
    END_VERSIONS
    """
}
