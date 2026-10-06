process KRAKEN2 {
    tag "$meta.id"
    label 'process_high'

    conda "bioconda::kraken2=2.1.3"
    container "${ workflow.containerEngine == 'singularity' ? 'https://depot.galaxyproject.org/singularity/kraken2:2.1.3--pl5321hdcf5f25_0' : 'quay.io/biocontainers/kraken2:2.1.3--pl5321hdcf5f25_0' }"

    input:
    tuple val(meta), path(reads)
    path db

    output:
    tuple val(meta), path('*.kraken2.report.txt'), emit: report
    tuple val(meta), path('*.kraken2.out.txt')   , emit: output
    path 'versions.yml'                           , emit: versions

    script:
    def read_args = meta.single_end ? "${reads[0]}" : "--paired ${reads[0]} ${reads[1]}"
    """
    kraken2 \\
        --db ${db} \\
        --threads $task.cpus \\
        ${read_args} \\
        --report ${meta.id}.kraken2.report.txt \\
        --output ${meta.id}.kraken2.out.txt

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        kraken: \$(kraken2 --version | head -n1 | sed 's/Kraken version //')
    END_VERSIONS
    """
}
