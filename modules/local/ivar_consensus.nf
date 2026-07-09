process IVAR_CONSENSUS {
    tag "$meta.id"
    label 'process_medium'

    conda "bioconda::ivar=1.4.3 bioconda::samtools=1.20"
    container "quay.io/biocontainers/ivar:1.4.3--h43eeafb_0"

    input:
    tuple val(meta), path(bam), path(bai), path(reference)

    output:
    tuple val(meta), path('*.consensus.fa'), emit: consensus
    tuple val(meta), path('*.qual.txt')    , emit: qual, optional: true
    path 'versions.yml'                    , emit: versions

    script:
    """
    # Index the reference and list its contigs. ivar consensus collapses the
    # whole pileup into ONE record, which fuses segments of a segmented genome.
    # To keep segments separate we call the consensus per contig and label each
    # record. For a single-contig reference the header is just the sample id;
    # for a multi-segment reference each record is >sample|contig.
    samtools faidx ${reference}
    contigs=\$(cut -f1 ${reference}.fai)
    n_contigs=\$(echo "\$contigs" | wc -l)

    : > ${meta.id}.consensus.fa
    for c in \$contigs; do
        samtools mpileup -aa -A -d 0 -B -Q 0 --reference ${reference} \\
                -q ${params.min_map_qual} -r "\$c" ${bam} \\
            | ivar consensus \\
                -p _tmp_\${c}.consensus \\
                -m ${params.min_cov} \\
                -q ${params.min_qual} \\
                -t ${params.min_freq} \\
                -n N

        if [ "\$n_contigs" -eq 1 ]; then
            header=">${meta.id}"
        else
            header=">${meta.id}|\${c}"
        fi
        # Replace ivar's header (first line) with ours and normalize ambiguous
        # IUPAC consensus bases to N. This keeps downstream FASTAs conservative
        # and avoids carrying degenerate symbols into submission/typing outputs.
        { printf '%s\\n' "\$header"; tail -n +2 _tmp_\${c}.consensus.fa; } \\
            | awk '/^>/ { print; next } { gsub(/[RYSWKMBDHVryswkmbdhv]/, "N"); print }' \\
            >> ${meta.id}.consensus.fa
        # keep the per-contig quality file if ivar produced one
        [ -f _tmp_\${c}.consensus.qual.txt ] && mv _tmp_\${c}.consensus.qual.txt ${meta.id}.\${c}.qual.txt || true
    done
    rm -f _tmp_*.consensus.fa

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        ivar: \$(ivar version | sed -n 's/iVar version //p')
        samtools: \$(samtools --version | head -n1 | sed 's/samtools //')
    END_VERSIONS
    """
}
