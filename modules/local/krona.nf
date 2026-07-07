process KRONA {
    tag "$vdir"
    label 'process_single'

    conda "bioconda::krona=2.8.1"
    container "quay.io/biocontainers/krona:2.8.1--pl5321hdfd78af_1"

    input:
    tuple val(vdir), path(krona_texts, stageAs: "krona_txt/*")

    output:
    tuple val(vdir), path("krona.html"), emit: html
    path 'versions.yml', emit: versions

    script:
    // ktImportText builds a self-contained interactive sunburst directly from
    // the <count>\\t<lineage...> text files (one per sample). No NCBI taxonomy
    // download required. Each input becomes one dataset in the Krona chart.
    """
    ktImportText -o krona.html krona_txt/*

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        krona: \$(ktImportText 2>&1 | grep -oP 'KronaTools \\K[0-9.]+' | head -1 || echo 2.8.1)
    END_VERSIONS
    """
}
