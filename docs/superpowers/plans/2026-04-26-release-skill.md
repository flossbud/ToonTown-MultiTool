# `/release` Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a single-file Claude Code skill at `.claude/skills/release/SKILL.md` that runs the full ToonTown MultiTool release flow when invoked as `/release <version-or-bump>`.

**Architecture:** One Markdown file with YAML frontmatter and nine numbered phases. Each phase is a mix of bash commands (executed via the Bash tool) and instructions to Claude (e.g., "Show the draft to the user, loop until approved"). One auxiliary shell test script verifies the contributor-scan regex against canned inputs so the most safety-critical regex doesn't silently break.

**Tech Stack:** Markdown + YAML frontmatter (skill format), bash 5+ (the runtime executing skill commands), git, sed, grep, pytest (for the soft-warn pre-flight test step).

**Spec:** `docs/superpowers/specs/2026-04-26-release-skill-design.md`

**File structure:**

- Create: `.claude/skills/release/SKILL.md` — the skill itself, built up phase-by-phase across the four tasks below.
- Create: `.claude/skills/release/tests/test_contributor_scan.sh` — shell test that runs the scan regex against good and bad inputs. Catches regressions if a future edit weakens a pattern.

No source files in the main project are touched; this plan only adds the skill and its test.

---

### Task 1: Skill scaffold + Phases 1-3 (parse arg, pre-flight, version bumps)

**Files:**
- Create: `.claude/skills/release/SKILL.md`

- [ ] **Step 1: Create the skills directory**

```bash
mkdir -p /home/jaret/Projects/ToonTownMultiTool-v2/.claude/skills/release
```

- [ ] **Step 2: Write the SKILL.md scaffold with Phases 1-3**

Create `/home/jaret/Projects/ToonTownMultiTool-v2/.claude/skills/release/SKILL.md` with exactly this content:

````markdown
---
name: release
description: Cut a versioned release of ToonTown MultiTool. Bumps version strings, drafts release notes from commits since the last tag, runs a strict contributor scan that hard-blocks on any Claude / Anthropic / GPT / LLM / Codex / Co-Authored-By leak, then on user confirmation commits, tags, pushes main, pushes the tag (which triggers CI builds for Windows EXE + Linux AppImage + Flatpak), and bumps the AUR PKGBUILD. Hybrid flow: prep work runs automatically, then a single "ready to ship?" prompt gates all destructive actions.
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
````

- [ ] **Step 3: Verify the file is valid Markdown with YAML frontmatter**

```bash
cd /home/jaret/Projects/ToonTownMultiTool-v2
head -5 .claude/skills/release/SKILL.md
python3 -c "
import re, sys
text = open('.claude/skills/release/SKILL.md').read()
m = re.match(r'^---\n(.*?)\n---\n', text, re.S)
assert m, 'no frontmatter'
import yaml  # assumes PyYAML installed; if not, just check the regex matched
fm = yaml.safe_load(m.group(1))
assert fm['name'] == 'release', fm
assert 'description' in fm
print('frontmatter OK:', list(fm.keys()))
"
```

If PyYAML is not installed, fall back to a simpler check:

```bash
python3 -c "
import re
text = open('.claude/skills/release/SKILL.md').read()
m = re.match(r'^---\nname: release\ndescription: .+?\n---\n', text, re.S)
assert m, 'frontmatter is missing or malformed'
print('frontmatter OK')
"
```

Expected: prints `frontmatter OK`.

- [ ] **Step 4: Commit**

```bash
cd /home/jaret/Projects/ToonTownMultiTool-v2
git add .claude/skills/release/SKILL.md
git commit -m "feat(skill): release skill scaffold with arg parsing, pre-flight, version bumps"
```

---

### Task 2: Phases 4-5 (release notes draft + iterate)

**Files:**
- Modify: `.claude/skills/release/SKILL.md` (append two phases)

- [ ] **Step 1: Append Phase 4 and Phase 5 to the skill**

Append the following content to `/home/jaret/Projects/ToonTownMultiTool-v2/.claude/skills/release/SKILL.md` (after the existing Phase 3 section, separated by `---`):

````markdown

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
- Strip the prefix (`fix:`, `feat:`) and the optional scope (`(scope)`).
- Trim leading/trailing whitespace.
- Capitalize the first character.
- Strip trailing periods.
- Replace any em dash (`—`) with `:` or rewrite the sentence to remove it. NO em dashes in the final output.

