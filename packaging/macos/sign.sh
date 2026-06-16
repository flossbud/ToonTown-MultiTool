#!/usr/bin/env bash
# sign.sh <app>  — ad-hoc by default; Developer-ID-ready.
#
# Signs the .app INSIDE-OUT (nested Mach-O deepest-first, then framework bundles,
# then the bundle itself), with the hardened runtime ON even for ad-hoc so any
# hardened-runtime loading problem surfaces now (proven by the --self-check RUN,
# not by `codesign --verify`). Run AFTER every bundle mutation (lipo merge,
# _build_info.py, the .beta_flavor sentinel, Info.plist) — re-signing here is the
# authoritative pass, regardless of PyInstaller's own ad-hoc signature.
#
# Entitlements default to entitlements.plist next to this script (the hardened
# runtime needs disable-library-validation so the ad-hoc-signed Python framework
# loads). The SAME file is correct for notarization, so Developer ID just swaps
# the identity. To ship Developer ID + notarization later, override the env:
#   TTMT_CODESIGN_ID="Developer ID Application: ..."  (default: "-" ad-hoc)
#   TTMT_ENTITLEMENTS=/path/to/entitlements.plist     (default: ./entitlements.plist)
#   TTMT_CODESIGN_TIMESTAMP="--timestamp"             (default: --timestamp=none)
set -euo pipefail
APP="$1"
ID="${TTMT_CODESIGN_ID:--}"
TS="${TTMT_CODESIGN_TIMESTAMP:---timestamp=none}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENT_FILE="${TTMT_ENTITLEMENTS:-$SCRIPT_DIR/entitlements.plist}"
ENT_ARGS=()
[ -f "$ENT_FILE" ] && ENT_ARGS=(--entitlements "$ENT_FILE")

sign_one() {
  # ${ENT_ARGS[@]+"..."} expands to nothing when the array is empty; a bare
  # "${ENT_ARGS[@]}" errors under `set -u` on macOS's bash 3.2 when unset.
  codesign --force --options runtime "$TS" --sign "$ID" ${ENT_ARGS[@]+"${ENT_ARGS[@]}"} "$1"
}

# 1) Loose nested Mach-O (deepest first via reverse-depth sort), skipping files
#    inside .framework bundles (those are signed as bundles in step 2).
find "$APP" -type f -print0 \
  | while IFS= read -r -d '' f; do
      case "$f" in *.framework/*) continue ;; esac
      if file -b "$f" | grep -q 'Mach-O'; then printf '%s\0' "$f"; fi
    done \
  | awk 'BEGIN{RS="\0";ORS="\0"} {print length($0)"\t"$0}' | sort -rn | cut -f2- \
  | while IFS= read -r -d '' f; do sign_one "$f"; done

# 2) Framework bundles (sign the bundle, not its internal Mach-O).
find "$APP" -type d -name '*.framework' -print0 \
  | while IFS= read -r -d '' fw; do sign_one "$fw"; done

# 3) The app bundle last.
sign_one "$APP"

# Verify signatures (including nested). Loading-under-hardened-runtime is proven
# by the packaged --self-check RUN (test-macos.yml), NOT by this verify.
codesign --verify --deep --strict --verbose=2 "$APP"
echo "sign.sh: signed ($ID) and verified: $APP"
