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
python3 -m py_compile "$LINUX/mkva-window"
MKVA_WINDOW_TEST=1 "$LINUX/mkva-window" | grep -q '^MKVA_WINDOW_URL=http://127.0.0.1:3000$'
sh -n "$LINUX/package/DEBIAN/postinst" "$LINUX/package/DEBIAN/postrm"
MKVA_BOOTSTRAP_TEST=1 \
MKVA_RELEASE_REF=v1.2.3 \
MKVA_APP_DATA_DIR="$TEST_ROOT/bootstrap-data" \
"$LINUX/bootstrap-linux.sh" | grep -q '^MKVA_TARGET='
MKVA_LAUNCHER_TEST=1 \
MKVA_PACKAGE_DIR="$LINUX" \
MKVA_APP_DATA_DIR="$TEST_ROOT/launcher-data" \
MKVA_STATE_DIR="$TEST_ROOT/launcher-state" \
"$LINUX/mkva-webtool" | grep -q '^MKVA_PACKAGE_DIR='

lock_output="$(
  MKVA_LAUNCHER_LOCK_TEST=1 \
  MKVA_LOCK_TEST_SECONDS=10 \
  MKVA_PACKAGE_DIR="$LINUX" \
  MKVA_APP_DATA_DIR="$TEST_ROOT/lock-data" \
  MKVA_STATE_DIR="$TEST_ROOT/lock-state" \
  "$LINUX/mkva-webtool"
)"
lock_child="${lock_output#MKVA_LOCK_TEST_CHILD=}"
[[ "$lock_child" =~ ^[0-9]+$ ]]
exec 8>"$TEST_ROOT/lock-state/launcher.lock"
flock -n 8
if [[ -e "/proc/$lock_child/fd/9" ]]; then
  echo "Background child inherited the launcher lock descriptor." >&2
  exit 1
fi
kill "$lock_child" 2>/dev/null || true

grep -q '^Exec=/usr/bin/mk-viral-assembly$' "$LINUX/package/usr/share/applications/mk-viral-assembly.desktop"
grep -q '^StartupWMClass=mk-viral-assembly$' "$LINUX/package/usr/share/applications/mk-viral-assembly.desktop"
grep -q 'zenity' "$LINUX/package/DEBIAN/control.in"
grep -q 'python3' "$LINUX/package/DEBIAN/control.in"
grep -q 'python3-gi' "$LINUX/package/DEBIAN/control.in"
grep -q 'gir1.2-webkit2-4.1' "$LINUX/package/DEBIAN/control.in"
grep -q 'nohup "$APP_WINDOW" "$url"' "$LINUX/mkva-webtool"
! grep -q 'xdg-open' "$LINUX/mkva-webtool"
grep -q 'nohup setsid env' "$LINUX/mkva-webtool"
grep -q 'kill -TERM -- "-$pid"' "$LINUX/mkva-webtool"
grep -q 'User data.*intentionally preserved' "$LINUX/package/DEBIAN/postrm"

echo "Ubuntu launcher checks passed."
