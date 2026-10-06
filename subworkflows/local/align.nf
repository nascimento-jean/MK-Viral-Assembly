/*
    ALIGN : index each unique reference once and map reads.
    Chooses bwa-mem or minimap2 based on params.aligner and produces a
    coordinate-sorted, indexed BAM together with the reference used.
*/

include { BWA_INDEX } from '../../modules/local/bwa_index'
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
        // Keep the original reference path as a stable join key. BWA_INDEX
        // receives each unique reference once, even in a large mixed run.
        ch_refs = reads
            .map { meta, sample_reads, reference -> [ reference.toString(), reference ] }
            .unique { ref_key, reference -> ref_key }
        BWA_INDEX ( ch_refs )

        ch_reads_keyed = reads
            .map { meta, sample_reads, reference ->
                [ reference.toString(), meta, sample_reads, reference ]
            }
        ch_indexes_keyed = BWA_INDEX.out.index
        // Each reference has one BWA index, but it may be shared by several samples.
        // combine(by: 0) broadcasts the matching index to every sample with that
        // reference key; join() would pair it with only one duplicate sample key.
        ch_bwa = ch_reads_keyed
            .combine(ch_indexes_keyed, by: 0)
            .map { ref_key, meta, sample_reads, original_reference, indexed_reference, index_files ->
                [ meta, sample_reads, indexed_reference, index_files ]
            }
        BWA_MEM ( ch_bwa )
        ch_bam = BWA_MEM.out.bam
    }

    emit:
    bam = ch_bam    // [ meta, bam, bai, reference ]
}
