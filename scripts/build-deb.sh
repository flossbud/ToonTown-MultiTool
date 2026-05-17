#!/usr/bin/env bash
# Build a .deb that wraps the PyInstaller Linux binary.
#
# The Python dependencies (PySide6, pynput, keyring, ...) are bundled inside
# the PyInstaller binary. The system Qt/GL/xcb runtime libraries are NOT
# bundled, so they are declared in the control file's Depends: field -- apt
# resolves them on `apt-get install ./TTMultiTool-*.deb`.
#
# Usage: scripts/build-deb.sh <binary-path> <version-label> [output-dir]
# Must be run from the repository root.
set -euo pipefail

BINARY="${1:?usage: build-deb.sh <binary-path> <version-label> [output-dir]}"
VERSION="${2:?usage: build-deb.sh <binary-path> <version-label> [output-dir]}"
OUTDIR="${3:-.}"

[ -f "$BINARY" ] || { echo "binary not found: $BINARY" >&2; exit 1; }

# Debian Version: field must not carry a leading 'v'; the CI 'dev' label is
# not a valid Debian version, so map it to a clearly-pre-release string.
DEB_VERSION="${VERSION#v}"
# dpkg: tilde sorts pre-release before stable; hyphen would be misread as a
# revision. The backslash before the tilde is load-bearing: bash performs
# tilde expansion on an UNESCAPED `~` in the replacement of ${var//pat/repl},
# so `${DEB_VERSION//-/~}` produced e.g. `2.3.0/home/runnera1` on CI.
DEB_VERSION="${DEB_VERSION//-/\~}"
[ "$DEB_VERSION" = "dev" ] && DEB_VERSION="0.0.0~dev"

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

install -Dm755 "$BINARY" "$STAGE/opt/toontown-multitool/ToonTownMultiTool"
mkdir -p "$STAGE/usr/bin"
ln -s /opt/toontown-multitool/ToonTownMultiTool "$STAGE/usr/bin/toontown-multitool"

install -Dm644 io.github.flossbud.ToonTownMultiTool.desktop \
    "$STAGE/usr/share/applications/io.github.flossbud.ToonTownMultiTool.desktop"

for sz in 48 64 128 256 512; do
    install -Dm644 "flatpak/icon-${sz}.png" \
        "$STAGE/usr/share/icons/hicolor/${sz}x${sz}/apps/io.github.flossbud.ToonTownMultiTool.png"
done

mkdir -p "$STAGE/DEBIAN"
cat > "$STAGE/DEBIAN/control" <<EOF
Package: toontown-multitool
Version: ${DEB_VERSION}
Architecture: amd64
Maintainer: flossbud <flossbud27@gmail.com>
Section: games
Priority: optional
Depends: libglib2.0-0, libgl1, libegl1, libdbus-1-3, libfontconfig1, libfreetype6, libx11-6, libx11-xcb1, libxext6, libxrender1, libxi6, libsm6, libice6, libxcb1, libxcb-cursor0, libxcb-glx0, libxcb-icccm4, libxcb-image0, libxcb-keysyms1, libxcb-randr0, libxcb-render-util0, libxcb-render0, libxcb-shape0, libxcb-shm0, libxcb-sync1, libxcb-util1, libxcb-xfixes0, libxcb-xinerama0, libxcb-xkb1, libxkbcommon0, libxkbcommon-x11-0
Description: Multitoon controller for Toontown Rewritten and Corporate Clash
 Multiboxing input control: launch and drive multiple Toontown clients,
 forward keystrokes, and keep background toons active. Python and Qt are
 bundled in the binary; this package depends only on the system GL/xcb stack.
EOF

OUTPUT="$OUTDIR/TTMultiTool-${VERSION}-Linux-x86_64.deb"
# -Zxz: Debian 11's dpkg 1.20 cannot read the zstd members modern
# dpkg-deb produces by default. xz is understood by every supported dpkg.
dpkg-deb --build --root-owner-group -Zxz "$STAGE" "$OUTPUT"
echo "built: $OUTPUT"
