#!/usr/bin/env bash
# verify_universal.sh <app>
# Acceptance gate: fail if ANY bundled Mach-O in the .app is not fat
# (x86_64 + arm64). Run after lipo_merge.sh and before sign.sh.
set -euo pipefail
APP="$1"
if [ ! -d "$APP" ]; then
  echo "verify_universal: no such app bundle: $APP" >&2
  exit 1
fi
fail=0
count=0
while IFS= read -r -d '' f; do
  # Only Mach-O files; skip data/resources.
  if file "$f" | grep -q 'Mach-O'; then
    count=$((count + 1))
    # lipo wants the input file FIRST, then the command: `lipo <file>
    # -verify_arch <arch>...`. The file must not come after -verify_arch or
    # lipo parses its path as an architecture flag and always errors.
    if ! lipo "$f" -verify_arch x86_64 arm64 2>/dev/null; then
      echo "THIN: $f" >&2
      fail=1
    fi
  fi
done < <(find "$APP" -type f -print0)
# Fail closed on a vacuous pass: zero Mach-O means a broken/empty bundle, not a
# universal one.
if [ "$count" -eq 0 ]; then
  echo "verify_universal: no Mach-O binaries found in $APP (broken bundle?)" >&2
  exit 1
fi
if [ "$fail" -ne 0 ]; then
  echo "verify_universal: bundle contains thin Mach-O binaries" >&2
  exit 1
fi
echo "verify_universal: all $count Mach-O are x86_64+arm64 fat"
