process BLAST_DB_PREP {
    label 'process_medium'

    conda "bioconda::blast=2.17.0 conda-forge::wget"
    container "quay.io/biocontainers/blast:2.17.0--h66d330f_0"

    // Persistent, run-scoped freshness: the DB lives in --blast_db_dir on the
    // host. We publish the built DB back there. cache:false so the age check
    // runs every execution (Nextflow can't wake on a timer; freshness is
    // enforced on the next run, as agreed).
    cache false
    publishDir "${params.blast_db_dir}", mode: 'copy'

    output:
    path "refseq_viral.*"      , emit: db,   optional: true
    path "refseq_build_date.txt", emit: date, optional: true
    path 'versions.yml'        , emit: versions

    script:
    def dbdir   = params.blast_db_dir
    def maxage  = params.blast_db_max_age_days
    """
    set -e
    DBDIR='${dbdir}'
    MARK="\$DBDIR/refseq_build_date.txt"
    NEED_BUILD=1

    if [ -f "\$MARK" ] && ls "\$DBDIR"/refseq_viral.n* >/dev/null 2>&1; then
        built=\$(cat "\$MARK" 2>/dev/null | head -1)
        now=\$(date +%s)
        # build date stored as epoch seconds
        age_days=\$(( ( now - built ) / 86400 ))
        if [ "\$age_days" -lt "${maxage}" ]; then
            echo "RefSeq viral BLAST DB is \$age_days day(s) old (< ${maxage}); reusing."
            NEED_BUILD=0
        else
            echo "RefSeq viral BLAST DB is \$age_days day(s) old (>= ${maxage}); rebuilding."
        fi
    else
        echo "No RefSeq viral BLAST DB found in \$DBDIR; building for the first time."
    fi

    if [ "\$NEED_BUILD" -eq 1 ]; then
        # Download RefSeq viral genomic FASTA from NCBI.
        # viral.N.1.genomic.fna.gz — N is small (currently just 1). Grab until a 404.
        #
        # NCBI's FTP server is frequently throttled to a few KB/s. The stock
        # busybox 'wget' in the blast biocontainer has NO throughput timeout,
        # NO retry and NO progress — so a slow server makes the process hang
        # silently at 0% forever. We therefore fetch with a hardened downloader:
        #   * resume interrupted transfers   (-C - / -c)
        #   * many retries with backoff
        #   * a THROUGHPUT floor: abort+retry a stalled connection instead of
        #     waiting hours on a near-dead socket
        # A helper picks curl if present, else wget, using whichever knobs exist.
        base="https://ftp.ncbi.nlm.nih.gov/refseq/release/viral"
        MINRATE=${params.blast_db_min_rate_bytes}   # bytes/s floor (default 1000)
        STALL=${params.blast_db_stall_seconds}       # seconds below floor -> abort+retry
        MAXTRIES=${params.blast_db_max_tries}

        fetch() {  # fetch <url> <outfile> ; returns 0 on success, 2 on 404, 1 on other fail
            _url="\$1"; _out="\$2"
            if command -v curl >/dev/null 2>&1; then
                curl -fL -C - --retry "\$MAXTRIES" --retry-delay 5 --retry-all-errors \\
                     --speed-limit "\$MINRATE" --speed-time "\$STALL" \\
                     -o "\$_out" "\$_url"
                rc=\$?
                [ "\$rc" -eq 22 ] && return 2   # curl -f: HTTP >=400 (e.g. 404)
                return \$rc
            else
                # busybox/GNU wget fallback: -c resume, timeout applies per-read stall
                i=0
                while [ "\$i" -lt "\$MAXTRIES" ]; do
                    wget -c --tries=1 --timeout="\$STALL" -O "\$_out" "\$_url" && return 0
                    # distinguish 404 from transient: HEAD-less, so probe size
                    i=\$((i+1)); echo "  retry \$i/\$MAXTRIES for \$_url"; sleep 5
                done
                return 1
            fi
        }

        n=1; got=0
        while [ "\$n" -le 20 ]; do
            url="\$base/viral.\${n}.1.genomic.fna.gz"
            echo ">> downloading viral.\${n}.1.genomic.fna.gz (server can be slow; floor \${MINRATE} B/s)"
            fetch "\$url" "viral.\${n}.fna.gz"; rc=\$?
            if [ "\$rc" -eq 0 ]; then
                echo "   ok: viral.\${n}.1.genomic.fna.gz"; got=1
            elif [ "\$rc" -eq 2 ]; then
                rm -f "viral.\${n}.fna.gz"; break   # 404 = no more parts
            else
                echo "ERROR: download of \$url failed after \$MAXTRIES tries (rc=\$rc)." >&2
                echo "       NCBI may be throttling. Pre-build the DB and point --blast_db_dir at it," >&2
                echo "       or re-run later. See README (BLAST species confirmation)." >&2
                exit 1
            fi
            n=\$((n+1))
        done
        if [ "\$got" -eq 0 ]; then
            echo "ERROR: could not download any RefSeq viral genomic file from NCBI." >&2
            exit 1
        fi
        cat viral.*.fna.gz > refseq_viral.fna.gz
        gunzip -f refseq_viral.fna.gz
        makeblastdb -in refseq_viral.fna -dbtype nucl -parse_seqids -title "RefSeq_viral" -out refseq_viral
        date +%s > refseq_build_date.txt
        rm -f viral.*.fna.gz refseq_viral.fna
    else
        # reuse: copy the cached DB into the work dir so downstream can find it
        cp "\$DBDIR"/refseq_viral.* .
        cp "\$MARK" refseq_build_date.txt
    fi

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        blast: \$(blastn -version | head -1 | sed 's/blastn: //')
    END_VERSIONS
    """
}
