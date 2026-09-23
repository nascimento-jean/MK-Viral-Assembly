#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
LINUX="$ROOT/linux-launcher"
TEST_ROOT="$(mktemp -d -t mkva-launcher-tests-XXXXXX)"

cleanup() {
  resolved="$(realpath -m "$TEST_ROOT")"
  case "$resolved" in
    "${TMPDIR:-/tmp}"/mkva-launcher-tests-*) rm -rf -- "$resolved" ;;
    *) printf 'Refusing to remove unexpected test path: %s\n' "$resolved" >&2 ;;
  esac
}
trap cleanup EXIT

bash -n "$LINUX/bootstrap-linux.sh" "$LINUX/mkva-webtool" "$LINUX/build-deb.sh"
sh -n "$LINUX/package/DEBIAN/postinst" "$LINUX/package/DEBIAN/postrm"
MKVA_BOOTSTRAP_TEST=1 \
MKVA_RELEASE_REF=v1.2.0 \
MKVA_APP_DATA_DIR="$TEST_ROOT/bootstrap-data" \
"$LINUX/bootstrap-linux.sh" | grep -q '^MKVA_TARGET='
MKVA_LAUNCHER_TEST=1 \
MKVA_PACKAGE_DIR="$LINUX" \
MKVA_APP_DATA_DIR="$TEST_ROOT/launcher-data" \
MKVA_STATE_DIR="$TEST_ROOT/launcher-state" \
"$LINUX/mkva-webtool" | grep -q '^MKVA_PACKAGE_DIR='

grep -q '^Exec=/usr/bin/mk-viral-assembly$' "$LINUX/package/usr/share/applications/mk-viral-assembly.desktop"
grep -q 'zenity' "$LINUX/package/DEBIAN/control.in"
grep -q 'python3' "$LINUX/package/DEBIAN/control.in"
grep -q 'nohup setsid env' "$LINUX/mkva-webtool"
grep -q 'kill -TERM -- "-$pid"' "$LINUX/mkva-webtool"
grep -q 'User data.*intentionally preserved' "$LINUX/package/DEBIAN/postrm"

echo "Ubuntu launcher checks passed."
