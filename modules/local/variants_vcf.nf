process VARIANTS_VCF {
    tag "$meta.id"
    label 'process_single'

    conda "conda-forge::python=3.10"
    container "${ workflow.containerEngine == 'singularity' ? 'https://depot.galaxyproject.org/singularity/python:3.10' : 'quay.io/biocontainers/python:3.10' }"

    input:
    tuple val(meta), path(variants)
    path helper

    output:
    tuple val(meta), path('*.variants.vcf'), emit: vcf
    path 'versions.yml', emit: versions

    script:
    """
    python ${helper} \\
        --input ${variants} \\
        --output ${meta.id}.variants.vcf \\
        --source "MK-Viral-Assembly-${workflow.manifest.version}"

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        python: \$(python --version | sed 's/Python //')
    END_VERSIONS
    """
}
