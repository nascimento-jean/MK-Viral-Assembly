process IVAR_VARIANTS {
    tag "$meta.id"
    label 'process_medium'

    conda "bioconda::ivar=1.4.3 bioconda::samtools=1.20"
    container "quay.io/biocontainers/ivar:1.4.3--h43eeafb_0"

    input:
    tuple val(meta), path(bam), path(bai), path(reference), path(gff)

    output:
    // raw iVar table (with REF_AA/ALT_AA/POS_AA columns when a GFF is given);
    // the gff is carried along so ANNOTATE_AA can add the aa_change column.
    tuple val(meta), path('*.ivar.tsv'), path(gff), emit: tsv
    path 'versions.yml'                            , emit: versions

    script:
    // -g <gff> makes iVar annotate REF_AA/ALT_AA/POS_AA; skipped when no GFF is provided.
    def has_gff = gff && gff.name != 'NO_FILE'
    def gff_arg = has_gff ? "-g ${gff}" : ""
    """
    samtools faidx ${reference}
    samtools mpileup -aa -A -d 0 -B -Q 0 --reference ${reference} -q ${params.min_map_qual} ${bam} \\
        | ivar variants \\
            -p ${meta.id}.ivar \\
            -r ${reference} \\
            ${gff_arg} \\
            -m ${params.min_cov} \\
            -q ${params.min_qual} \\
            -t ${params.min_freq}

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        ivar: \$(ivar version | sed -n 's/iVar version //p')
        samtools: \$(samtools --version | head -n1 | sed 's/samtools //')
    END_VERSIONS
    """
}
