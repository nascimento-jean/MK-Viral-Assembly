process SAMPLE_VALIDATION {
    tag "$meta.id"
    label 'process_single'

    input:
    val meta

    output:
    tuple val(meta), path('*.sample_validation.tsv'), emit: tsv
    path 'versions.yml'                              , emit: versions

    script:
    def issue = (meta.input_issue ?: '').toString().replace('\t', ' ').replace('\n', ' ')
    def fq1 = (meta.input_fastq_1 ?: '').toString().replace('\t', ' ')
    def fq2 = (meta.input_fastq_2 ?: '').toString().replace('\t', ' ')
    """
    printf 'sample\\tvirus\\tvdir\\tsample_role\\tis_negative_control\\tinput_status\\tinput_issue\\tfastq_1\\tfastq_2\\n' > ${meta.id}.sample_validation.tsv
    printf '%s\\t%s\\t%s\\t%s\\t%s\\t%s\\t%s\\t%s\\t%s\\n' \\
        '${meta.id}' \\
        '${meta.virus ?: ""}' \\
        '${meta.vdir ?: ""}' \\
        '${meta.sample_role ?: "sample"}' \\
        '${meta.is_control ? "true" : "false"}' \\
        '${meta.input_status ?: "unknown"}' \\
        '${issue}' \\
        '${fq1}' \\
        '${fq2}' >> ${meta.id}.sample_validation.tsv

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        shell: bash
    END_VERSIONS
    """
}
