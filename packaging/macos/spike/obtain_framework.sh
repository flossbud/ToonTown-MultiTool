#!/usr/bin/env bash
# obtain_framework.sh - download + SHA-verify + install the python.org universal2
# framework CPython, then print the absolute interpreter path. Idempotent: if the
# framework is already installed it just prints the path.
#
# Pin: PY_VER + PY_SHA256 may be overridden in the environment. The "macos11"
# installer is the UNIVERSAL2 (Intel + Apple Silicon) build.
set -euo pipefail
PY_VER="${PY_VER:-3.12.8}"
PKG="python-${PY_VER}-macos11.pkg"
URL="https://www.python.org/ftp/python/${PY_VER}/${PKG}"
# Pinned digest for python-3.12.8-macos11.pkg (see obtain_framework.sh history).
# Override PY_SHA256 if you bump PY_VER.
PY_SHA256="${PY_SHA256:-c411b5372d563532f5e6b589af7eb16e95613d61bd5af7bfe78563467130bbff}"
PY_MINOR="${PY_VER%.*}"                                   # 3.12.8 -> 3.12
DEST="/Library/Frameworks/Python.framework/Versions/${PY_MINOR}/bin/python${PY_MINOR}"

if [ -x "$DEST" ]; then echo "$DEST"; exit 0; fi
if [ "$PY_SHA256" = "PIN_ME" ]; then
  echo "PY_SHA256 not pinned - run the digest-resolution step or pass PY_SHA256=" >&2
  exit 2
fi

tmp="$(mktemp -d)"
curl -fsSL "$URL" -o "$tmp/$PKG"
echo "${PY_SHA256}  $tmp/$PKG" | shasum -a 256 -c -        # FAIL CLOSED on mismatch
pkgutil --check-signature "$tmp/$PKG" >/dev/null || { echo "pkg signature check failed" >&2; exit 1; }
echo "Installing $PKG (needs admin) ..." >&2
sudo installer -pkg "$tmp/$PKG" -target /
rm -rf "$tmp"
[ -x "$DEST" ] || { echo "framework python not at $DEST after install" >&2; exit 1; }
echo "$DEST"
