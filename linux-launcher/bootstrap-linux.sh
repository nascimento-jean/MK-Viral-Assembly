#!/usr/bin/env bash
set -euo pipefail

REPOSITORY="${MKVA_REPOSITORY:-https://github.com/nascimento-jean/MK-Viral-Assembly}"
RELEASE_REF="${MKVA_RELEASE_REF:-v1.2.3}"
APP_DATA_DIR="${MKVA_APP_DATA_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/mk-viral-assembly}"
INSTALL_DIR="${MKVA_INSTALL_DIR:-$APP_DATA_DIR/source}"
MINIFORGE_DIR="${MKVA_CONDA_DIR:-$APP_DATA_DIR/miniforge3}"
NEXTFLOW_ENV="$APP_DATA_DIR/envs/nextflow"
WEBTOOL_ENV="$APP_DATA_DIR/envs/mkva-webtool"
WORK_DIR="$(mktemp -d -t mkva-linux-install-XXXXXX)"

cleanup() {
  case "$WORK_DIR" in
    "${TMPDIR:-/tmp}"/mkva-linux-install-*) rm -rf -- "$WORK_DIR" ;;
    *) printf 'Refusing to remove unexpected temporary path: %s\n' "$WORK_DIR" >&2 ;;
  esac
}
trap cleanup EXIT
status() { printf 'STATUS:%s\n' "$1"; }
fail() { printf 'ERROR:%s\n' "$1" >&2; exit 1; }

if [[ "${MKVA_BOOTSTRAP_TEST:-}" == "1" ]]; then
  command -v bash >/dev/null
  command -v python3 >/dev/null
  command -v tar >/dev/null
  [[ "$(uname -m)" == "x86_64" ]] || fail "This package currently supports x86-64 systems only."
  printf 'MKVA_TARGET=%s\n' "$INSTALL_DIR"
  printf 'MKVA_RELEASE=%s\n' "$RELEASE_REF"
  exit 0
fi

[[ "$(uname -m)" == "x86_64" ]] || fail "This installer currently supports Ubuntu x86-64 only."
command -v python3 >/dev/null || fail "Python 3 is required."
command -v tar >/dev/null || fail "The tar utility is required."
mkdir -p "$APP_DATA_DIR" "$APP_DATA_DIR/envs"

if [[ ! -f "$INSTALL_DIR/main.nf" || ! -x "$INSTALL_DIR/webtool/start-local.sh" ]]; then
  if [[ -e "$INSTALL_DIR" ]]; then
    fail "$INSTALL_DIR exists but is not a complete installation. Rename it and open the application again."
  fi
  status "Downloading MK-Viral-Assembly ${RELEASE_REF}..."
  archive="$WORK_DIR/mkva.tar.gz"
  if [[ "$RELEASE_REF" == v* ]]; then
    download_url="${REPOSITORY}/archive/refs/tags/${RELEASE_REF}.tar.gz"
  else
    download_url="${REPOSITORY}/archive/refs/heads/${RELEASE_REF}.tar.gz"
  fi
  python3 - "$download_url" "$archive" <<'PY'
import pathlib
import sys
import urllib.request

url, target = sys.argv[1:]
request = urllib.request.Request(url, headers={"User-Agent": "MK-Viral-Assembly-Ubuntu-Installer"})
with urllib.request.urlopen(request, timeout=300) as response, pathlib.Path(target).open("wb") as output:
    while block := response.read(1024 * 1024):
        output.write(block)
PY
  mkdir -p "$WORK_DIR/source"
  tar -xzf "$archive" -C "$WORK_DIR/source" --strip-components=1
  [[ -f "$WORK_DIR/source/main.nf" ]] || fail "The downloaded release is not a valid MK-Viral-Assembly package."
  chmod +x "$WORK_DIR/source/webtool/start-local.sh" "$WORK_DIR/source/webtool/verify-install.sh"
  mv "$WORK_DIR/source" "$INSTALL_DIR"
fi

if [[ ! -x "$MINIFORGE_DIR/bin/conda" ]]; then
  status "Installing the isolated package manager..."
  installer="$WORK_DIR/miniforge.sh"
  python3 - "$installer" <<'PY'
import pathlib
import sys
import urllib.request

url = "https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-x86_64.sh"
request = urllib.request.Request(url, headers={"User-Agent": "MK-Viral-Assembly-Ubuntu-Installer"})
with urllib.request.urlopen(request, timeout=300) as response, pathlib.Path(sys.argv[1]).open("wb") as output:
    while block := response.read(1024 * 1024):
        output.write(block)
PY
  bash "$installer" -b -p "$MINIFORGE_DIR"
fi

CONDA_EXE="$MINIFORGE_DIR/bin/conda"
status "Installing Nextflow and Java..."
if [[ ! -x "$NEXTFLOW_ENV/bin/nextflow" || ! -x "$NEXTFLOW_ENV/bin/java" ]]; then
  "$CONDA_EXE" create -y -p "$NEXTFLOW_ENV" -c conda-forge -c bioconda nextflow 'openjdk=17'
fi

status "Installing the WebTool runtime..."
if [[ ! -x "$WEBTOOL_ENV/bin/npm" || ! -x "$WEBTOOL_ENV/bin/node" ]]; then
  "$CONDA_EXE" create -y -p "$WEBTOOL_ENV" -c conda-forge 'nodejs=22'
fi

status "Preparing the graphical interface..."
(
  cd "$INSTALL_DIR/webtool"
  PATH="$WEBTOOL_ENV/bin:$PATH" "$WEBTOOL_ENV/bin/npm" ci --no-audit --no-fund
  PATH="$WEBTOOL_ENV/bin:$PATH" "$WEBTOOL_ENV/bin/npm" run build
)

status "Validating the installation..."
MKVA_NEXTFLOW="$NEXTFLOW_ENV/bin/nextflow" \
MKVA_JAVA="$NEXTFLOW_ENV/bin/java" \
MKVA_NODE_ENV_BIN="$WEBTOOL_ENV/bin" \
"$INSTALL_DIR/webtool/verify-install.sh"

cat > "$INSTALL_DIR/.mkva-managed-install" <<EOF
repository=$REPOSITORY
release=$RELEASE_REF
platform=ubuntu
installed_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)
EOF

"$CONDA_EXE" clean --all -y >/dev/null 2>&1 || true
PATH="$WEBTOOL_ENV/bin:$PATH" "$WEBTOOL_ENV/bin/npm" cache clean --force >/dev/null 2>&1 || true
printf 'MKVA_TARGET=%s\n' "$INSTALL_DIR"
status "Installation completed."
