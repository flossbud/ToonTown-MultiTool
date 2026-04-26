---
name: release
description: "Cut a versioned release of ToonTown MultiTool. Bumps version strings, drafts release notes from commits since the last tag, runs a strict contributor scan that hard-blocks on any Claude / Anthropic / GPT / LLM / Codex / Co-Authored-By leak, then on user confirmation commits, tags, pushes main, pushes the tag (which triggers CI builds for Windows EXE + Linux AppImage + Flatpak), and bumps the AUR PKGBUILD. Hybrid flow: prep work runs automatically, then a single \"ready to ship?\" prompt gates all destructive actions."
---

# `/release`

Run with `/release <version-or-bump>`:

- Literal version: `/release 2.0.4`
- Bump keyword: `/release patch` | `/release minor` | `/release major`

Print a clear marker before each phase: `▸ Phase N: <name>`.

NEVER add `Co-Authored-By:` (or any Claude / Anthropic / LLM attribution) to any commit message, file, or note. The contributor scan in Phase 6 will catch this; do not let it.

---

## Phase 1: Parse argument

The argument is the literal text following `/release`. Determine the new version:

1. If it matches `^\d+\.\d+\.\d+$`, use it as `NEW_VERSION` directly.

2. If it is `patch`, `minor`, or `major`, read the latest tag and bump:

   ```bash
   LATEST_TAG=$(git tag --list 'v[0-9]*.[0-9]*.[0-9]*' --sort=-v:refname | head -1)
   ```

   Strip the leading `v`, split on `.`, bump the requested component, zero the lower components:
   - `patch`: `2.0.3` → `2.0.4`
   - `minor`: `2.0.3` → `2.1.0`
   - `major`: `2.0.3` → `3.0.0`

3. Otherwise, abort with the message: `Usage: /release <X.Y.Z | patch | minor | major>`.

Set these variables for use in later phases:
- `NEW_VERSION` (e.g. `2.0.4`)
- `NEW_TAG` = `v$NEW_VERSION`
- `LATEST_TAG` (already set above; will also serve as the diff base)

---

## Phase 2: Pre-flight checks

### Hard-blocks (abort immediately on any failure)

1. **Working tree clean (excluding untracked):**
   ```bash
   git status --porcelain | grep -v '^??'
   ```
   If non-empty, abort and list the dirty files. Untracked files are allowed because `.codex/` and `docs/superpowers/` live there.

2. **On main:**
   ```bash
   git rev-parse --abbrev-ref HEAD
   ```
   Must equal `main`. Otherwise abort with the current branch name.

3. **Commits exist since last tag:**
   ```bash
   git log "${LATEST_TAG}..HEAD" --oneline | head -1
   ```
   If empty, abort with `Nothing to release since ${LATEST_TAG}`.

4. **AUR repo present and clean:**
   ```bash
   AUR_PATH=/home/jaret/Projects/aur-toontown-multitool
   [ -d "$AUR_PATH/.git" ] || abort "AUR repo not found at $AUR_PATH"
   git -C "$AUR_PATH" status --porcelain
   ```
   If status output is non-empty, abort.

### Soft-warns (proceed only with explicit confirmation)

5. **Tests:**
   ```bash
   pytest tests/ -q
   ```
   If exit code is non-zero, print the failing test count and ask:
   `Tests are failing. Proceed anyway? [y/N]`
   Accept only `y`, `Y`, or `yes` (case-insensitive). Anything else aborts.

---

## Phase 3: Bump version strings

Read the current version from `main.py` to use in the AUR `.SRCINFO` substitution later:

```bash
OLD_VERSION=$(grep -oP 'APP_VERSION = "\K[^"]+' main.py)
```

Edit three files in place:

1. `main.py`: replace `APP_VERSION = "$OLD_VERSION"` with `APP_VERSION = "$NEW_VERSION"`.
2. `services/cc_login_service.py`: replace `"User-Agent": "ToontownMultiTool/$OLD_VERSION"` with `"User-Agent": "ToontownMultiTool/$NEW_VERSION"`.
3. `services/ttr_login_service.py`: same replacement as `cc_login_service.py`.

After editing, verify exactly three lines changed:

```bash
git diff --stat main.py services/cc_login_service.py services/ttr_login_service.py
```

Each file should show `1 +1 -1`. If anything else changed, abort and let the user investigate.

---

## Phase 4: Draft release notes

Read commit subjects since the last tag:

```bash
git log "${LATEST_TAG}..HEAD" --pretty=format:"%s"
```

For each line, classify by conventional-commit prefix (anchored at the start, optional scope in parens):

- `^fix(\(.+?\))?:` → **Bug Fixes**
- `^feat(\(.+?\))?:` → **Improvements**
- `^(docs|chore|refactor|build|ci|test|style)(\(.+?\))?:` → **skip** (internal-only, not user-facing)
- Anything else (no recognized prefix) → **Improvements** (fallback)

For each kept line:
- Strip the prefix and optional scope.
- Trim leading/trailing whitespace.
- Capitalize the first character.
- Strip trailing periods.
- Replace any em dash (`—`) with `:` or rewrite the sentence to remove it. NO em dashes in the final output.

Render into the project's release notes template (header, a one-sentence summary, Bug Fixes section, Improvements section, downloads table for the new version, and a "Running from Source" code block matching the format used in previous `RELEASE_NOTES.md` files). Use the existing `RELEASE_NOTES.md` from any prior release as the structural reference.

Rules for the template:

