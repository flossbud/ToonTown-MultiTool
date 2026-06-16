#!/usr/bin/env bash
# verify_universal.sh <app>
# Acceptance gate: fail if ANY bundled Mach-O in the .app is not fat
# (x86_64 + arm64). Run after lipo_merge.sh and before sign.sh.
set -euo pipefail
APP="$1"
fail=0
while IFS= read -r -d '' f; do
  # Only Mach-O files; skip data/resources.
  if file "$f" | grep -q 'Mach-O'; then
    if ! lipo -verify_arch x86_64 arm64 "$f" 2>/dev/null; then
      echo "THIN: $f" >&2
      fail=1
    fi
  fi
done < <(find "$APP" -type f -print0)
if [ "$fail" -ne 0 ]; then
  echo "verify_universal: bundle contains thin Mach-O binaries" >&2
  exit 1
fi
echo "verify_universal: all Mach-O are x86_64+arm64 fat"
