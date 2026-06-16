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
mkdir -p "$(dirname "$OUT")"
cp -R "$ARM" "$OUT"
has_arch() { lipo -archs "$1" 2>/dev/null | tr ' ' '\n' | grep -qx "$2"; }

while IFS= read -r -d '' f; do
  rel="${f#"$OUT"/}"
  if file "$f" | grep -q 'Mach-O'; then
    # Some deps ship a universal2 wheel (e.g. cryptography), so the arm-tree
    # file may already contain both slices. Re-lipo'ing two universal2 files
    # errors ("same architectures"), so leave an already-fat file as-is.
    if has_arch "$f" x86_64 && has_arch "$f" arm64; then
      continue
    fi
    x86f="$X86/$rel"
    if [ -f "$x86f" ]; then
      # The counterpart may itself be universal2; fuse only its x86_64 slice
      # onto the arm64 file so the result is exactly x86_64+arm64.
      slice="$x86f"
      if has_arch "$x86f" arm64; then
        slice="$(mktemp)"
        lipo "$x86f" -thin x86_64 -output "$slice"
      fi
      lipo -create "$f" "$slice" -output "$f.fat" && mv "$f.fat" "$f"
      [ "$slice" != "$x86f" ] && rm -f "$slice"
    else
      echo "WARN: no x86_64 counterpart for $rel (left arm64-only)" >&2
    fi
  fi
done < <(find "$OUT" -type f -print0)
echo "lipo_merge: merged into $OUT"
