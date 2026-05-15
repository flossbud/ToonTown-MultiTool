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

if [ ! -x "$VENV/bin/python" ] || [ ! -f "$SENTINEL" ] || [ "$(cat "$SENTINEL")" != "$REQ_HASH" ]; then
    echo "run.sh: bootstrapping $VENV (this only happens when requirements.txt changes)…"
    if [ ! -x "$VENV/bin/python" ]; then
        "$PYTHON_BIN" -m venv "$VENV"
    fi
    "$VENV/bin/pip" install --upgrade pip --quiet
    "$VENV/bin/pip" install --quiet -r requirements.txt
    echo "$REQ_HASH" > "$SENTINEL"
    echo "run.sh: bootstrap done."
fi

exec "$VENV/bin/python" main.py "$@"
