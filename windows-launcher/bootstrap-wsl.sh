#!/usr/bin/env bash
set -euo pipefail

REPOSITORY="${MKVA_REPOSITORY:-https://github.com/nascimento-jean/MK-Viral-Assembly}"
RELEASE_REF="${MKVA_RELEASE_REF:-main}"
INSTALL_DIR="${MKVA_INSTALL_DIR:-$HOME/MK-Viral-Assembly}"
MINIFORGE_DIR="${MKVA_CONDA_DIR:-$HOME/miniforge3}"
WORK_DIR="$(mktemp -d -t mkva-install-XXXXXX)"

cleanup() { rm -rf "$WORK_DIR"; }
trap cleanup EXIT
status() { printf 'STATUS:%s\n' "$1"; }
fail() { printf 'ERROR:%s\n' "$1" >&2; exit 1; }

if [[ "${MKVA_BOOTSTRAP_TEST:-}" == "1" ]]; then
  command -v bash >/dev/null
  command -v python3 >/dev/null
  command -v tar >/dev/null
  printf 'MKVA_TARGET=%s\n' "$INSTALL_DIR"
  exit 0
fi

command -v python3 >/dev/null || fail "Python 3 is required in the selected WSL distribution."
command -v tar >/dev/null || fail "The tar utility is required in the selected WSL distribution."

MARKER="$INSTALL_DIR/.mkva-managed-install"
INSTALLED_RELEASE=""
if [[ -f "$MARKER" ]]; then
  INSTALLED_RELEASE="$(sed -n 's/^release=//p' "$MARKER" | head -n 1)"
fi

NEEDS_SOURCE=0
if [[ ! -f "$INSTALL_DIR/main.nf" || ! -x "$INSTALL_DIR/webtool/start-local.sh" ]]; then
  if [[ -e "$INSTALL_DIR" && ! -f "$MARKER" ]]; then
    fail "$INSTALL_DIR already exists but is not a managed MK-Viral-Assembly installation. Move or rename it and retry."
  fi
  NEEDS_SOURCE=1
elif [[ -f "$MARKER" && "$INSTALLED_RELEASE" != "$RELEASE_REF" ]]; then
  NEEDS_SOURCE=1
fi

if [[ "$NEEDS_SOURCE" == "1" ]]; then
  status "Downloading MK-Viral-Assembly ${RELEASE_REF}..."
  ARCHIVE="$WORK_DIR/mkva.tar.gz"
  if [[ "$RELEASE_REF" == v* ]]; then
    DOWNLOAD_URL="${REPOSITORY}/archive/refs/tags/${RELEASE_REF}.tar.gz"
  else
    DOWNLOAD_URL="${REPOSITORY}/archive/refs/heads/${RELEASE_REF}.tar.gz"
  fi
  python3 - "$DOWNLOAD_URL" "$ARCHIVE" <<'PY_DOWNLOAD'
import pathlib, sys, urllib.request
url, target = sys.argv[1:]
request = urllib.request.Request(url, headers={"User-Agent": "MK-Viral-Assembly-Installer"})
with urllib.request.urlopen(request, timeout=120) as response, pathlib.Path(target).open("wb") as output:
    while block := response.read(1024 * 1024):
        output.write(block)
PY_DOWNLOAD
  mkdir -p "$WORK_DIR/source"
  tar -xzf "$ARCHIVE" -C "$WORK_DIR/source" --strip-components=1
  [[ -f "$WORK_DIR/source/main.nf" ]] || fail "The downloaded release is not a valid MK-Viral-Assembly package."
  chmod +x "$WORK_DIR/source/webtool/start-local.sh" "$WORK_DIR/source/webtool/verify-install.sh"
  if [[ -e "$INSTALL_DIR" ]]; then
    status "Updating the managed MK-Viral-Assembly installation..."
    cp -a "$WORK_DIR/source/." "$INSTALL_DIR/"
    rm -f "$INSTALL_DIR/webtool/native_picker.cs"
  else
    mv "$WORK_DIR/source" "$INSTALL_DIR"
  fi
fi

if [[ "${MKVA_BOOTSTRAP_SOURCE_TEST:-}" == "1" ]]; then
  printf 'MKVA_TARGET=%s\n' "$INSTALL_DIR"
  exit 0
fi

CONDA_EXE=""
for candidate in "$MINIFORGE_DIR/bin/conda" "$HOME/miniconda3/bin/conda" "$HOME/anaconda3/bin/conda" "$HOME/mambaforge/bin/conda"; do
  if [[ -x "$candidate" ]]; then CONDA_EXE="$candidate"; break; fi
done

if [[ -z "$CONDA_EXE" ]]; then
  status "Installing the isolated package manager..."
  INSTALLER="$WORK_DIR/miniforge.sh"
  python3 - "$INSTALLER" <<'PY'
import pathlib, sys, urllib.request
url = "https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-x86_64.sh"
request = urllib.request.Request(url, headers={"User-Agent": "MK-Viral-Assembly-Installer"})
with urllib.request.urlopen(request, timeout=120) as response, pathlib.Path(sys.argv[1]).open("wb") as output:
    while block := response.read(1024 * 1024):
        output.write(block)
PY
  bash "$INSTALLER" -b -p "$MINIFORGE_DIR"
  CONDA_EXE="$MINIFORGE_DIR/bin/conda"
fi

CONDA_BASE="$(dirname "$(dirname "$CONDA_EXE")")"
status "Installing Nextflow and Java..."
if [[ ! -x "$CONDA_BASE/envs/nextflow/bin/nextflow" ]]; then
  "$CONDA_EXE" create -y -n nextflow -c conda-forge -c bioconda nextflow 'openjdk=17'
fi
status "Installing the WebTool runtime..."
if [[ ! -x "$CONDA_BASE/envs/mkva-webtool/bin/npm" ]]; then
  "$CONDA_EXE" create -y -n mkva-webtool -c conda-forge 'nodejs=22'
fi

NODE_BIN="$CONDA_BASE/envs/mkva-webtool/bin"
status "Preparing the WebTool interface..."
(
  cd "$INSTALL_DIR/webtool"
  PATH="$NODE_BIN:$PATH" "$NODE_BIN/npm" ci --no-audit --no-fund
  PATH="$NODE_BIN:$PATH" "$NODE_BIN/npm" run build
)
status "Validating the installation..."
MKVA_NEXTFLOW="$CONDA_BASE/envs/nextflow/bin/nextflow" MKVA_JAVA="$CONDA_BASE/envs/nextflow/bin/java" MKVA_NODE_ENV_BIN="$NODE_BIN" "$INSTALL_DIR/webtool/verify-install.sh"

cat > "$INSTALL_DIR/.mkva-managed-install" <<EOF
repository=$REPOSITORY
release=$RELEASE_REF
installed_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)
EOF
"$CONDA_EXE" clean --all -y >/dev/null 2>&1 || true
PATH="$NODE_BIN:$PATH" "$NODE_BIN/npm" cache clean --force >/dev/null 2>&1 || true
printf 'MKVA_TARGET=%s\n' "$INSTALL_DIR"
status "Installation completed."
