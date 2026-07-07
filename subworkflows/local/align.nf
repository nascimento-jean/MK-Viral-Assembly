/*
    ALIGN : index the reference and map paired reads.
    Chooses bwa-mem or minimap2 based on params.aligner and produces a
    coordinate-sorted, indexed BAM together with the reference used.
*/

include { BWA_MEM   } from '../../modules/local/bwa_mem'
include { MINIMAP2  } from '../../modules/local/minimap2'

workflow ALIGN {
    take:
    reads   // [ meta, [reads], reference ]

    main:
    if (params.aligner == 'minimap2') {
        MINIMAP2 ( reads )
        ch_bam = MINIMAP2.out.bam
    } else {
        BWA_MEM ( reads )
        ch_bam = BWA_MEM.out.bam
    }

    emit:
    bam = ch_bam    // [ meta, bam, bai, reference ]
}
