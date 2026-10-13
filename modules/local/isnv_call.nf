process ISNV_CALL {
    tag "$meta.id"
    label 'process_medium'

    conda "bioconda::ivar=1.4.3 bioconda::samtools=1.20"
    container "${ workflow.containerEngine == 'singularity' ? 'https://depot.galaxyproject.org/singularity/ivar:1.4.3--h43eeafb_0' : 'quay.io/biocontainers/ivar:1.4.3--h43eeafb_0' }"

    input:
    tuple val(meta), path(bam), path(bai), path(reference)

    output:
    tuple val(meta), path('*.isnv_raw.tsv'), emit: tsv
    path 'versions.yml', emit: versions

    script:
    """
    samtools faidx ${reference}
    samtools mpileup -aa -A -d 0 -B -Q 0 --reference ${reference} \
            -q ${params.min_map_qual} ${bam} \
        | ivar variants -p ${meta.id}.isnv_raw -r ${reference} \
            -m ${params.isnv_min_depth} -q ${params.isnv_min_qual} -t ${params.isnv_min_freq}

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        ivar: \$(ivar version | sed -n 's/iVar version //p')
        samtools: \$(samtools --version | head -n1 | sed 's/samtools //')
    END_VERSIONS
    """
}
