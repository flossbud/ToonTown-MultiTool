#!/usr/bin/env bash
# build_spike.sh <framework-python> <arch>  (arch = arm64 | x86_64)
# Makes an arch-pinned venv off the framework python, installs deps + PyInstaller,
# freezes the spike spec, ad-hoc-signs the .app under the hardened runtime with the
# PRODUCTION entitlements. Output: dist_spike_<arch>/Framework Spike.app
set -euo pipefail
PYBIN="$1"; ARCH="$2"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"   # repo root
RUN=(); [ "$ARCH" = "x86_64" ] && RUN=(arch -x86_64)
VENV="/tmp/ttmt_spike_${ARCH}"

rm -rf "$VENV"
${RUN[@]+"${RUN[@]}"} "$PYBIN" -m venv "$VENV"
${RUN[@]+"${RUN[@]}"} "$VENV/bin/python" -m pip install --quiet --upgrade pip
${RUN[@]+"${RUN[@]}"} "$VENV/bin/python" -m pip install --quiet -r "$ROOT/requirements.txt" pyinstaller
${RUN[@]+"${RUN[@]}"} "$VENV/bin/python" -m PyInstaller --noconfirm \
    --distpath "$ROOT/dist_spike_${ARCH}" --workpath "$ROOT/build_spike_${ARCH}" \
    "$ROOT/scripts/macos_framework_spike.spec"
APP="$ROOT/dist_spike_${ARCH}/Framework Spike.app"
bash "$ROOT/packaging/macos/sign.sh" "$APP"     # ad-hoc, hardened runtime, real entitlements
echo "BUILT: $APP"
