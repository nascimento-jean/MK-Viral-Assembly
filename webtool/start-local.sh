#!/usr/bin/env bash
set -euo pipefail

WEBTOOL_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$WEBTOOL_DIR")"
MARKER="$PROJECT_DIR/.mkva-managed-install"

if [[ -z "${MKVA_NODE_ENV_BIN:-}" ]]; then
  bases=()
  marker_base="$(sed -n 's/^conda_base=//p' "$MARKER" 2>/dev/null | head -n 1 || true)"
  [[ -n "$marker_base" ]] && bases+=("$marker_base")

  project_owner="$(stat -c %U "$PROJECT_DIR" 2>/dev/null || true)"
  project_home=""
  if [[ -n "$project_owner" ]] && command -v getent >/dev/null 2>&1; then
    project_home="$(getent passwd "$project_owner" | cut -d: -f6)"
  fi
  for home_dir in "$HOME" "$project_home"; do
    [[ -n "$home_dir" ]] || continue
    bases+=("$home_dir/miniforge3" "$home_dir/miniconda3" "$home_dir/anaconda3" "$home_dir/mambaforge")
  done

  for base in "${bases[@]}"; do
    if [[ -x "$base/envs/mkva-webtool/bin/node" && -x "$base/envs/mkva-webtool/bin/npm" ]]; then
      MKVA_NODE_ENV_BIN="$base/envs/mkva-webtool/bin"
      break
    fi
  done
fi
NODE_ENV_BIN="${MKVA_NODE_ENV_BIN:-}"

if [[ -z "$NODE_ENV_BIN" || ! -x "$NODE_ENV_BIN/node" || ! -x "$NODE_ENV_BIN/npm" ]]; then
  echo "Node.js da webtool não encontrado para o usuário $(id -un)." >&2
  echo "Reabra o instalador para reparar automaticamente o ambiente." >&2
  exit 21
fi

cd "$WEBTOOL_DIR"

CONDA_BASE="$(dirname "$(dirname "$(dirname "$NODE_ENV_BIN")")")"
export PATH="$NODE_ENV_BIN:$CONDA_BASE/bin:$PATH"
if [[ -z "${MKVA_NEXTFLOW:-}" && -x "$CONDA_BASE/envs/nextflow/bin/nextflow" ]]; then
  export MKVA_NEXTFLOW="$CONDA_BASE/envs/nextflow/bin/nextflow"
fi
if [[ -z "${MKVA_JAVA:-}" && -x "$CONDA_BASE/envs/nextflow/bin/java" ]]; then
  export MKVA_JAVA="$CONDA_BASE/envs/nextflow/bin/java"
fi
if [[ -z "${MKVA_NEXTFLOW:-}" || ! -x "$MKVA_NEXTFLOW" ]]; then
  echo "Nextflow não encontrado no ambiente gerenciado: $CONDA_BASE/envs/nextflow" >&2
  echo "Reabra o instalador para reparar automaticamente o ambiente." >&2
  exit 22
fi

http_ok() {
  python3 - "$1" <<'PY'
import sys
from urllib.request import ProxyHandler, build_opener

try:
    opener = build_opener(ProxyHandler({}))
    with opener.open(sys.argv[1], timeout=1) as response:
        raise SystemExit(0 if response.status == 200 else 1)
except Exception:
    raise SystemExit(1)
PY
}

cleanup() {
  if [[ -n "${API_PID:-}" ]]; then
    kill "$API_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

API_PID=""
if http_ok "http://127.0.0.1:8787/api/health"; then
  API_WAS_RUNNING=true
else
  python3 local_api.py &
  API_PID=$!
  API_WAS_RUNNING=false
fi

printf '
MK-Viral-Assembly Webtool
'
printf 'Interface: http://localhost:3000
'
printf 'API local: http://localhost:8787/api/health
'

if http_ok "http://127.0.0.1:3000"; then
  printf '
A WebTool já está ativa em http://localhost:3000
'
  printf 'Não foi iniciada uma segunda instância.
'
  if [[ "$API_WAS_RUNNING" == false ]]; then
    printf 'Use Ctrl+C para encerrar a API local.

'
    wait "$API_PID"
  fi
  exit 0
fi

printf 'Use Ctrl+C para encerrar.

'
if [[ -f "$WEBTOOL_DIR/../.mkva-managed-install" && -d "$WEBTOOL_DIR/dist" ]]; then
  PATH="$NODE_ENV_BIN:$PATH" "$NODE_ENV_BIN/npm" run start -- --host 127.0.0.1 --port 3000 --strictPort
else
  PATH="$NODE_ENV_BIN:$PATH" "$NODE_ENV_BIN/npm" run dev
fi