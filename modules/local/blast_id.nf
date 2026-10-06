process BLASTN_ID {
    tag "$vdir"
    label 'process_medium'

    conda "bioconda::blast=2.17.0"
    container "${ workflow.containerEngine == 'singularity' ? 'https://depot.galaxyproject.org/singularity/blast:2.17.0--h66d330f_0' : 'quay.io/biocontainers/blast:2.17.0--h66d330f_0' }"

    input:
    tuple val(vdir), path(consensus, stageAs: "consensus/*")
    path(db)
    path(build_date)

    output:
    tuple val(vdir), path("blast_raw.tsv"), path("blast_status.tsv"), emit: raw
    path 'versions.yml', emit: versions

    script:
    """
    : > all.fasta
    find -L consensus -maxdepth 1 -type f \\( -name '*.consensus.fa' -o -name '*.fa' \\) -print0 \\
        | sort -z \\
        | xargs -0 -r cat \\
        | awk 'BEGIN{s=0} /^>/{s=1} s' > all.fasta

    status="OK"
    message=""
    : > blast_raw.tsv
    if ! grep -q '^>' all.fasta; then
        status="NO_CONSENSUS"
        message="No consensus sequence was available for BLAST."
    else
        set +e
        blastn -query all.fasta -db refseq_viral \\
            -max_target_seqs 5 -evalue 1e-10 \\
            -outfmt '6 qseqid sseqid pident length qcovs evalue bitscore stitle' \\
            > blast_raw.tsv
        rc=\$?
        set -e
        if [ "\$rc" -ne 0 ]; then
            status="BLAST_FAILED"
            message="blastn exited with status \$rc. Verify the executable and RefSeq viral database."
            : > blast_raw.tsv
            printf 'WARNING: %s\n' "\$message" >&2
        fi
    fi
    printf 'status\tmessage\n%s\t%s\n' "\$status" "\$message" > blast_status.tsv

    printf '"${task.process}":\n    blast: %s\n' \
        "\$(blastn -version | head -1 | sed 's/blastn: //')" > versions.yml
    """
}
