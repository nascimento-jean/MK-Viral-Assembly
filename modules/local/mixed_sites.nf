process MIXED_SITES {
    tag "$meta.id"
    label 'process_medium'

    conda "bioconda::ivar=1.4.3 bioconda::samtools=1.20"
    container "quay.io/biocontainers/ivar:1.4.3--h43eeafb_0"

    input:
    tuple val(meta), path(bam), path(bai), path(reference)

    output:
    tuple val(meta), path('*.mixed_sites.tsv'), emit: tsv
    path 'versions.yml'                        , emit: versions

    script:
    // Intra-sample heterozygosity screen: a low-frequency iVar pass (-t 0.03)
    // exposes minor alleles. Positions with good depth whose alternate allele
    // sits in an ambiguous band (min_het..max_het, default 0.20..0.80) are the
    // most sensitive signal of cross-sample contamination or co-infection.
    // LC_ALL=C on every awk: numeric locales (e.g. pt_BR) parse "0.40" as 0.
    def lo  = params.mixed_min_freq ?: 0.20
    def hi  = params.mixed_max_freq ?: 0.80
    """
    samtools faidx ${reference}

    # low-threshold variant call to expose minor alleles
    samtools mpileup -aa -A -d 0 -B -Q 0 --reference ${reference} \\
            -q ${params.min_map_qual} ${bam} \\
        | ivar variants -p ${meta.id}.lowfreq -r ${reference} \\
            -m ${params.min_cov} -q ${params.min_qual} -t 0.03

    # positions covered at >= min_cov (denominator for the mixed rate)
    covered=\$(samtools depth -a -q ${params.min_map_qual} ${bam} \\
        | LC_ALL=C awk -v m=${params.min_cov} '\$3>=m' | wc -l)

    # count ambiguous-frequency positions (header-aware; dedup by REGION+POS)
    LC_ALL=C awk -F'\\t' -v lo=${lo} -v hi=${hi} -v mc=${params.min_cov} '
        NR==1 { for (i=1;i<=NF;i++) h[\$i]=i; next }
        {
            fi=h["ALT_FREQ"]; di=h["TOTAL_DP"]; pi=h["PASS"]; ri=h["REGION"]; poi=h["POS"]
            freq=\$fi+0; dp=\$di+0; pass=\$pi
            if (dp>=mc && pass=="TRUE" && freq>=lo && freq<=hi) {
                key=\$ri":"\$poi
                if (!(key in seen)) { seen[key]=1; nmix++; if (freq>maxf) maxf=freq }
            }
        }
        END { print nmix+0, maxf+0 }
    ' ${meta.id}.lowfreq.tsv > _mix_counts.txt

    nmix=\$(cut -d' ' -f1 _mix_counts.txt)
    maxf=\$(cut -d' ' -f2 _mix_counts.txt)
    rate=\$(LC_ALL=C awk -v n=\$nmix -v c=\$covered 'BEGIN{ if(c>0) printf "%.4f", (n/c)*1000; else print "0.0000" }')

    printf 'sample\\tcovered_positions\\tn_mixed_sites\\tmixed_per_kb\\tmax_minor_freq\\n' >  ${meta.id}.mixed_sites.tsv
    printf '%s\\t%s\\t%s\\t%s\\t%s\\n' "${meta.id}" "\$covered" "\$nmix" "\$rate" "\$maxf"  >> ${meta.id}.mixed_sites.tsv

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        ivar: \$(ivar version | sed -n 's/iVar version //p')
        samtools: \$(samtools --version | head -n1 | sed 's/samtools //')
    END_VERSIONS
    """
}
