#!/usr/bin/env nextflow
/*
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    viral-assembly : reference-based viral genome assembly from Illumina reads
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    Virus-agnostic consensus-genome pipeline. The reference genome is a
    parameter (global via --reference or per-sample via the samplesheet), so
    the same code works for SARS-CoV-2, Dengue, Chikungunya, Oropouche, RSV and
    any other RNA/DNA virus for which a reference FASTA is available.
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
*/

nextflow.enable.dsl = 2

/*
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    INPUT FASTQ VALIDATION HELPERS
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
*/

def _basename(obj) {
    def s = obj == null ? '' : obj.toString()
    return s.tokenize('/').last().tokenize('\\').last()
}

def _starts_with_cn(obj) {
    return _basename(obj).toUpperCase().startsWith('CN')
}

def is_negative_control(meta, reads) {
    // Negative controls are detected from the sample id and, as a fallback,
    // from the FASTQ filename prefix. Examples: CN, CN-Run01, CN_BUTANTAN.
    return _starts_with_cn(meta.id) || reads.any { r -> _starts_with_cn(r) }
}

def validate_fastq_gz(read_path) {
    def path_str = read_path.toString()
    def p = java.nio.file.Paths.get(path_str)
    if (!java.nio.file.Files.exists(p)) {
        return [ok: false, reason: 'missing_file']
    }
    def size = java.nio.file.Files.size(p)
    if (size == 0) {
        return [ok: false, reason: 'empty_file']
    }
    try {
        def input = java.nio.file.Files.newInputStream(p)
        def gzip = new java.util.zip.GZIPInputStream(input)
        def reader = new java.io.BufferedReader(new java.io.InputStreamReader(gzip))
        def l1 = reader.readLine()
        if (l1 == null) {
            reader.close()
            return [ok: false, reason: 'no_reads']
        }
        def l2 = reader.readLine()
        def l3 = reader.readLine()
        def l4 = reader.readLine()
        reader.close()
        if (l2 == null || l3 == null || l4 == null) {
            return [ok: false, reason: 'incomplete_fastq_record']
        }
        if (!l1.startsWith('@') || !l3.startsWith('+')) {
            return [ok: false, reason: 'invalid_fastq_format']
        }
        return [ok: true, reason: 'ok']
    } catch (java.util.zip.ZipException e) {
        return [ok: false, reason: 'invalid_gzip']
    } catch (java.io.EOFException e) {
        return [ok: false, reason: 'truncated_gzip']
    } catch (Exception e) {
        return [ok: false, reason: "unreadable_fastq:${e.getClass().getSimpleName()}"]
    }
}

def annotate_fastq_status(meta, reads, ref) {
    def r1 = validate_fastq_gz(reads[0])
    def r2 = validate_fastq_gz(reads[1])
    def ok = r1.ok && r2.ok
    def is_cn = is_negative_control(meta, reads)
    def issue = ok ? '' : "R1=${r1.reason};R2=${r2.reason}"
    def meta2 = meta + [
        is_control    : is_cn,
        sample_role   : is_cn ? 'negative_control' : 'sample',
        input_status  : ok ? 'valid' : 'skipped',
        input_issue   : issue,
        input_fastq_1 : reads[0].toString(),
        input_fastq_2 : reads[1].toString(),
    ]
    if (!ok) {
        log.warn "[viral-assembly] Skipping sample '${meta.id}' before processing: ${issue}"
    }
    return [ meta2, reads, ref ]
}

/*
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    HELP / PARAMETER SUMMARY
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
*/

