#!/usr/bin/env bash
# Run TTMT from source. Auto-bootstraps a venv at ./.venv on first
# invocation and forwards any arguments to main.py.
#
# Usage:
#   ./run.sh              # launch the app
#   ./run.sh --debug      # any args after run.sh go to main.py

set -euo pipefail

cd "$(dirname "$0")"

VENV=".venv"
PYTHON_BIN="${TTMT_PYTHON:-python3.12}"
SENTINEL="$VENV/.requirements.sha"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
    cat >&2 <<EOF
run.sh: '$PYTHON_BIN' not found.

On Debian/Ubuntu/Mint:
  sudo apt install python3.12 python3.12-venv python3.12-dev

Or set TTMT_PYTHON to a different interpreter (3.10+):
  TTMT_PYTHON=python3.11 ./run.sh
EOF
    exit 1
fi

# Cheap fingerprint of requirements.txt so we re-install when it changes
# without forcing a full rebuild on every run.
REQ_HASH="$(sha256sum requirements.txt | awk '{print $1}')"

if [ ! -x "$VENV/bin/python" ] || [ ! -f "$SENTINEL" ] || [ "$(cat "$SENTINEL" 2>/dev/null)" != "$REQ_HASH" ]; then
    echo "run.sh: bootstrapping $VENV (this only happens when requirements.txt changes)…"
    if [ ! -x "$VENV/bin/python" ]; then
        "$PYTHON_BIN" -m venv "$VENV"
    fi
    "$VENV/bin/pip" install --upgrade pip --quiet
    # Keep pip's output visible on first bootstrap so install failures
    # surface the actual error. We only re-run pip when requirements.txt
    # changes (sentinel check above), so this noise is rare and useful.
    "$VENV/bin/pip" install -r requirements.txt
    echo "$REQ_HASH" > "$SENTINEL"
    echo "run.sh: bootstrap done."
fi

exec "$VENV/bin/python" main.py "$@"
