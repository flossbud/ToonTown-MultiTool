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

# Sudo helper: print the command, prompt for confirmation (unless --yes),
# then run it. Exit 1 with a clean message on user decline or command failure.
run_sudo() {
    local cmd="$*"
    echo ""
    echo "The script will run:"
    echo "  sudo $cmd"
    if [ "$ASSUME_YES" -ne 1 ]; then
        printf 'Proceed? [y/N] '
        read -r reply
        case "$reply" in
            y|Y|yes|YES)
                ;;
            *)
                echo "Aborted. No changes were made." >&2
                exit 1
                ;;
        esac
    fi
    # shellcheck disable=SC2086
    if ! sudo $cmd; then
        echo "" >&2
        echo "Failed: sudo $cmd" >&2
        echo "See output above for details. You can fix the issue and re-run ./install.sh;" >&2
        echo "the idempotency check skips already-installed packages." >&2
        exit 1
    fi
}

# Resolve which packages need to be installed for the detected family.
# Echoes a list of package names; empty string means "nothing missing".
missing_python_packages() {
    case "$DISTRO_FAMILY" in
        debian)
            echo "python3.12 python3.12-venv python3.12-dev"
            ;;
        fedora)
            echo "python3.13"
            ;;
        arch)
            # Arch path is only reached when user has already installed a
            # supported Python via AUR/pyenv (Arch wart already gates this).
            echo ""
            ;;
    esac
}

missing_qt6_packages() {
    # Pre-check which packages are already installed; only echo the missing ones.
    case "$DISTRO_FAMILY" in
        debian)
            # Required runtime libs for PySide6 6.8.x on a minimal Debian/Ubuntu install
            local needed="libxcb-cursor0 libxkbcommon-x11-0 libegl1 libglib2.0-0"
            local missing=""
            for pkg in $needed; do
                if ! dpkg -s "$pkg" >/dev/null 2>&1; then
                    missing="$missing $pkg"
                fi
            done
            echo "$missing" | sed 's/^ //'
            ;;
        fedora)
            local needed="qt6-qtbase libxkbcommon-x11"
            local missing=""
            for pkg in $needed; do
                if ! rpm -q "$pkg" >/dev/null 2>&1; then
                    missing="$missing $pkg"
                fi
            done
            echo "$missing" | sed 's/^ //'
            ;;
        arch)
            local needed="qt6-base libxkbcommon-x11"
            local missing=""
            for pkg in $needed; do
                if ! pacman -Q "$pkg" >/dev/null 2>&1; then
                    missing="$missing $pkg"
                fi
            done
            echo "$missing" | sed 's/^ //'
            ;;
    esac
}

# Map a package-list to the install command for the current family
install_packages_cmd() {
    local pkgs="$*"
    case "$DISTRO_FAMILY" in
        debian) echo "apt install -y $pkgs" ;;
        fedora) echo "dnf install -y $pkgs" ;;
        arch)   echo "pacman -S --noconfirm $pkgs" ;;
    esac
}

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

    # System Python install (if missing)
    if [ -z "$PYTHON_BIN" ]; then
        py_pkgs="$(missing_python_packages)"
        if [ -n "$py_pkgs" ]; then
            echo ""
            echo "No supported Python (3.9 to 3.13) found."
            run_sudo "$(install_packages_cmd $py_pkgs)"
            # Re-detect Python after install
            PYTHON_BIN="$(find_supported_python || true)"
            if [ -z "$PYTHON_BIN" ]; then
                echo "Python install completed but no supported interpreter found on PATH." >&2
                echo "Aborting; please report this as a bug." >&2
                exit 1
            fi
            echo "Found supported Python: $PYTHON_BIN -> $(command -v "$PYTHON_BIN")"
        fi
    fi

    # Qt6 runtime libs install (if missing)
    qt_missing="$(missing_qt6_packages)"
    if [ -n "$qt_missing" ]; then
        echo ""
        echo "Missing Qt6 runtime libraries: $qt_missing"
        run_sudo "$(install_packages_cmd $qt_missing)"
    fi
fi

echo ""
echo "install.sh: system deps phase complete; venv + pip phase lands in Task 4."