def helpMessage() {
    log.info """
    ============================================================================
     viral-assembly  v${workflow.manifest.version}
    ============================================================================
    Usage:
      # with a samplesheet:
      nextflow run main.nf --input samplesheet.csv --reference ref.fasta \\
          -profile docker --outdir results

      # or point --input at a folder of FASTQs (samplesheet auto-built):
      nextflow run main.nf --input /path/to/fastqs/ --reference ref.fasta \\
          -profile docker --outdir results

    Mandatory:
      --input          EITHER a samplesheet CSV (columns:
                       sample,fastq_1,fastq_2[,reference])
                       OR a directory containing paired FASTQ files
                       (*_R1/_R2 or *_1/_2, .fastq.gz/.fq.gz) — the samplesheet
                       is then built automatically.
      --outdir         Output directory                        [default: ${params.outdir}]

    Reference (one of):
      --reference      Global reference FASTA used for every sample that does
                       not declare its own 'reference' column in the samplesheet.
      --gff            Global GFF3 (CDS features) for the reference. When set,
                       'ivar variants' annotates amino-acid changes and the
                       variants table gains an 'aa_change' column (e.g. S:N501Y).
                       Optional; per-sample override via a 'gff' samplesheet column.

    Amplicon options (optional):
      --primer_bed     BED file of primer coordinates. If set, primers are
                       soft/hard-clipped with 'ivar trim' before variant calling.

    Consensus / variant thresholds:
      --min_cov        Min coverage/depth to call a consensus base
                       (below -> N)                             [default: ${params.min_cov}]
                       (--min_depth is accepted as a deprecated alias)
      --min_freq       Min alt-allele freq for consensus        [default: ${params.min_freq}]
      --min_qual       Min base quality (ivar)                  [default: ${params.min_qual}]
      --min_map_qual   Min mapping quality (samtools/ivar)      [default: ${params.min_map_qual}]

    Optional steps:
      --kraken2_db     Path to a Kraken2 DB dir to run taxonomic screen (off by default)
      --skip_fastqc    Skip FastQC                              [default: ${params.skip_fastqc}]
      --skip_multiqc   Skip MultiQC                             [default: ${params.skip_multiqc}]
      --skip_dashboard Skip the HTML surveillance dashboard     [default: ${params.skip_dashboard}]
      --skip_combine   Skip run-level combined multi-FASTA(s)   [default: ${params.skip_combine}]
      --combine_min_status  Lowest QC status kept in combined FASTA: PASS|WARN|FAIL [default: ${params.combine_min_status}]
      --run_name       Label shown in the dashboard header      [default: Nextflow run name]
      --dash_pass      Min completeness for PASS badge          [default: ${params.dash_pass}]
      --dash_warn      Min completeness for WARN badge          [default: ${params.dash_warn}]
      --aligner        'bwa' or 'minimap2'                      [default: ${params.aligner}]

    Profiles (-profile):
      docker | singularity | conda | test
    ============================================================================
    """.stripIndent()
}

/*
    discover_fastqs : build the [ meta, [fq1, fq2], reference ] channel directly
    from a directory of paired FASTQ files (folder-input mode). Sample IDs are
    inferred from the filename up to the mate token. Supports _R1/_R2 and _1/_2
    with .fastq.gz / .fq.gz. A custom glob can be supplied via --fastq_pattern.
*/
def discover_fastqs(dir) {
    if (!params.reference) {
        error "Folder input mode requires a global --reference (there is no per-sample reference column)."
    }
    def ref = file(params.reference, checkIfExists: true)
    def pattern = params.fastq_pattern ?: "${dir}/*_{R1,R2,1,2}*.{fastq,fq}.gz"

    def ch = Channel.fromFilePairs(pattern, flat: false)
        .ifEmpty { error "No paired FASTQ files found in '${dir}' (looked for: ${pattern}). Provide a samplesheet or check --fastq_pattern." }
        .map { id, reads ->
            // strip a trailing mate/lane leftover token from the pair key
            def clean = id.replaceAll(/[._-]?(R?[12])$/, '').replaceAll(/_L?0*\d+$/, '')
            def vlabel = (params.virus ?: '').toString().trim()
            def vdir   = ( vlabel ?: 'unspecified_virus' ).toLowerCase().replaceAll('[^a-z0-9._-]', '_')
            def meta = [ id: (clean ?: id), single_end: false, virus: vlabel, vdir: vdir ]
            if (reads.size() != 2) {
                error "Sample '${id}' did not resolve to exactly 2 files: ${reads}. Use a samplesheet for this dataset."
            }
            [ meta, reads.sort(), ref ]
        }
    return ch
}

