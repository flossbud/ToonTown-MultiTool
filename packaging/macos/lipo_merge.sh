#!/usr/bin/env bash
# lipo_merge.sh <arm64-app> <x86_64-app> <out-app>
# Copies the arm64 .app to <out>, then replaces every Mach-O with a fat
# (arm64+x86_64) version lipo'd from the two source trees. Non-Mach-O files
# (resources, symlinks, plists) come from the arm64 tree unchanged.
#
# The arm64 tree is the base so symlinks/resources have one canonical source.
# Both source trees MUST be built with the same Python minor + pinned deps
# (see build_env.sh) so the trees are structurally identical before lipo.
set -euo pipefail
ARM="$1"; X86="$2"; OUT="$3"
rm -rf "$OUT"
cp -R "$ARM" "$OUT"
while IFS= read -r -d '' f; do
  rel="${f#"$OUT"/}"
  if file "$f" | grep -q 'Mach-O'; then
    x86f="$X86/$rel"
    if [ -f "$x86f" ]; then
      lipo -create "$f" "$x86f" -output "$f.fat" && mv "$f.fat" "$f"
    else
      echo "WARN: no x86_64 counterpart for $rel (left arm64-only)" >&2
    fi
  fi
done < <(find "$OUT" -type f -print0)
echo "lipo_merge: merged into $OUT"
