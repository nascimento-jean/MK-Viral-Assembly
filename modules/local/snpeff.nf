process SNPEFF_ANNOTATE {
    tag "$meta.id"
    label 'process_medium'

    conda "bioconda::snpeff=5.2"
    container "${ workflow.containerEngine == 'singularity' ? 'https://depot.galaxyproject.org/singularity/snpeff:5.2--hdfd78af_0' : 'quay.io/biocontainers/snpeff:5.2--hdfd78af_0' }"

    input:
    tuple val(meta), path(vcf), path(reference), path(gff)

    output:
    tuple val(meta), path('*.snpeff.annotated.vcf'), path('*.snpeff.status.tsv'), emit: annotated
    path 'versions.yml', emit: versions

    script:
    def genome = "mkva_" + meta.id.toString().replaceAll('[^A-Za-z0-9_.-]', '_')
    """
    set +e
    export JAVA_TOOL_OPTIONS="-XX:-UsePerfData"
    mkdir -p data/${genome}
    cp ${reference} data/${genome}/sequences.fa
    cp ${gff} data/${genome}/genes.gff
    printf 'data.dir = ./data\n${genome}.genome : ${meta.id}\n' > snpEff.config

    status=OK
    message=
    if ! snpEff build -gff3 -noCheckCds -noCheckProtein -c snpEff.config ${genome} > snpeff_build.log 2>&1; then
        status=BUILD_FAILED
        message="SnpEff database build failed; see snpeff_build.log"
        cp ${vcf} ${meta.id}.snpeff.annotated.vcf
    elif ! snpEff ann -noStats -noLog -c snpEff.config ${genome} ${vcf} > ${meta.id}.snpeff.annotated.vcf 2> snpeff_annotate.log; then
        status=ANNOTATION_FAILED
        message="SnpEff annotation failed; see snpeff_annotate.log"
        cp ${vcf} ${meta.id}.snpeff.annotated.vcf
    fi
    awk 'BEGIN { FS=OFS="\\t" } /^#/ || NF >= 8 { print }' ${meta.id}.snpeff.annotated.vcf > ${meta.id}.snpeff.annotated.clean.vcf
    mv ${meta.id}.snpeff.annotated.clean.vcf ${meta.id}.snpeff.annotated.vcf
    printf '%s\t%s\n' "\$status" "\$message" > ${meta.id}.snpeff.status.tsv

    snpeff_version=\$(snpEff -version 2>&1 | head -n1 | sed 's/.*SnpEff //')
    printf '"${task.process}":\n    snpeff: %s\n' "\$snpeff_version" > versions.yml
    """
}

process SNPSIFT_FILTER {
    tag "$meta.id"
    label 'process_medium'

    conda "bioconda::snpsift=5.2"
    container "${ workflow.containerEngine == 'singularity' ? 'https://depot.galaxyproject.org/singularity/snpsift:5.2--hdfd78af_0' : 'quay.io/biocontainers/snpsift:5.2--hdfd78af_0' }"

    input:
    tuple val(meta), path(annotated_vcf), path(status_file)
    path helper

    output:
    tuple val(meta), path('*.snpeff.vcf'), emit: vcf
    tuple val(meta), path('*.snpeff.tsv'), emit: tsv
    path 'versions.yml', emit: versions

    script:
    """
    set +e
    export JAVA_TOOL_OPTIONS="-XX:-UsePerfData"
    status=\$(cut -f1 ${status_file})
    message=\$(cut -f2- ${status_file})

    if [ "\$status" = "OK" ]; then
        if ! SnpSift filter "(FILTER = 'PASS') | (FILTER = '.')" ${annotated_vcf} > ${meta.id}.snpeff.vcf 2> snpsift.log; then
            status=SNPSIFT_FAILED
            message="SnpSift filtering failed; unfiltered SnpEff VCF retained"
            cp ${annotated_vcf} ${meta.id}.snpeff.vcf
        fi
    else
        cp ${annotated_vcf} ${meta.id}.snpeff.vcf
    fi

    python3 ${helper} --sample ${meta.id} --vcf ${meta.id}.snpeff.vcf \
        --output ${meta.id}.snpeff.tsv --status "\$status" --message "\$message"

    snpsift_version=\$(SnpSift -version 2>&1 | head -n1 | sed 's/.*SnpSift //')
    printf '"${task.process}":\n    snpsift: %s\n' "\$snpsift_version" > versions.yml
    """
}
