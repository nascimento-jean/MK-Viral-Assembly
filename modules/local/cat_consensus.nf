process CAT_CONSENSUS {
    tag "$vdir"
    label 'process_single'

    conda "conda-forge::python=3.10"
    container "quay.io/biocontainers/python:3.10"

    input:
    tuple val(vdir), path(consensus_files, stageAs: "consensus/*"), path(qc_files, stageAs: "qc/*")

    output:
    tuple val(vdir), path("${vdir}_consensus*.fasta"), emit: fasta
    tuple val(vdir), path("excluded_samples*.txt")   , emit: excluded, optional: true
    path 'versions.yml'              , emit: versions

    script:
    def base_run = params.run_name ?: workflow.runName
    def run_name = "${base_run} — ${vdir}"
    def qc_arg   = qc_files ? "--qc-dir qc --pass ${params.dash_pass} --warn ${params.dash_warn} --min-status ${params.combine_min_status}" : ""
    """
    combine_consensus.py \\
        --indir consensus \\
        --run-name "${run_name}" \\
        --outdir . \\
        --prefix ${vdir}_consensus \\
        ${qc_arg}

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        python: \$(python --version | sed 's/Python //')
    END_VERSIONS
    """
}