Render into this exact template (replace `<NEW_VERSION>` and the bullet lists; the one-sentence summary is your judgment based on the dominant theme of the changes):

```markdown
## ToonTown MultiTool v<NEW_VERSION>

<one-sentence summary>.

---

### Bug Fixes

- <bullet>
- <bullet>

### Improvements

- <bullet>
- <bullet>

---

### Downloads

| File | Platform |
|------|----------|
| `ToonTownMultiTool-v<NEW_VERSION>-Windows-x86_64.exe` | Windows 10/11 |
| `TTMultiTool-v<NEW_VERSION>-Linux-x86_64.AppImage` | Linux (X11 / Wayland) |

---

### Running from Source

​```bash
git clone https://github.com/flossbud/ToonTown-MultiTool.git
cd ToonTown-MultiTool
pip install -r requirements.txt
python main.py
​```
```

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

````

- [ ] **Step 2: Verify the file still parses and the new sections were appended**

```bash
cd /home/jaret/Projects/ToonTownMultiTool-v2
grep -c "^## Phase" .claude/skills/release/SKILL.md
```

Expected output: `5` (Phases 1, 2, 3, 4, 5).

- [ ] **Step 3: Commit**

```bash
git add .claude/skills/release/SKILL.md
git commit -m "feat(skill): release notes drafting and inline iteration phases"
```

---

### Task 3: Phase 6 (contributor scan) + test fixture

**Files:**
- Modify: `.claude/skills/release/SKILL.md` (append Phase 6)
- Create: `.claude/skills/release/tests/test_contributor_scan.sh`

- [ ] **Step 1: Write the test fixture FIRST (TDD: define the contract)**

Create directory and file:

```bash
mkdir -p /home/jaret/Projects/ToonTownMultiTool-v2/.claude/skills/release/tests
```

Create `/home/jaret/Projects/ToonTownMultiTool-v2/.claude/skills/release/tests/test_contributor_scan.sh` with exactly:

```bash
#!/usr/bin/env bash
# Test fixture for the contributor-scan regex used in
# .claude/skills/release/SKILL.md (Phase 6).
#
# If you change the PATTERNS variable here, change it in SKILL.md too.

set -e

PATTERNS='claude|anthropic|noreply@anthropic\.com|\bgpt[-0-9]?\b|\bllm\b|\bcodex\b|co-authored-by:'

assert_match() {
    local desc="$1"
    local input="$2"
    if ! echo "$input" | grep -iqE "$PATTERNS"; then
        echo "FAIL (should match): $desc"
        echo "  input: $input"
        exit 1
    fi
}

assert_no_match() {
    local desc="$1"
    local input="$2"
    if echo "$input" | grep -iqE "$PATTERNS"; then
        echo "FAIL (should NOT match): $desc"
        echo "  input: $input"
        echo "  matched as: $(echo "$input" | grep -ioE "$PATTERNS")"
        exit 1
    fi
}

# --- Should match ---
assert_match "coauthor trailer (Claude)"  "Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
assert_match "coauthor trailer (any)"     "Co-authored-by: Someone Else <a@b.c>"
assert_match "anthropic mention"          "Generated with the Anthropic SDK"
assert_match "import anthropic"           "import anthropic"
assert_match "claude in comment"          "# Claude wrote this"
assert_match "GPT-4 mention"              "Drafted by GPT-4"
assert_match "bare gpt"                   "see gpt for details"
assert_match "LLM mention"                "uses an LLM under the hood"
assert_match "Codex word"                 "Codex generated the diff"
assert_match "anthropic email"            "noreply@anthropic.com"

# --- Should NOT match ---
assert_no_match "encrypted"               "encrypted message body"
assert_no_match "html escape"             "from html import escape"
assert_no_match "CodexValidator class"    "class CodexValidator:"
assert_no_match "compiler"                "the compiler emits valid IR"
assert_no_match "plain code"              "def calculate(x): return x * 2"

echo "All contributor scan tests passed."
```

Make it executable:

```bash
chmod +x /home/jaret/Projects/ToonTownMultiTool-v2/.claude/skills/release/tests/test_contributor_scan.sh
```

