#!/usr/bin/env bash
# build_dmg.sh <app> <out-dmg> <volume-name>
#
# Wraps the signed/merged .app in a compressed drag-to-Applications DMG.
# Run AFTER sign.sh (the .app must already be in its final, signed state).
set -euo pipefail
APP="$1"; OUT="$2"; VOL="$3"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
python3 -m pip install --quiet dmgbuild
TTMT_DMG_APP="$APP" TTMT_DMG_VOLNAME="$VOL" \
  python3 -m dmgbuild -s "$SCRIPT_DIR/dmg_settings.py" "$VOL" "$OUT"
echo "build_dmg: wrote $OUT"
