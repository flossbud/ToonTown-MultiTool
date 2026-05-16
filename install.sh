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
# shellcheck disable=SC2034  # consumed by run_sudo() in Task 3
ASSUME_YES=0
FORCE=0
# shellcheck disable=SC2034  # consumed by the SKIP_SYSTEM_DEPS gate in Task 2
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
    # Return empty silently if requirements.txt is missing, so the
    # idempotency check falls through to the proceed-with-install path
    # without printing a sha256sum error.
    [ -f requirements.txt ] || return 0
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

# Distro detection from /etc/os-release
if [ ! -f /etc/os-release ]; then
    echo "install.sh: /etc/os-release not found; cannot detect distro." >&2
    echo "Re-run with --skip-system-deps to skip OS-level detection:" >&2
    echo "  ./install.sh --skip-system-deps" >&2
    exit 1
fi

. /etc/os-release  # exports ID, ID_LIKE, PRETTY_NAME, etc.
DISTRO_ID="${ID:-unknown}"
DISTRO_LIKE="${ID_LIKE:-}"
DISTRO_PRETTY="${PRETTY_NAME:-$DISTRO_ID}"

# Map the detected distro to one of three families
DISTRO_FAMILY="unsupported"
case "$DISTRO_ID" in
    debian|ubuntu|linuxmint|pop|elementary)
        DISTRO_FAMILY="debian"
        ;;
    fedora)
        DISTRO_FAMILY="fedora"
        ;;
    arch|manjaro|endeavouros)
        DISTRO_FAMILY="arch"
        ;;
    *)
        # Fall back to ID_LIKE for derivatives we haven't enumerated
        for like in $DISTRO_LIKE; do
            case "$like" in
                debian|ubuntu)
                    DISTRO_FAMILY="debian"
                    break
                    ;;
                fedora|rhel)
                    DISTRO_FAMILY="fedora"
                    break
                    ;;
                arch)
                    DISTRO_FAMILY="arch"
                    break
                    ;;
            esac
        done
        ;;
esac

echo "Detected: $DISTRO_PRETTY"

# Supported Python detection: search PATH for python3.13 down to python3.9
find_supported_python() {
    local candidate
    for candidate in python3.13 python3.12 python3.11 python3.10 python3.9; do
        if command -v "$candidate" >/dev/null 2>&1; then
            echo "$candidate"
            return 0
        fi
    done
    return 1
}

PYTHON_BIN="$(find_supported_python || true)"

if [ -n "$PYTHON_BIN" ]; then
    echo "Found supported Python: $PYTHON_BIN -> $(command -v "$PYTHON_BIN")"
fi

# Arch wart: bail with hint if no supported Python on Arch
if [ "$DISTRO_FAMILY" = "arch" ] && [ -z "$PYTHON_BIN" ]; then
    cat >&2 <<EOF

Detected: Arch Linux
Arch ships Python 3.14 as default, which is not supported by PySide6 6.8.x.

To install a supported Python:
  AUR:    yay -S python313    (or paru, makepkg)
  pyenv:  pyenv install 3.13 && pyenv shell 3.13

After installing Python 3.13, re-run ./install.sh.

(Most Arch users should install the AUR package directly:
   yay -S toontown-multitool
 instead of running from source.)
EOF
    exit 1
fi

# Unsupported-distro bail (skipped when --skip-system-deps is passed)
if [ "$SKIP_SYSTEM_DEPS" -eq 0 ]; then
    if [ "$DISTRO_FAMILY" = "unsupported" ]; then
        cat >&2 <<EOF

Detected unsupported distro: $DISTRO_PRETTY

This installer does not have a package-manager mapping for your distro
yet. Please install dependencies manually using your distro's package
manager:
  - A Python interpreter in the 3.9 to 3.13 range
  - The Qt6 base runtime libraries (libxcb-*, libxkbcommon-x11, libegl1,
    libglib2.0-0 equivalents)

Then re-run with --skip-system-deps:
  ./install.sh --skip-system-deps

This skips OS package detection and just creates the venv and installs
the Python deps.
EOF
        exit 1
    fi
fi

echo "install.sh: detection complete (family=$DISTRO_FAMILY); next phase lands in Task 3."
