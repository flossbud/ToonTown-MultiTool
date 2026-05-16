#!/usr/bin/env bash
#
# install.sh - ToonTown MultiTool dependency installer for Linux
#
# Detects your distro, installs system dependencies (Python 3.9 to 3.13
# and Qt6 runtime libraries) via sudo, creates a venv at ./venv, and
# installs the Python dependencies from requirements.txt.
#
# Usage:
#   ./install.sh                  Interactive install (prompts before each sudo)
#   ./install.sh --yes            Skip all confirmation prompts
#   ./install.sh --force          Wipe ./venv and redo everything
#   ./install.sh --skip-system-deps   Skip OS package detection (venv + pip only)
#   ./install.sh --help           Show this help

set -euo pipefail

# Resolve script directory so the script works regardless of cwd
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Parse args
ASSUME_YES=0
FORCE=0
SKIP_SYSTEM_DEPS=0

print_help() {
    sed -n '/^# Usage:/,/^$/p' "$0" | sed 's/^# //; s/^#//'
}

while [ $# -gt 0 ]; do
    case "$1" in
        --yes|-y)
            ASSUME_YES=1
            shift
            ;;
        --force)
            FORCE=1
            shift
            ;;
        --skip-system-deps)
            SKIP_SYSTEM_DEPS=1
            shift
            ;;
        --help|-h)
            print_help
            exit 0
            ;;
        *)
            echo "install.sh: unknown argument: $1" >&2
            echo "Try './install.sh --help'." >&2
            exit 1
            ;;
    esac
done

# OS detection: Linux only in v1
OS="$(uname -s)"
if [ "$OS" != "Linux" ]; then
    cat >&2 <<EOF
install.sh is for Linux. Detected: $OS

On Windows: powershell -ExecutionPolicy Bypass -File .\install.ps1
On macOS:   not supported yet (planned for v2)
EOF
    exit 1
fi

# Idempotency early-exit: if venv exists with matching requirements, skip everything
VENV_DIR="./venv"
SENTINEL="$VENV_DIR/.requirements.sha"

req_hash() {
    sha256sum requirements.txt | awk '{print $1}'
}

venv_python_version() {
    # Print "3.X" for the venv's Python, or empty string if missing
    if [ ! -x "$VENV_DIR/bin/python" ]; then
        return
    fi
    "$VENV_DIR/bin/python" -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")' 2>/dev/null || true
}

venv_python_in_range() {
    local v
    v="$(venv_python_version)"
    case "$v" in
        3.9|3.10|3.11|3.12|3.13) return 0 ;;
        *) return 1 ;;
    esac
}

if [ "$FORCE" -ne 1 ] \
    && [ -x "$VENV_DIR/bin/python" ] \
    && venv_python_in_range \
    && [ -f "$SENTINEL" ] \
    && [ "$(cat "$SENTINEL" 2>/dev/null)" = "$(req_hash)" ]; then
    echo "venv is already up to date."
    echo "Activate with: source venv/bin/activate"
    echo "         (or  source venv/bin/activate.fish for fish)"
    echo "Then run: python main.py"
    exit 0
fi

echo "install.sh: nothing-to-do check did not match; proceeding with install."
echo "(This stub will be extended in later tasks.)"
