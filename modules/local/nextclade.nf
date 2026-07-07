process NEXTCLADE_RUN {
    label 'process_medium'

    conda "bioconda::nextclade=3.21.2"
    container "quay.io/biocontainers/nextclade:3.21.2--h9ee0642_0"

    input:
    tuple val(gkey), path(consensus, stageAs: "consensus/*"), path(datasets, stageAs: "ds/*"), val(segmented)
    // gkey       : virus-group key (the per-sample nextclade_dataset value)
    // consensus  : the consensus FASTAs of THIS group's samples only
    // datasets   : 1 dataset (non-segmented) or 3 (Oropouche L/M/S)
    // segmented  : true => split by segment (L/M/S) before running

    output:
    tuple val(gkey), path("nextclade_raw/*.tsv"), emit: tsv
    path 'versions.yml'                         , emit: versions

    script:
    def gsafe = gkey.toString().replaceAll('[^A-Za-z0-9]', '_')
    // For segmented genomes the consensus headers are ">sample|contig"; segments
    // are told apart by length (L ~6.8kb > M ~4.4kb > S ~0.9kb) which is robust
    // regardless of contig naming. Each segment is matched to its dataset dir
    // (staged as ds/L__*, ds/M__*, ds/S__*). Non-segmented runs use ds/ALL__*.
    """
    mkdir -p nextclade_raw
    cat consensus/*.consensus.fa consensus/*.fa 2>/dev/null | awk 'BEGIN{seen=0} /^>/{seen=1} seen' > all.fasta || true
    # (the two globs above tolerate either *.consensus.fa or *.fa staging names)

    if [ "${segmented}" = "true" ]; then
        # Split records into L/M/S by sequence length, then run each against its
        # dataset. Done in awk (the nextclade container has NO python3, only a
        # rust binary + coreutils). Header is reduced to the sample id (drops the
        # |contig suffix); segment is chosen by non-N length: L>=5000, M>=2500,
        # else S. Sequence re-wrapped at 70 columns.
        rm -f seg_L.fasta seg_M.fasta seg_S.fasta
        awk '
        /^>/ {
            if (name != "") emit()
            h = substr(\$0, 2); sub(/\\|.*/, "", h); name = h; seq = ""
            next
        }
        { seq = seq \$0 }
        END { if (name != "") emit() }
        function emit(   clean, L, seg, i) {
            clean = seq; gsub(/[Nn]/, "", clean); L = length(clean)
            if      (L >= 5000) seg = "L"
            else if (L >= 2500) seg = "M"
            else                seg = "S"
            f = "seg_" seg ".fasta"
            print ">" name >> f
            for (i = 1; i <= length(seq); i += 70) print substr(seq, i, 70) >> f
        }
        ' all.fasta

        for seg in L M S; do
            fa="seg_\${seg}.fasta"
            ds=\$(ls -d ds/\${seg}__* 2>/dev/null | head -1)
            if [ -s "\$fa" ] && [ -n "\$ds" ]; then
                nextclade run --input-dataset "\$ds" \\
                    --output-tsv "nextclade_raw/nextclade.${gsafe}.\${seg}.tsv" "\$fa" || true
            fi
        done
    else
        ds=\$(ls -d ds/ALL__* 2>/dev/null | head -1)
        if [ -s all.fasta ] && [ -n "\$ds" ]; then
            nextclade run --input-dataset "\$ds" \\
                --output-tsv "nextclade_raw/nextclade.${gsafe}.ALL.tsv" all.fasta || true
        fi
    fi

    # guard: ensure at least one output exists so the summary step has input
    ls nextclade_raw/*.tsv >/dev/null 2>&1 || echo -e "seqName" > nextclade_raw/nextclade.${gsafe}.EMPTY.tsv

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        nextclade: \$(nextclade --version | sed 's/nextclade //')
    END_VERSIONS
    """
}
