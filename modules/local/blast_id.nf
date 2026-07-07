process BLASTN_ID {
    tag "$vdir"
    label 'process_medium'

    conda "bioconda::blast=2.17.0"
    container "quay.io/biocontainers/blast:2.17.0--h66d330f_0"

    input:
    tuple val(vdir), path(consensus, stageAs: "consensus/*")   // one virus' consensus FASTAs
    path(db)                                   // refseq_viral.* DB files
    path(build_date)                           // refseq_build_date.txt

    output:
    tuple val(vdir), path("blast_raw.tsv"), emit: raw
    path 'versions.yml'         , emit: versions

    script:
    """
    cat consensus/*.consensus.fa consensus/*.fa 2>/dev/null | awk 'BEGIN{s=0} /^>/{s=1} s' > all.fasta || true

    # blastn each consensus record vs local RefSeq viral; keep best hit per query.
    # outfmt: qseqid sseqid pident length qcovs evalue bitscore stitle
    # (summary is done in a separate python:3.10 process — the blast container
    #  has no python interpreter.)
    blastn -query all.fasta -db refseq_viral \\
        -max_target_seqs 5 -evalue 1e-10 \\
        -outfmt '6 qseqid sseqid pident length qcovs evalue bitscore stitle' \\
        > blast_raw.tsv || true

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        blast: \$(blastn -version | head -1 | sed 's/blastn: //')
    END_VERSIONS
    """
}
