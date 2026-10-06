process BWA_INDEX {
    tag "$ref_key"
    label 'process_single'

    conda "bioconda::bwa=0.7.18"
    container "${ workflow.containerEngine == 'singularity' ? 'https://depot.galaxyproject.org/singularity/mulled-v2-fe8faa35dbf6dc65a0f7f5d4ea12e31a79f73e40:66ed1b38d280722529bb8a0167b0cf02f8a0b488-0' : 'quay.io/biocontainers/mulled-v2-fe8faa35dbf6dc65a0f7f5d4ea12e31a79f73e40:66ed1b38d280722529bb8a0167b0cf02f8a0b488-0' }"

    input:
    tuple val(ref_key), path(reference)

    output:
    tuple val(ref_key), path(reference), path("${reference.name}.*"), emit: index
    path 'versions.yml', emit: versions

    script:
    """
    bwa index ${reference}

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        bwa: \$(bwa 2>&1 | sed -n 's/^Version: //p')
    END_VERSIONS
    """
}
