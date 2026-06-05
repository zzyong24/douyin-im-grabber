#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PYTHON="${PYTHON:-$REPO_ROOT/.venv/bin/python}"

if [[ ! -x "$PYTHON" ]]; then
  PYTHON="${PYTHON_FALLBACK:-python3}"
fi

if ! "$PYTHON" -c "import requests, websocket" >/dev/null 2>&1; then
  echo "Missing Python deps. Run:"
  echo "  uv venv --python python3.11 .venv"
  echo "  uv pip install --python .venv/bin/python -r requirements.txt"
  exit 1
fi

cd "$REPO_ROOT"
exec env PYTHONPATH="$REPO_ROOT/src${PYTHONPATH:+:$PYTHONPATH}" \
  "$PYTHON" -m douyin_im_grabber.net_grab "$@"
