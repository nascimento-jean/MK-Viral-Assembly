process NEXTCLADE_DATASET_GET {
    tag "${seg}:${name}"
    label 'process_single'

    conda "bioconda::nextclade=3.21.2"
    container "quay.io/biocontainers/nextclade:3.21.2--h9ee0642_0"

    // Persistent cache: if the dataset dir already exists in this store, the
    // process is skipped and the cached copy reused. This is exactly the
    // "use local if present, else download the latest" behaviour requested.
    // The tag (or 'latest') is part of the stored dir name so pinning a new
    // --nextclade_tag triggers a fresh fetch instead of silently reusing.
    storeDir "${params.nextclade_datasets_dir}"

    input:
    tuple val(gkey), val(seg), val(name)

    // NOTE: the output MUST be the exact dataset dir name, never a glob like
    // "${seg}__*". storeDir decides whether to skip by matching the declared
    // outputs against the store; a glob "ALL__*" matches ANY previously cached
    // non-segmented dataset (e.g. CHIKV's ALL__...), so a later virus (SARS-CoV-2)
    // would be wrongly considered "already present", skipped, and silently
    // classified against the stale dataset. The full name keys each virus
    // uniquely so every dataset is fetched on first use.
    output:
    tuple val(gkey), val(seg), path("${seg}__${name.replaceAll('[^A-Za-z0-9]','_')}__${params.nextclade_tag ?: 'latest'}"), emit: dataset
    path 'versions.yml', emit: versions

    script:
    def tagopt   = params.nextclade_tag ? "--tag ${params.nextclade_tag}" : ""
    def tag_lbl  = params.nextclade_tag ?: "latest"
    def safename = name.replaceAll('[^A-Za-z0-9]', '_')
    def outdir   = "${seg}__${safename}__${tag_lbl}"
    """
    nextclade dataset get --name '${name}' ${tagopt} --output-dir '${outdir}'

    # Record the effective dataset version (from pathogen.json) so the report
    # can state exactly which dataset release classified each sample.
    # Shell-only parse: the nextclade container has NO python3. Best-effort grab
    # of the first "tag" field; falls back to the requested tag label.
    ver=""
    if [ -f '${outdir}/pathogen.json' ]; then
        ver=\$(grep -o '"tag"[[:space:]]*:[[:space:]]*"[^"]*"' '${outdir}/pathogen.json' | head -1 | sed 's/.*"tag"[[:space:]]*:[[:space:]]*"//; s/".*//')
    fi
    [ -n "\$ver" ] || ver='${tag_lbl}'
    printf '%s\\n' "\$ver" > '${outdir}/DATASET_VERSION.txt'

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        nextclade: \$(nextclade --version | sed 's/nextclade //')
    END_VERSIONS
    """
}
