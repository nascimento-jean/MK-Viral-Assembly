process MULTIQC {
    label 'process_low'

    conda "bioconda::multiqc=1.21"
    container "quay.io/biocontainers/multiqc:1.21--pyhdfd78af_0"

    input:
    path(qc_files, stageAs: "qc/*")
    path(consensus_qc, stageAs: "consensus_qc/*")
    path(multiqc_config)

    output:
    path "*multiqc_report.html", emit: report
    path "multiqc_data"        , emit: data
    path 'versions.yml'        , emit: versions

    script:
    def config = multiqc_config ? "--config ${multiqc_config}" : ''
    """
    # combine the per-sample consensus QC tables into one for MultiQC custom content
    if ls consensus_qc/*.tsv >/dev/null 2>&1; then
        head -n1 \$(ls consensus_qc/*.tsv | head -n1) > consensus_qc_mqc.tsv
        for f in consensus_qc/*.tsv; do tail -n +2 \$f >> consensus_qc_mqc.tsv; done
    fi

    multiqc -f ${config} .

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        multiqc: \$(multiqc --version | sed 's/multiqc, version //')
    END_VERSIONS
    """
}