// Resolve --nextclade_dataset (a catalog name OR a short virus alias) into a
// list of [segment, dataset_name] pairs. Non-segmented viruses => one pair
// tagged 'ALL'; Oropouche => three pairs (L/M/S) using the 'tefe' datasets.
// A value containing '/' is treated as a literal catalog name (escape hatch).
def resolve_nextclade_datasets(value) {
    if (!value) { return [] }
    def v = value.toString().trim()
    def alias = v.toLowerCase()
    // segmented special case
    if (alias in ['oropouche', 'orov']) {
        return [
            ['L', 'community/itps/orov/L/tefe'],
            ['M', 'community/itps/orov/M/tefe'],
            ['S', 'community/itps/orov/S/tefe'],
        ]
    }
    def aliases = [
        'sars-cov-2' : 'nextstrain/sars-cov-2/wuhan-hu-1/orfs',
        'sarscov2'   : 'nextstrain/sars-cov-2/wuhan-hu-1/orfs',
        'covid'      : 'nextstrain/sars-cov-2/wuhan-hu-1/orfs',
        'dengue'     : 'nextstrain/dengue/all',
        'denv'       : 'nextstrain/dengue/all',
        'denv1'      : 'community/v-gen-lab/dengue/denv1',
        'denv-1'     : 'community/v-gen-lab/dengue/denv1',
        'denv2'      : 'community/v-gen-lab/dengue/denv2',
        'denv-2'     : 'community/v-gen-lab/dengue/denv2',
        'denv3'      : 'community/v-gen-lab/dengue/denv3',
        'denv-3'     : 'community/v-gen-lab/dengue/denv3',
        'denv4'      : 'community/v-gen-lab/dengue/denv4',
        'denv-4'     : 'community/v-gen-lab/dengue/denv4',
        'chikv'      : 'community/v-gen-lab/chikV/genotypes',
        'chikungunya': 'community/v-gen-lab/chikV/genotypes',
        'rsv-a'      : 'nextstrain/rsv/a/EPI_ISL_412866',
        'rsva'       : 'nextstrain/rsv/a/EPI_ISL_412866',
        'rsv-b'      : 'nextstrain/rsv/b/EPI_ISL_1653999',
        'rsvb'       : 'nextstrain/rsv/b/EPI_ISL_1653999',
        'zika'       : 'community/itps/zikav',
        'zikv'       : 'community/itps/zikav',
        'yellow-fever': 'nextstrain/yellow-fever/prM-E',
        'yfv'        : 'nextstrain/yellow-fever/prM-E',
    ]
    if (v.contains('/')) { return [['ALL', v]] }          // literal catalog name
    if (aliases.containsKey(alias)) { return [['ALL', aliases[alias]]] }
    // unknown short token: pass through as-is and let nextclade error clearly
    return [['ALL', v]]
}

/*
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    IMPORT SUBWORKFLOWS / MODULES
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
*/

include { INPUT_CHECK       } from './subworkflows/local/input_check'
include { FASTP             } from './modules/local/fastp'
include { FASTQC as FASTQC_RAW  } from './modules/local/fastqc'
include { FASTQC as FASTQC_TRIM } from './modules/local/fastqc'
include { KRAKEN2           } from './modules/local/kraken2'
include { HOST_DEPLETE      } from './modules/local/host_deplete'
include { KREPORT2KRONA     } from './modules/local/kreport2krona'
include { KRONA             } from './modules/local/krona'
include { KRONA as KRONA_VALIDATION } from './modules/local/krona'
include { TAXONOMY_SUMMARY  } from './modules/local/taxonomy_summary'
include { ALIGN             } from './subworkflows/local/align'
include { SAMPLE_VALIDATION } from './modules/local/sample_validation'
include { IVAR_TRIM         } from './modules/local/ivar_trim'
include { SAMTOOLS_STATS    } from './modules/local/samtools_stats'
include { IVAR_VARIANTS     } from './modules/local/ivar_variants'
include { ANNOTATE_AA       } from './modules/local/annotate_aa'
include { MIXED_SITES       } from './modules/local/mixed_sites'
include { IVAR_CONSENSUS    } from './modules/local/ivar_consensus'
include { CAT_CONSENSUS     } from './modules/local/cat_consensus'
include { CONSENSUS_QC      } from './modules/local/consensus_qc'
include { READ_STATS        } from './modules/local/read_stats'
include { NEXTCLADE_DATASET_GET } from './modules/local/nextclade_dataset'
include { NEXTCLADE_RUN     } from './modules/local/nextclade'
include { NEXTCLADE_SUMMARY } from './modules/local/nextclade_summary'
include { BLAST_DB_PREP     } from './modules/local/blast_db'
include { BLASTN_ID         } from './modules/local/blast_id'
include { BLAST_SUMMARY     } from './modules/local/blast_summary'
include { MULTIQC           } from './modules/local/multiqc'
include { DASHBOARD         } from './modules/local/dashboard'

/*
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    MAIN WORKFLOW
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
*/

