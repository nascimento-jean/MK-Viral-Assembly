process GISAID_SUBMISSION {
    tag "$virus"
    label 'process_single'

    // The same pinned wheels are bundled for every execution profile, so the
    // process does not need internet access at analysis time.
    conda "conda-forge::python=3.10"
    container "${ workflow.containerEngine == 'singularity' ? 'https://depot.galaxyproject.org/singularity/python:3.10' : 'quay.io/biocontainers/python:3.10' }"

    input:
    tuple val(virus), path(metadata_xlsx), path(consensus_files, stageAs: "consensus/*")
    path templates_dir
    path wheels_dir

    output:
    tuple val(virus), path("${virus}_GISAID_submission.xls"),   emit: xls,   optional: true
    tuple val(virus), path("${virus}_GISAID_submission.fasta"), emit: fasta, optional: true
    path 'versions.yml', emit: versions

    script:
    """
    make_gisaid_submission.py \
        --metadata-xlsx ${metadata_xlsx} \
        --consensus-fasta consensus \
        --virus "${virus}" \
        --templates-dir ${templates_dir} \
        --vendor-dir ${wheels_dir} \
        --out-xls ${virus}_GISAID_submission.xls \
        --out-fasta ${virus}_GISAID_submission.fasta

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        python: \$(python --version | sed 's/Python //')
        xlrd: 2.0.1
        xlwt: 1.3.0
        xlutils: 2.0.0
    END_VERSIONS
    """
}