- [ ] **Step 2: Run the test fixture and verify it passes**

```bash
cd /home/jaret/Projects/ToonTownMultiTool-v2
.claude/skills/release/tests/test_contributor_scan.sh
```

Expected output: `All contributor scan tests passed.`

If any line fails, the regex is wrong or the test case is wrong; investigate before continuing.

- [ ] **Step 3: Append Phase 6 to the skill**

Append the following to `/home/jaret/Projects/ToonTownMultiTool-v2/.claude/skills/release/SKILL.md`:

````markdown

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

````

- [ ] **Step 4: Verify total phase count and re-run the test**

```bash
cd /home/jaret/Projects/ToonTownMultiTool-v2
grep -c "^## Phase" .claude/skills/release/SKILL.md
.claude/skills/release/tests/test_contributor_scan.sh
```

Expected: phase count is `6`; test prints `All contributor scan tests passed.`

- [ ] **Step 5: Commit**

```bash
git add .claude/skills/release/SKILL.md .claude/skills/release/tests/
git commit -m "feat(skill): contributor scan phase with regex test fixture"
```

---

### Task 4: Phases 7-9 (ready-to-ship summary, push flow, final summary)

**Files:**
- Modify: `.claude/skills/release/SKILL.md` (append Phases 7, 8, 9)

- [ ] **Step 1: Append Phases 7, 8, and 9**

Append the following to `/home/jaret/Projects/ToonTownMultiTool-v2/.claude/skills/release/SKILL.md`:

````markdown

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

````

- [ ] **Step 2: Verify the skill file is complete (9 phases) and re-run the contributor-scan test**

```bash
cd /home/jaret/Projects/ToonTownMultiTool-v2
grep -c "^## Phase" .claude/skills/release/SKILL.md
.claude/skills/release/tests/test_contributor_scan.sh
```

Expected: phase count is `9`; the test still passes.

- [ ] **Step 3: Read through the whole SKILL.md once for coherence**

```bash
wc -l .claude/skills/release/SKILL.md
cat .claude/skills/release/SKILL.md | head -30
echo "---"
cat .claude/skills/release/SKILL.md | tail -30
```

Sanity-check: file starts with the YAML frontmatter and ends with `End of skill.`

- [ ] **Step 4: Run the contributor scan against THIS skill file as a self-test**

The skill itself necessarily contains the strings `claude`, `anthropic`, `gpt`, `llm`, `codex`, and `co-authored-by` (in the regex pattern definition and in instructions like "do not add Co-Authored-By"). When the user actually invokes `/release`, this file would not be in the diff range (it's already committed), so it won't trigger.

But to confirm the skill won't accidentally self-flag in some unusual edge case, test that the file is NOT in any path the scan would pick up during a normal run:

```bash
# The scan's "always-checked" list:
ALWAYS_CHECK=(
    RELEASE_NOTES.md
    README.md
    AppDir/AppRun
    /home/jaret/Projects/aur-toontown-multitool/PKGBUILD
    /home/jaret/Projects/aur-toontown-multitool/.SRCINFO
)
for f in "${ALWAYS_CHECK[@]}" flatpak/*.metainfo.xml; do
    if [ "$f" = ".claude/skills/release/SKILL.md" ]; then
        echo "WARN: SKILL.md is in always-checked list — that would be a false positive"
        exit 1
    fi
done
echo "SKILL.md correctly excluded from always-check list"
```

Expected: `SKILL.md correctly excluded from always-check list`. (It is not in the list, by design.)

- [ ] **Step 5: Commit**

```bash
git add .claude/skills/release/SKILL.md
git commit -m "feat(skill): ready-to-ship summary, push flow, AUR bump"
```

---

## Self-Review Checklist

After all four tasks complete, run:

```bash
cd /home/jaret/Projects/ToonTownMultiTool-v2
ls .claude/skills/release/
grep -c "^## Phase" .claude/skills/release/SKILL.md
.claude/skills/release/tests/test_contributor_scan.sh
git log --oneline -5 .claude/skills/release/
```

Expected:
- Directory contains `SKILL.md` and `tests/test_contributor_scan.sh`.
- Phase count is `9`.
- Contributor scan test prints `All contributor scan tests passed.`
- Four commits on the skill (one per task).

The skill is then ready to be invoked the next time the user runs `/release <version>`.
