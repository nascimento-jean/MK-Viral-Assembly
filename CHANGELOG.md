# Changelog

All notable changes to MK-Viral-Assembly are recorded here. Changes under
**Unreleased** remain local until they pass command-line and WebTool validation.

## Unreleased

## 1.2.5 - 2026-10-06

- Separate the minimum read length, consensus frequency and variant frequency
  parameters (`--trim_min_len`, `--consensus_min_freq`, `--variant_min_freq`).
- Require Nextflow 24.04 or newer, matching the `resourceLimits` configuration.
- Report BLAST failures explicitly instead of silently producing an empty table.
- Follow Nextflow-staged consensus symlinks so BLAST receives every generated
  consensus in single-virus and mixed-virus runs.
- Match segmented consensus sequences to depth records by contig name.
- Support single-end Illumina rows in samplesheets and an explicit
  `sample_type` column for controls.
- Build each BWA reference index once per run and reuse it across samples.
- Add VCF output, amplicon coverage/dropout summaries and generic coding-region
  integrity checks when a GFF3 is available.
- Match versioned and unversioned accessions, such as `NC_001477.1` and
  `NC_001477`, when calculating amplicon coverage, while preserving exact and
  unambiguous contig matching.
- Add a machine-readable parameter schema and regression tests for the new
  outputs and mixed-virus metadata matching.
