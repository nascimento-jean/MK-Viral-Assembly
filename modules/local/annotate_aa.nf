process ANNOTATE_AA {
    tag "$meta.id"
    label 'process_single'

    conda "conda-forge::python=3.10"
    container "quay.io/biocontainers/python:3.10"

    input:
    tuple val(meta), path(ivar_tsv), path(gff)

    output:
    tuple val(meta), path('*.variants.tsv'), emit: tsv
    path 'versions.yml'                     , emit: versions

    script:
    // Add the human-readable aa_change column when a GFF is available; otherwise
    // just pass the nucleotide-level iVar table through unchanged. This runs in a
    // Python container because the iVar image ships no interpreter.
    def has_gff = gff && gff.name != 'NO_FILE'
    """
    if ${has_gff}; then
        annotate_aa.py --in ${ivar_tsv} --gff ${gff} --out ${meta.id}.variants.tsv
    else
        cp ${ivar_tsv} ${meta.id}.variants.tsv
    fi

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        python: \$(python --version | sed 's/Python //')
    END_VERSIONS
    """
}
