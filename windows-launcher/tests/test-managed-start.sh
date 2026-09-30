#!/usr/bin/env bash
set -euo pipefail

PROJECT="${MKVA_TEST_PROJECT:?MKVA_TEST_PROJECT is required}"
NODE_ENV_BIN="${MKVA_TEST_NODE_ENV_BIN:?MKVA_TEST_NODE_ENV_BIN is required}"
NEXTFLOW="${MKVA_TEST_NEXTFLOW:?MKVA_TEST_NEXTFLOW is required}"
JAVA="${MKVA_TEST_JAVA:?MKVA_TEST_JAVA is required}"
PICKER_DIR="${MKVA_TEST_PICKER_DIR:?MKVA_TEST_PICKER_DIR is required}"
MARKER="$PROJECT/.mkva-managed-install"
LOG="$(mktemp -t mkva-managed-start-XXXXXX.log)"
HAD_MARKER=0
BACKUP=""

if [[ -f "$MARKER" ]]; then
  HAD_MARKER=1
  BACKUP="$(mktemp -t mkva-managed-marker-XXXXXX)"
  cp -a "$MARKER" "$BACKUP"
fi

cleanup() {
  if [[ -n "${PID:-}" ]]; then
    kill -TERM -- "-$PID" 2>/dev/null || kill "$PID" 2>/dev/null || true
    wait "$PID" 2>/dev/null || true
  fi
  if [[ "$HAD_MARKER" == 1 ]]; then
    cp -a "$BACKUP" "$MARKER"
  else
    rm -f "$MARKER"
  fi
  rm -f "$BACKUP" "$LOG"
}
trap cleanup EXIT

for proc in /proc/[0-9]*; do
  cwd="$(readlink "$proc/cwd" 2>/dev/null || true)"
  case "$cwd" in
    "$PROJECT/webtool"|"$PROJECT/webtool/"*)
      kill -TERM "${proc##*/}" 2>/dev/null || true
      ;;
  esac
done
sleep 2

cat > "$MARKER" <<EOF
repository=test
release=v1.2.4
revision=startup-recovery-2026-09-30
EOF

export MKVA_PICKER_DIR="$PICKER_DIR"
export MKVA_NODE_ENV_BIN="$NODE_ENV_BIN"
export MKVA_NEXTFLOW="$NEXTFLOW"
export MKVA_JAVA="$JAVA"
export MKVA_DEFAULT_PROFILE=conda
cd "$PROJECT/webtool"
setsid ./start-local.sh >"$LOG" 2>&1 &
PID=$!

http_status() {
  python3 - "$1" <<'PY'
import sys
from urllib.request import ProxyHandler, build_opener
try:
    print(build_opener(ProxyHandler({})).open(sys.argv[1], timeout=1).status)
except Exception:
    print(0)
PY
}

for _ in $(seq 1 30); do
  if ! kill -0 "$PID" 2>/dev/null; then
    set +e
    wait "$PID"
    code=$?
    set -e
    printf 'PROCESS_EXIT=%s\n' "$code"
    cat "$LOG"
    exit 1
  fi
  api="$(http_status http://127.0.0.1:8787/api/health)"
  ui="$(http_status http://127.0.0.1:3000/)"
  if [[ "$api" == 200 && "$ui" == 200 ]]; then
    printf 'MANAGED_START_OK\n'
    cat "$LOG"
    exit 0
  fi
  sleep 1
done

printf 'MANAGED_START_TIMEOUT\n'
cat "$LOG"
exit 1
