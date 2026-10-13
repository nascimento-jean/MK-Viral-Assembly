#!/usr/bin/env bash
set -euo pipefail
WEBTOOL_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$WEBTOOL_DIR")"
NODE_ENV_BIN="${MKVA_NODE_ENV_BIN:-}"
NEXTFLOW="${MKVA_NEXTFLOW:-}"
NF_TEST="${MKVA_NF_TEST:-}"
[[ -f "$PROJECT_DIR/main.nf" ]] || { echo "main.nf was not found." >&2; exit 10; }
[[ -x "$WEBTOOL_DIR/start-local.sh" ]] || { echo "start-local.sh is not executable." >&2; exit 11; }
[[ -n "$NODE_ENV_BIN" && -x "$NODE_ENV_BIN/node" && -x "$NODE_ENV_BIN/npm" ]] || { echo "The WebTool Node.js runtime is incomplete." >&2; exit 12; }
[[ -n "$NEXTFLOW" && -x "$NEXTFLOW" ]] || { echo "Nextflow was not found." >&2; exit 13; }
[[ -n "$NF_TEST" && -x "$NF_TEST" ]] || { echo "nf-test was not found." >&2; exit 14; }
python3 -m py_compile "$WEBTOOL_DIR/local_api.py"
PATH="$NODE_ENV_BIN:$PATH" "$NODE_ENV_BIN/node" --version
JAVA_CMD="${MKVA_JAVA:-java}" "$NEXTFLOW" -version >/dev/null
JAVA_HOME="$(dirname "$(dirname "${MKVA_JAVA:-$(command -v java)}")")" PATH="$(dirname "${MKVA_JAVA:-$(command -v java)}"):$PATH" "$NF_TEST" version >/dev/null
printf 'MK-Viral-Assembly WebTool installation: OK\n'
