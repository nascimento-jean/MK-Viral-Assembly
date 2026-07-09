process DASHBOARD {
    tag "$virus"
    label 'process_single'

    conda "conda-forge::python=3.10"
    container "quay.io/biocontainers/python:3.10"

    input:
    tuple val(virus),
          path(qc_files,       stageAs: "consensus_qc/*"),
          path(variant_files,  stageAs: "variants/*"),
          path(mixed_files,    stageAs: "mixed/*"),
          path(taxonomy_file,  stageAs: "taxonomy/*"),
          path(krona_file,     stageAs: "krona/*"),
          path(nextclade_file, stageAs: "nextclade/*"),
          path(blast_file,     stageAs: "blast/*"),
          path(readstat_files, stageAs: "read_stats/*"),
          path(validation_files, stageAs: "sample_validation/*"),
          path(validation_krona, stageAs: "validation_krona/*")

    output:
    tuple val(virus), path("${virus}_dashboard.html"), emit: html
    path 'versions.yml'  , emit: versions

    script:
    def base_run = params.run_name ?: workflow.runName
    def run_name = "${base_run} — ${virus}"
    def var_arg  = variant_files ? "--variants-dir variants" : ""
    def mix_arg  = mixed_files   ? "--mixed-dir mixed" : ""
    def tax_arg  = taxonomy_file ? "--taxonomy taxonomy/taxonomy_summary.tsv" : ""
    def krona_arg = krona_file   ? "--krona krona/krona.html" : ""
    def nc_arg   = nextclade_file ? "--nextclade nextclade/nextclade_summary.tsv" : ""
    def blast_arg = blast_file   ? "--blast blast/blast_summary.tsv" : ""
    def nc_tag   = params.nextclade_tag ?: 'latest'
    def nc_info  = nextclade_file ? "--nextclade-info \"${params.nextclade_dataset} @ ${nc_tag}\"" : ""
    def bl_info  = blast_file    ? "--blast-info \"RefSeq viral local (max ${params.blast_db_max_age_days} dias)\"" : ""
    def rs_arg   = readstat_files ? "--read-stats-dir read_stats" : ""
    def val_arg  = validation_files ? "--validation-dir sample_validation" : ""
    def val_krona_arg = validation_krona ? "--validation-krona validation_krona/krona.html" : ""
    """
    make_dashboard.py \\
        --qc-dir consensus_qc \\
        ${var_arg} \\
        ${mix_arg} \\
        ${tax_arg} \\
        ${krona_arg} \\
        ${nc_arg} \\
        ${blast_arg} \\
        ${nc_info} \\
        ${bl_info} \\
        ${rs_arg} \\
        ${val_arg} \\
        ${val_krona_arg} \\
        --out ${virus}_dashboard.html \\
        --run-name "${run_name}" \\
        --pass ${params.dash_pass} \\
        --warn ${params.dash_warn} \\
        --min-cov ${params.min_cov}

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        python: \$(python --version | sed 's/Python //')
    END_VERSIONS
    """
}
