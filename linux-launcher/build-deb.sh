#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
LAUNCHER_DIR="$ROOT/linux-launcher"
VERSION="${MKVA_VERSION:-1.2.1}"
ARCH="${MKVA_ARCH:-amd64}"
OUTPUT_DIR="${MKVA_OUTPUT_DIR:-$LAUNCHER_DIR/output}"
TMP_ROOT="${TMPDIR:-/tmp}"
STAGE="$(mktemp -d -p "$TMP_ROOT" mkva-deb-XXXXXX)"
PACKAGE_NAME="MK-Viral-Assembly-WebTool_${VERSION}_${ARCH}.deb"
PACKAGE_PATH="$OUTPUT_DIR/$PACKAGE_NAME"
chmod 0755 "$STAGE"

cleanup() {
  resolved="$(realpath -m "$STAGE")"
  expected="$(realpath -m "$TMP_ROOT")/mkva-deb-"
  case "$resolved" in
    "$expected"*) rm -rf -- "$resolved" ;;
    *) printf 'Refusing to remove unexpected staging path: %s\n' "$resolved" >&2 ;;
  esac
}
trap cleanup EXIT

command -v dpkg-deb >/dev/null || { echo "dpkg-deb is required." >&2; exit 1; }
[[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+([+~.-][0-9A-Za-z.-]+)?$ ]] || { echo "Invalid Debian version: $VERSION" >&2; exit 1; }
[[ "$ARCH" == "amd64" ]] || { echo "Only amd64 packages are currently supported." >&2; exit 1; }

install -d \
  "$STAGE/DEBIAN" \
  "$STAGE/opt/mk-viral-assembly" \
  "$STAGE/usr/bin" \
  "$STAGE/usr/share/applications" \
  "$STAGE/usr/share/icons/hicolor/scalable/apps" \
  "$STAGE/usr/share/doc/mk-viral-assembly-webtool" \
  "$OUTPUT_DIR"

sed "s/@VERSION@/$VERSION/g; s/@ARCH@/$ARCH/g" "$LAUNCHER_DIR/package/DEBIAN/control.in" > "$STAGE/DEBIAN/control"
install -m 0755 "$LAUNCHER_DIR/package/DEBIAN/postinst" "$STAGE/DEBIAN/postinst"
install -m 0755 "$LAUNCHER_DIR/package/DEBIAN/postrm" "$STAGE/DEBIAN/postrm"
install -m 0755 "$LAUNCHER_DIR/bootstrap-linux.sh" "$STAGE/opt/mk-viral-assembly/bootstrap-linux.sh"
install -m 0755 "$LAUNCHER_DIR/mkva-webtool" "$STAGE/opt/mk-viral-assembly/mkva-webtool"
install -m 0755 "$LAUNCHER_DIR/mkva-window" "$STAGE/opt/mk-viral-assembly/mkva-window"
sed "s/v1\.2\.1/v$VERSION/g" "$STAGE/opt/mk-viral-assembly/bootstrap-linux.sh" > "$STAGE/opt/mk-viral-assembly/bootstrap-linux.sh.tmp"
mv "$STAGE/opt/mk-viral-assembly/bootstrap-linux.sh.tmp" "$STAGE/opt/mk-viral-assembly/bootstrap-linux.sh"
chmod 0755 "$STAGE/opt/mk-viral-assembly/bootstrap-linux.sh"
sed "s/v1\.2\.1/v$VERSION/g" "$STAGE/opt/mk-viral-assembly/mkva-webtool" > "$STAGE/opt/mk-viral-assembly/mkva-webtool.tmp"
mv "$STAGE/opt/mk-viral-assembly/mkva-webtool.tmp" "$STAGE/opt/mk-viral-assembly/mkva-webtool"
chmod 0755 "$STAGE/opt/mk-viral-assembly/mkva-webtool"
ln -s /opt/mk-viral-assembly/mkva-webtool "$STAGE/usr/bin/mk-viral-assembly"
install -m 0644 "$LAUNCHER_DIR/package/usr/share/applications/mk-viral-assembly.desktop" "$STAGE/usr/share/applications/mk-viral-assembly.desktop"
install -m 0644 "$ROOT/webtool/public/favicon.svg" "$STAGE/usr/share/icons/hicolor/scalable/apps/mk-viral-assembly.svg"
install -m 0644 "$ROOT/LICENSE" "$STAGE/usr/share/doc/mk-viral-assembly-webtool/copyright"
install -m 0644 "$LAUNCHER_DIR/README.md" "$STAGE/usr/share/doc/mk-viral-assembly-webtool/README.md"

rm -f -- "$PACKAGE_PATH" "$PACKAGE_PATH.sha256"
dpkg-deb --root-owner-group --build "$STAGE" "$PACKAGE_PATH"
(
  cd "$OUTPUT_DIR"
  sha256sum "$PACKAGE_NAME" > "$PACKAGE_NAME.sha256"
)

dpkg-deb --info "$PACKAGE_PATH"
dpkg-deb --contents "$PACKAGE_PATH"
printf 'PACKAGE=%s\n' "$PACKAGE_PATH"
printf 'SHA256=%s\n' "$(cut -d' ' -f1 "$PACKAGE_PATH.sha256")"
