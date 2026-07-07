/*
    INPUT_CHECK : parse the samplesheet into channels.
    Columns:  sample,fastq_1,fastq_2[,virus][,reference][,gff][,bed_file][,nextclade_dataset]
    - 'reference' optional; empty => global --reference.
    - 'gff' optional; empty => global --gff (may be none).
    - 'bed_file' optional; empty => global --primer_bed (may be none). Per-sample
      primer trimming lets a mixed run trim CHIKV, DENV, ... each with its own BED.
    - 'nextclade_dataset' optional; empty => global --nextclade_dataset. Per-sample
      typing lets a mixed run classify each virus against its own dataset.
    - 'virus' is informational (carried into meta for reporting).
*/

workflow INPUT_CHECK {
    take:
    samplesheet   // file: /path/to/samplesheet.csv

    main:
    Channel
        .fromPath(samplesheet)
        .splitCsv(header: true, strip: true)
        .multiMap { row ->
            reads: create_read_channel(row)
            gff:   create_gff_channel(row)
            bed:   create_bed_channel(row)
            ncds:  create_ncds_channel(row)
        }
        .set { parsed }

    emit:
    reads = parsed.reads   // [ meta, [ fastq_1, fastq_2 ], reference_fasta ]
    gff   = parsed.gff     // [ meta, gff_file_or_NO_FILE ]
    bed   = parsed.bed     // [ meta, bed_file_or_NO_FILE ]
    ncds  = parsed.ncds    // [ meta, nextclade_dataset_string ]  ('' when none)
}

// Sanitize a virus label into a safe subfolder name (lowercase, alnum/._- only).
// Empty label falls back to --virus, then to 'unspecified_virus'.
def vdir_of(String virus) {
    def s = (virus ?: '').toString().trim()
    if (!s) s = (params.virus ?: '').toString().trim()
    if (!s) s = 'unspecified_virus'
    return s.toLowerCase().replaceAll('[^a-z0-9._-]', '_')
}

def row_meta(LinkedHashMap row) {
    def meta = [:]
    meta.id         = row.sample
    meta.single_end = false
    meta.virus      = (row.virus && row.virus.trim()) ? row.virus.trim() : ''
    meta.vdir       = vdir_of(meta.virus)   // output subfolder name for this sample's virus
    return meta
}

// Build [ meta, gff ] from one samplesheet row (per-sample gff overrides global --gff)
def create_gff_channel(LinkedHashMap row) {
    def meta = row_meta(row)
    def gff_path = (row.gff && row.gff.trim()) ? row.gff.trim() : params.gff
    def gff = gff_path ? file(gff_path, checkIfExists: true)
                       : file("${projectDir}/assets/NO_FILE", checkIfExists: true)
    return [ meta, gff ]
}

// Build [ meta, bed ] from one samplesheet row (per-sample bed_file overrides --primer_bed)
def create_bed_channel(LinkedHashMap row) {
    def meta = row_meta(row)
    def bed_path = (row.bed_file && row.bed_file.trim()) ? row.bed_file.trim() : params.primer_bed
    def bed = bed_path ? file(bed_path, checkIfExists: true)
                       : file("${projectDir}/assets/NO_FILE", checkIfExists: true)
    return [ meta, bed ]
}

// Build [ meta, nextclade_dataset_string ] (per-sample overrides global --nextclade_dataset)
def create_ncds_channel(LinkedHashMap row) {
    def meta = row_meta(row)
    def ds = (row.nextclade_dataset && row.nextclade_dataset.trim()) ? row.nextclade_dataset.trim()
                                                                     : (params.nextclade_dataset ?: '')
    return [ meta, ds ]
}

// Build [ meta, [reads], reference ] from one samplesheet row
def create_read_channel(LinkedHashMap row) {

    if (!row.sample)  { error("ERROR: samplesheet row is missing a 'sample' value: ${row}") }
    if (!row.fastq_1) { error("ERROR: sample '${row.sample}' is missing 'fastq_1'") }
    if (!row.fastq_2) { error("ERROR: sample '${row.sample}' is missing 'fastq_2' (this pipeline expects paired-end reads)") }

    def meta = row_meta(row)

    def fq1 = file(row.fastq_1, checkIfExists: true)
    def fq2 = file(row.fastq_2, checkIfExists: true)

    // per-sample reference overrides the global one
    def ref_path = (row.reference && row.reference.trim()) ? row.reference.trim() : params.reference
    if (!ref_path) {
        error("ERROR: no reference for sample '${row.sample}'. Provide --reference or a 'reference' column in the samplesheet.")
    }
    def ref = file(ref_path, checkIfExists: true)

    return [ meta, [ fq1, fq2 ], ref ]
}
