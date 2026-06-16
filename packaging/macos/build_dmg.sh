#!/usr/bin/env bash
# build_dmg.sh <app> <out-dmg> <volume-name>
#
# Wraps the signed/merged .app in a compressed drag-to-Applications DMG.
# Run AFTER sign.sh (the .app must already be in its final, signed state).
set -euo pipefail
APP="$1"; OUT="$2"; VOL="$3"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Install dmgbuild in an isolated venv: a CI runner's system python3 is often
# externally managed (PEP 668), which refuses `pip install` into it. A venv is
# never externally managed, so this works on any host without polluting it.
VENV="$(mktemp -d)/dmgvenv"
python3 -m venv "$VENV"
"$VENV/bin/python" -m pip install --quiet dmgbuild
TTMT_DMG_APP="$APP" TTMT_DMG_VOLNAME="$VOL" \
  "$VENV/bin/python" -m dmgbuild -s "$SCRIPT_DIR/dmg_settings.py" "$VOL" "$OUT"
echo "build_dmg: wrote $OUT"