- If a section (Bug Fixes or Improvements) has zero bullets, omit the section header entirely.
- The summary sentence at the top is concise (one sentence, under ~15 words). It describes the release theme, not specifics. Examples: "Patch release fixing credential storage on KDE Plasma." / "Adds Wayland auto-detection and cleans up minor UI alignment issues."
- The summary contains NO em dashes.

**Show the rendered draft to the user. Do NOT write to `RELEASE_NOTES.md` yet.**

---

## Phase 5: Iterate notes inline

Ask the user verbatim:

> Does this look right? Reply `good` / `ship it` to accept, or describe what to change.

Loop:
- If the response matches `good`, `ship it`, `approved`, `lgtm`, `looks good`, or `accept` (case-insensitive), proceed.
- Otherwise, apply the user's edits and re-render the full draft. Show it again. Repeat.

Once approved, write the final draft to `RELEASE_NOTES.md`, overwriting the previous version's notes.

---

## Phase 6: Contributor scan

This phase has a corresponding shell test at
`.claude/skills/release/tests/test_contributor_scan.sh`. If you change
`PATTERNS` here, change it there too and re-run the test.

```bash
PATTERNS='claude|anthropic|noreply@anthropic\.com|\bgpt[-0-9]?\b|\bllm\b|\bcodex\b|co-authored-by:'
```

Run all three checks below. Collect every match (file, line number, matching text). If ANY check produces output, abort the release and print the matches.

### A. Commit metadata + bodies since the last tag

```bash
git log "${LATEST_TAG}..HEAD" --pretty="%H %an %ae %s%n%b" \
    | grep -inE "$PATTERNS" || true
```

### B. Every file in the diff range

```bash
git diff --name-only "${LATEST_TAG}..HEAD" | while read -r f; do
    [ -f "$f" ] && grep -inHE "$PATTERNS" "$f" || true
done
```

### C. Always-checked release artifacts

```bash
ALWAYS_CHECK=(
    RELEASE_NOTES.md
    README.md
    AppDir/AppRun
    /home/jaret/Projects/aur-toontown-multitool/PKGBUILD
    /home/jaret/Projects/aur-toontown-multitool/.SRCINFO
)
for f in "${ALWAYS_CHECK[@]}" flatpak/*.metainfo.xml; do
    [ -f "$f" ] && grep -inHE "$PATTERNS" "$f" || true
done
```

### Verdict

- If A, B, and C all produce zero output, the scan PASSED. Continue to Phase 7.
- If any of them produces output, abort with:

  > Contributor scan FAILED. Fix the source of these matches and re-run /release. No autofix.
  >
  > <list every match: file:line: text>

  Do not attempt to clean the matches automatically. Past autofix attempts are how `Co-Authored-By: Claude` slipped through originally.

---

## Phase 7: Ready-to-ship summary

Print a single block (substitute the variables):

```
▸ Ready to ship v${NEW_VERSION}

  Commit:  chore: release v${NEW_VERSION}
  Tag:     v${NEW_VERSION}
  Files:
    - main.py (APP_VERSION: ${OLD_VERSION} -> ${NEW_VERSION})
    - services/cc_login_service.py (User-Agent)
    - services/ttr_login_service.py (User-Agent)
    - RELEASE_NOTES.md (rewritten)
  Contributor scan: PASSED
  AUR bump: /home/jaret/Projects/aur-toontown-multitool from ${OLD_VERSION} to ${NEW_VERSION}

  Push targets:
    - origin main
    - origin v${NEW_VERSION}  (triggers CI release workflow)
    - aur master
```

Then ask: `Ready to ship? [y/N]`

Match `y`, `Y`, `yes`, or `YES` to proceed. Anything else aborts. The bumps and `RELEASE_NOTES.md` stay on disk for retry.

---

## Phase 8: Commit, tag, push, AUR

Execute these in order. **If any step fails, stop immediately and report which step failed.** Do not skip past failures.

```bash
# 1. Commit the source bumps
git add main.py services/cc_login_service.py services/ttr_login_service.py RELEASE_NOTES.md
git commit -m "chore: release v${NEW_VERSION}"

# 2. Tag
git tag -a "v${NEW_VERSION}" -m "v${NEW_VERSION}"

# 3. Push main and tag (triggers CI)
git push origin main
git push origin "v${NEW_VERSION}"

# 4. Bump AUR PKGBUILD and .SRCINFO
cd /home/jaret/Projects/aur-toontown-multitool
sed -i "s/^pkgver=.*/pkgver=${NEW_VERSION}/" PKGBUILD
sed -i "s/${OLD_VERSION}/${NEW_VERSION}/g" .SRCINFO

# 5. Commit and push AUR
git add PKGBUILD .SRCINFO
git commit -m "Update to v${NEW_VERSION}"
git push aur master

# 6. Return to project
cd -
```

**No `Co-Authored-By:` trailers in any commit message.** The contributor scan in Phase 6 already verified the working tree is clean of LLM attribution. Don't add it back here.

If a push fails (auth, network, conflict), stop and report which one. The local commit and tag persist; the user can retry the failed push manually.

---

## Phase 9: Final summary

Print:

```
✓ v${NEW_VERSION} released

  CI:       https://github.com/flossbud/ToonTown-MultiTool/actions
  Release:  https://github.com/flossbud/ToonTown-MultiTool/releases/tag/v${NEW_VERSION}
  AUR:      https://aur.archlinux.org/packages/toontown-multitool

  Watch CI for the build. Once it finishes, the release page will have
  the Windows EXE, Linux AppImage, and Flatpak attached.
```

End of skill.
