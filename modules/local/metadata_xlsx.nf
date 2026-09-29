process METADATA_XLSX {
    tag "$virus"
    label 'process_single'

    conda "conda-forge::python=3.10"
    container "${ workflow.containerEngine == 'singularity' ? 'https://depot.galaxyproject.org/singularity/python:3.10' : 'quay.io/biocontainers/python:3.10' }"

    input:
    tuple val(virus),
          path(qc_files,       stageAs: "consensus_qc/*"),
          path(readstat_files, stageAs: "read_stats/*"),
          path(nextclade_file, stageAs: "nextclade/*"),
          path(blast_file,     stageAs: "blast/*")
    path metadata

    output:
    tuple val(virus), path("metadata_${virus}.xlsx"), emit: xlsx
    path 'versions.yml'  , emit: versions

    script:
    def nc_arg = nextclade_file ? "--nextclade nextclade/nextclade_summary.tsv" : ""
    def blast_arg = blast_file ? "--blast blast/blast_summary.tsv" : ""
    def rs_arg = readstat_files ? "--read-stats-dir read_stats" : ""
    def sw_version = workflow.manifest.version ?: ''
    """
    make_metadata_xlsx.py \
        --metadata ${metadata} \
        --virus "${virus}" \
        --qc-dir consensus_qc \
        ${rs_arg} \
        ${nc_arg} \
        ${blast_arg} \
        --out metadata_${virus}.xlsx \
        --pass ${params.dash_pass} \
        --warn ${params.dash_warn} \
        --software-name "MK-Viral-Assembly" \
        --software-version "${sw_version}"

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        python: \$(python --version | sed 's/Python //')
    END_VERSIONS
    """
}