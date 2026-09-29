#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
TEST_ROOT="$(mktemp -d -t mkva-windows-bootstrap-tests-XXXXXX)"

cleanup() {
  resolved="$(realpath -m "$TEST_ROOT")"
  case "$resolved" in
    "${TMPDIR:-/tmp}"/mkva-windows-bootstrap-tests-*) rm -rf -- "$resolved" ;;
    *) printf 'Refusing to remove unexpected test path: %s\n' "$resolved" >&2 ;;
  esac
}
trap cleanup EXIT

source_root="$TEST_ROOT/source/MK-Viral-Assembly-vtest"
mkdir -p "$source_root/webtool"
printf 'nextflow.enable.dsl=2\n' > "$source_root/main.nf"
printf '#!/usr/bin/env bash\n' > "$source_root/webtool/start-local.sh"
printf '#!/usr/bin/env bash\n' > "$source_root/webtool/verify-install.sh"
printf 'updated\n' > "$source_root/release-file.txt"
chmod +x "$source_root/webtool/start-local.sh" "$source_root/webtool/verify-install.sh"

repository="$TEST_ROOT/repository"
mkdir -p "$repository/archive/refs/tags"
tar -czf "$repository/archive/refs/tags/vtest.tar.gz" -C "$TEST_ROOT/source" "MK-Viral-Assembly-vtest"

install="$TEST_ROOT/install"
mkdir -p "$install/webtool/.local-data" "$install/assets/blast_refseq_viral"
printf 'old\n' > "$install/main.nf"
printf '#!/usr/bin/env bash\n' > "$install/webtool/start-local.sh"
chmod +x "$install/webtool/start-local.sh"
printf 'repository=old\nrelease=vold\n' > "$install/.mkva-managed-install"
printf 'history\n' > "$install/webtool/.local-data/jobs.json"
printf 'database\n' > "$install/assets/blast_refseq_viral/refseq_viral.nsq"
printf 'obsolete\n' > "$install/webtool/native_picker.cs"

output="$(
  MKVA_REPOSITORY="file://$repository" \
  MKVA_RELEASE_REF=vtest \
  MKVA_INSTALL_DIR="$install" \
  MKVA_BOOTSTRAP_SOURCE_TEST=1 \
  bash "$ROOT/windows-launcher/bootstrap-wsl.sh"
)"

grep -q '^MKVA_TARGET=' <<<"$output"
grep -q '^updated$' "$install/release-file.txt"
grep -q '^history$' "$install/webtool/.local-data/jobs.json"
grep -q '^database$' "$install/assets/blast_refseq_viral/refseq_viral.nsq"
[[ ! -e "$install/webtool/native_picker.cs" ]]