workflow {

    if (params.help) {
        helpMessage()
        exit 0
    }
    if (!params.input) {
        error "You must provide --input (a samplesheet CSV or a folder of FASTQs). See --help."
    }

    // --min_depth is a deprecated alias of --min_cov; honour it with a warning
    if (params.min_depth != null) {
        log.warn "--min_depth is deprecated; using its value (${params.min_depth}) for --min_cov. Please switch to --min_cov."
        params.min_cov = params.min_depth
    }

    // Collect files for MultiQC
    ch_multiqc = Channel.empty()
    ch_versions = Channel.empty()

    //
    // Resolve --input: a samplesheet CSV, or a directory of FASTQ files.
    // -> ch_reads_raw : [ meta, [fq1, fq2], reference_fasta ]
    //
    def input_file = file(params.input, checkIfExists: true)

    // resolve global GFF / BED paths into a file or the NO_FILE sentinel
    def ch_no_file = file("${projectDir}/assets/NO_FILE", checkIfExists: true)
    def global_gff = params.gff ? file(params.gff, checkIfExists: true) : ch_no_file
    def global_bed = params.primer_bed ? file(params.primer_bed, checkIfExists: true) : ch_no_file
    def global_ncds = params.nextclade_dataset ?: ''

    if ( input_file.isDirectory() ) {
        log.info "[viral-assembly] --input is a directory: auto-discovering paired FASTQ files."
        ch_reads_raw = discover_fastqs( input_file )
        // folder mode has no per-sample columns -> use the global values for every sample
        ch_gff_raw   = ch_reads_raw.map { meta, reads, ref -> [ meta, global_gff ] }
        ch_bed_raw   = ch_reads_raw.map { meta, reads, ref -> [ meta, global_bed ] }
        ch_ncds_raw  = ch_reads_raw.map { meta, reads, ref -> [ meta, global_ncds ] }
    } else {
        INPUT_CHECK ( input_file )
        ch_reads_raw = INPUT_CHECK.out.reads
        ch_gff_raw   = INPUT_CHECK.out.gff
        ch_bed_raw   = INPUT_CHECK.out.bed
        ch_ncds_raw  = INPUT_CHECK.out.ncds
    }

    //
    // Validate input FASTQs before any tool consumes them. Empty/truncated/
    // unreadable pairs are reported and skipped so one bad sample does not
    // abort the whole run. Negative controls are auto-detected by CN* sample or
    // filename prefix and are carried only through the validation/QC/taxonomy
    // branch, not into consensus assembly.
    //
    ch_reads_all = ch_reads_raw.map { meta, reads, ref -> annotate_fastq_status(meta, reads, ref) }
    SAMPLE_VALIDATION ( ch_reads_all.map { meta, reads, ref -> meta } )

    ch_meta_all = ch_reads_all.map { meta, reads, ref -> [ meta.id, meta ] }
    ch_reads = ch_reads_all.filter { meta, reads, ref -> meta.input_status == 'valid' }

    // Re-key optional per-sample metadata with the augmented meta map. This keeps
    // downstream joins consistent after adding input_status/is_control fields.
    ch_gff  = ch_gff_raw.map  { meta, f -> [ meta.id, f ] }.join( ch_meta_all ).map { id, f, meta -> [ meta, f ] }
    ch_bed  = ch_bed_raw.map  { meta, f -> [ meta.id, f ] }.join( ch_meta_all ).map { id, f, meta -> [ meta, f ] }
    ch_ncds = ch_ncds_raw.map { meta, s -> [ meta.id, s ] }.join( ch_meta_all ).map { id, s, meta -> [ meta, s ] }

    //
    // Raw-read QC
    //
    if (!params.skip_fastqc) {
        FASTQC_RAW ( ch_reads.map { meta, reads, ref -> [ meta, reads ] } )
        ch_multiqc = ch_multiqc.mix( FASTQC_RAW.out.zip.map { it[1] } )
    }

    //
    // Adapter/quality trimming
    //
    FASTP ( ch_reads.map { meta, reads, ref -> [ meta, reads ] } )
    ch_multiqc = ch_multiqc.mix( FASTP.out.json.map { it[1] } )

    // re-attach the per-sample reference after trimming
    ch_trimmed = FASTP.out.reads.join( ch_reads.map { meta, reads, ref -> [ meta, ref ] } )
        // -> [ meta, trimmed_reads, reference ]

    if (!params.skip_fastqc) {
        FASTQC_TRIM ( ch_trimmed.map { meta, reads, ref -> [ meta, reads ] } )
        ch_multiqc = ch_multiqc.mix( FASTQC_TRIM.out.zip.map { it[1] } )
    }

    //
    // Optional taxonomic screen (contamination / co-infection check) and,
    // optionally, host-read depletion before alignment.
    //
    ch_taxonomy = Channel.empty()
    ch_krona    = Channel.empty()
    ch_align_in = ch_trimmed.filter { meta, reads, ref -> !meta.is_control }  // [ meta, reads, ref ]
    ch_dehost   = Channel.empty()                  // [ meta, dehosted_reads ] when depletion runs
    ch_validation_krona = Channel.empty()
    if (params.kraken2_db) {
        KRAKEN2 ( ch_trimmed.map { meta, reads, ref -> [ meta, reads ] }, file(params.kraken2_db, checkIfExists: true) )
        ch_multiqc = ch_multiqc.mix( KRAKEN2.out.report.map { it[1] } )

        // per-virus composition table (target/host/unclassified) for the dashboard
        TAXONOMY_SUMMARY ( KRAKEN2.out.report.map { meta, r -> [ meta.vdir, r ] }.groupTuple() )
        ch_taxonomy = TAXONOMY_SUMMARY.out.tsv        // [ vdir, tsv ]

        // interactive Krona sunburst from the Kraken2 reports (no NCBI taxonomy needed)
        KREPORT2KRONA ( KRAKEN2.out.report )
        KRONA ( KREPORT2KRONA.out.txt.map { meta, t -> [ meta.vdir, t ] }.groupTuple() )
        ch_krona = KRONA.out.html                      // [ vdir, html ]

        // Krona restricted to valid negative controls, used by the Run Validation tab.
        KRONA_VALIDATION (
            KREPORT2KRONA.out.txt
                .filter { meta, t -> meta.is_control }
                .map { meta, t -> [ meta.vdir, t ] }
                .groupTuple()
        )
        ch_validation_krona = KRONA_VALIDATION.out.html // [ vdir, html ]

        // optional: remove host reads before alignment
        if (params.deplete_host) {
            // join reads + kraken output + report by meta key into ONE channel
            // (separate queue inputs would be consumed positionally, not by key)
            ch_deplete_in = ch_trimmed
                                      .filter { meta, reads, ref -> !meta.is_control }
                                      .map { meta, reads, ref -> [ meta, reads ] }
                                      .join( KRAKEN2.out.output.filter { meta, f -> !meta.is_control } )
                                      .join( KRAKEN2.out.report.filter { meta, f -> !meta.is_control } )
            HOST_DEPLETE ( ch_deplete_in )
            ch_dehost = HOST_DEPLETE.out.reads
            // re-attach the per-sample reference to the dehosted reads
            ch_align_in = HOST_DEPLETE.out.reads.join( ch_trimmed.filter { meta, reads, ref -> !meta.is_control }
                                                               .map { meta, reads, ref -> [ meta, ref ] } )
                                                .map { meta, reads, ref -> [ meta, reads, ref ] }
        }
    }

    //
    // Map reads to the (per-sample) reference
    //
    ALIGN ( ch_align_in )
    ch_bam = ALIGN.out.bam    // [ meta, bam, bai, reference ]

    //
    // Optional amplicon primer trimming (per-sample BED).
    // Each sample carries its own primer BED (samplesheet 'bed_file' column, or
    // the global --primer_bed). Samples whose BED is the NO_FILE sentinel skip
    // trimming and pass through untouched, so a mixed run can trim CHIKV, DENV,
    // ... each with its own primer scheme while amplicon-free samples are spared.
    //
    ch_bam_bed = ch_bam.join( ch_bed )        // [ meta, bam, bai, reference, bed ]
        .branch { meta, bam, bai, ref, bed ->
            trim: bed.name != 'NO_FILE'
            keep: true
        }
    IVAR_TRIM ( ch_bam_bed.trim )             // input tuple includes the per-sample bed
    ch_bam_final = IVAR_TRIM.out.bam
        .mix( ch_bam_bed.keep.map { meta, bam, bai, ref, bed -> [ meta, bam, bai, ref ] } )

    //
    // Alignment statistics
    //
    SAMTOOLS_STATS ( ch_bam_final )
    ch_multiqc = ch_multiqc.mix( SAMTOOLS_STATS.out.stats.map { it[1] } )

    //
    // Variant calling and consensus generation (iVar)
    //
    // attach the per-sample GFF (or NO_FILE sentinel) to the BAM channel
    ch_bam_gff = ch_bam_final.join( ch_gff )   // [ meta, bam, bai, reference, gff ]
    IVAR_VARIANTS  ( ch_bam_gff )
    // amino-acid annotation runs in a Python container (the iVar image has no python)
    ANNOTATE_AA    ( IVAR_VARIANTS.out.tsv )

    // intra-sample heterozygosity screen (contamination / co-infection signal)
    ch_mixed = Channel.empty()
    if (!params.skip_mixed_sites) {
        MIXED_SITES ( ch_bam_final )
        ch_mixed = MIXED_SITES.out.tsv
    }

    IVAR_CONSENSUS ( ch_bam_final )

    //
    // Per-genome QC summary (coverage breadth, mean depth, N%, length)
    //
    CONSENSUS_QC ( IVAR_CONSENSUS.out.consensus.join( SAMTOOLS_STATS.out.depth ) )

    //
    // Per-sample read accounting for the dashboard: raw reads, reads surviving
    // fastp, and reads surviving host depletion (when --deplete_host is on).
    // fastp JSON carries raw+post-filter; dehosted FASTQs are counted directly.
    // Samples without depletion get the NO_FILE sentinel (read_stats.py skips it).
    //
    READ_STATS (
        FASTP.out.json.join( ch_dehost, remainder: true )
            .map { meta, json, dehost -> [ meta, json, dehost ?: ch_no_file ] }
    )
    ch_read_stats = READ_STATS.out.tsv         // [ meta, tsv ] — grouped per-virus at dashboard assembly

    //
    // Lineage / genotype typing with Nextclade (optional, downstream of consensus).
    // Runs once per run over all consensus genomes; segmented (Oropouche) runs the
    // L/M/S tefe trio. Dataset version is recorded for the report.
    //
    ch_nextclade = Channel.empty()
    if (params.nextclade) {
        // Per-sample Nextclade: each sample carries a dataset string (samplesheet
        // 'nextclade_dataset' or global --nextclade_dataset). Samples are grouped
        // by that string; each distinct virus/dataset is fetched once and run over
        // just its own consensus genomes. This lets one mixed run type CHIKV, DENV,
        // Oropouche, ... each against the right dataset.

        // [ vdir, consensus, ds_string ] — group key is the VIRUS (so DENV1/DENV2
        // land in separate folders even though both use the 'dengue' dataset),
        // carrying the per-sample dataset string; drop samples with no dataset.
        ch_cons_by_group = IVAR_CONSENSUS.out.consensus
            .join( ch_ncds )                                   // [ meta, consensus, ds_string ]
            .filter { meta, cons, ds -> ds && ds.toString().trim() }
            .map { meta, cons, ds -> [ meta.vdir, cons, ds ] } // [ vdir, consensus, ds_string ]

        // group the consensus genomes per virus -> [ vdir, [consensus...] ]
        ch_group_cons = ch_cons_by_group.map { vdir, cons, ds -> [ vdir, cons ] }.groupTuple()

        // distinct (virus, dataset) pairs -> expand each into its [seg, name] pairs,
        // tagged with the virus key so datasets route back to the right virus.
        ch_ds_specs = ch_cons_by_group
            .map { vdir, cons, ds -> [ vdir, ds ] }
            .unique()
            .flatMap { vdir, ds ->
                resolve_nextclade_datasets(ds).collect { seg, name -> [ vdir, seg, name ] }
            }                                                  // [ vdir, seg, name ]

        NEXTCLADE_DATASET_GET ( ch_ds_specs )

        // datasets per virus -> [ vdir, [ds_dirs...] ] ; segmented if >1 segment
        ch_group_ds = NEXTCLADE_DATASET_GET.out.dataset        // [ vdir, seg, ds_dir ]
            .map { vdir, seg, ds -> [ vdir, ds ] }
            .groupTuple()
            .map { vdir, dss -> [ vdir, dss, dss.size() > 1 ] } // [ vdir, [ds...], segmented ]

        // one run per virus: [ vdir, [consensus...], [ds...], segmented ]
        ch_nc_run_in = ch_group_cons.join( ch_group_ds )
            .map { vdir, cons, dss, segmented -> [ vdir, cons, dss, segmented ] }
        NEXTCLADE_RUN ( ch_nc_run_in )

        // one summary table per virus -> [ vdir, summary_tsv ]
        NEXTCLADE_SUMMARY ( NEXTCLADE_RUN.out.tsv )
        ch_nextclade = NEXTCLADE_SUMMARY.out.tsv               // [ vdir, tsv ]
    }

    //
    // Species confirmation of the assembled consensus with BLAST vs local RefSeq
    // viral (optional). The DB is (re)built on the host if missing or older than
    // --blast_db_max_age_days, then reused.
    //
    ch_blast = Channel.empty()
    if (params.blast_id) {
        BLAST_DB_PREP ()
        // one BLAST run per virus: group each virus' consensus genomes, reuse the DB
        ch_blast_cons = IVAR_CONSENSUS.out.consensus
            .map { meta, cons -> [ meta.vdir, cons ] }
            .groupTuple()                                      // [ vdir, [consensus...] ]
        BLASTN_ID (
            ch_blast_cons,
            BLAST_DB_PREP.out.db.collect(),
            BLAST_DB_PREP.out.date
        )
        BLAST_SUMMARY ( BLASTN_ID.out.raw )                    // [ vdir, blast_raw ] -> [ vdir, summary ]
        ch_blast = BLAST_SUMMARY.out.tsv                       // [ vdir, tsv ]
    }

    //
    // Aggregate all per-sample consensus genomes into run-level multi-FASTAs
    // (one general file + one per segment for segmented genomes). QC tables are
    // passed so FAIL samples are excluded from the combined FASTA(s).
    //
    if (!params.skip_combine) {
        // group each virus' consensus genomes + QC tables -> [ vdir, [cons...], [qc...] ]
        ch_cat_in = IVAR_CONSENSUS.out.consensus
            .join( CONSENSUS_QC.out.tsv )              // [ meta, consensus, qc ]
            .map { meta, cons, qc -> [ meta.vdir, cons, qc ] }
            .groupTuple()
        CAT_CONSENSUS ( ch_cat_in )
    }

    //
    // Aggregate report
    //
    if (!params.skip_multiqc) {
        MULTIQC (
            ch_multiqc.collect().ifEmpty([]),
            CONSENSUS_QC.out.tsv.map { it[1] }.collect().ifEmpty([]),
            file("$projectDir/assets/multiqc_config.yml", checkIfExists: false)
        )
    }

    //
    // Self-contained HTML surveillance dashboard (PASS/WARN/FAIL per sample,
    // per-segment breakdown, variant counts, inline charts)
    //
    if (!params.skip_dashboard) {
        // One dashboard per virus. Per-sample channels are grouped by meta.vdir;
        // the per-virus aggregate tables (taxonomy/krona/nextclade/blast) are already
        // keyed by vdir. Everything is joined on vdir with remainder:true so a virus
        // missing an optional input still emits a row; nulls collapse to [] (which
        // stageAs '<dir>/*' treats as "nothing staged", exactly like the old ifEmpty).
        ch_dash_qc    = CONSENSUS_QC.out.tsv.map { meta, f -> [ meta.vdir, f ] }.groupTuple()
        ch_dash_var   = ANNOTATE_AA.out.tsv.map  { meta, f -> [ meta.vdir, f ] }.groupTuple()
        ch_dash_mixed = ch_mixed.map             { meta, f -> [ meta.vdir, f ] }.groupTuple()
        ch_dash_reads = ch_read_stats.map        { meta, f -> [ meta.vdir, f ] }.groupTuple()
        ch_dash_validation = SAMPLE_VALIDATION.out.tsv.map { meta, f -> [ meta.vdir, f ] }.groupTuple()

        ch_dash_in = ch_dash_qc
            .join( ch_dash_var,   remainder: true )
            .join( ch_dash_mixed, remainder: true )
            .join( ch_taxonomy,   remainder: true )
            .join( ch_krona,      remainder: true )
            .join( ch_nextclade,  remainder: true )
            .join( ch_blast,      remainder: true )
            .join( ch_dash_reads, remainder: true )
            .join( ch_dash_validation, remainder: true )
            .join( ch_validation_krona, remainder: true )
            .map { row ->
                // row = [ vdir, qc[], var[], mixed[], taxonomy, krona, nextclade, blast, reads[], validation[], validation_krona ]
                def vdir = row[0]
                def vals = row[1..-1].collect { v -> v == null ? [] : v }
                [ vdir ] + vals
            }
        DASHBOARD ( ch_dash_in )
    }
}
