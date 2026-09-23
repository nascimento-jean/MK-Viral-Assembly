#!/usr/bin/env bash
set -euo pipefail

WEBTOOL_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

if [[ -z "${MKVA_NODE_ENV_BIN:-}" ]]; then
  for base in "$HOME/miniforge3" "$HOME/miniconda3" "$HOME/anaconda3" "$HOME/mambaforge"; do
    if [[ -x "$base/envs/mkva-webtool/bin/npm" ]]; then
      MKVA_NODE_ENV_BIN="$base/envs/mkva-webtool/bin"
      break
    fi
  done
fi
NODE_ENV_BIN="${MKVA_NODE_ENV_BIN:-}"

if [[ -z "$NODE_ENV_BIN" || ! -x "$NODE_ENV_BIN/node" || ! -x "$NODE_ENV_BIN/npm" ]]; then
  echo "Node.js da webtool não encontrado em: $NODE_ENV_BIN" >&2
  echo "Crie o ambiente com: conda create -n mkva-webtool -c conda-forge nodejs=22" >&2
  exit 1
fi

cd "$WEBTOOL_DIR"

CONDA_BASE="$(dirname "$(dirname "$NODE_ENV_BIN")")"
export PATH="$NODE_ENV_BIN:$CONDA_BASE/bin:$PATH"
if [[ -z "${MKVA_NEXTFLOW:-}" && -x "$CONDA_BASE/envs/nextflow/bin/nextflow" ]]; then
  export MKVA_NEXTFLOW="$CONDA_BASE/envs/nextflow/bin/nextflow"
fi
if [[ -z "${MKVA_JAVA:-}" && -x "$CONDA_BASE/envs/nextflow/bin/java" ]]; then
  export MKVA_JAVA="$CONDA_BASE/envs/nextflow/bin/java"
fi

http_ok() {
  python3 - "$1" <<'PY'
import sys
from urllib.request import urlopen

try:
    with urlopen(sys.argv[1], timeout=1) as response:
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