# `/release` Skill Design

A project-specific Claude Code skill that runs the full release flow for ToonTown MultiTool with one slash command.

## Goals

- Cut a tagged release (Windows EXE, Linux AppImage, Flatpak via CI) and publish the matching AUR bump from a single `/release` invocation.
- Make it impossible to ship attribution to Claude or any other LLM by accident.
- Keep release notes concise, in the user's voice, and free of em dashes.
- Match how the user already cuts releases manually, but automate the bookkeeping.

## Non-goals

- Generalizing across other projects. This skill is project-specific (it knows about `main.py`'s `APP_VERSION`, the two `services/*_login_service.py` User-Agents, and the AUR repo at `/home/jaret/Projects/aur-toontown-multitool`). A future generalization can read these from a config file; not now.
- Retrying or rolling back failed pushes. Failures abort and the user fixes them manually.
- Triggering or waiting for CI. The skill pushes the tag and ends; the user watches CI in the browser.

## Scope

- Slash command: `/release <version-or-bump>` where the argument is either a literal `2.0.4` or one of `patch` / `minor` / `major`.
- Single skill file: `.claude/skills/release/SKILL.md` with frontmatter and a numbered phase list. All shell commands inline; no separate scripts.

## Phases

The skill executes these in order. A phase that fails aborts the skill.

### 1. Parse argument

- If the argument matches `^\d+\.\d+\.\d+$`, use it as the new version.
- If the argument is `patch`, `minor`, or `major`, read the latest tag matching `v\d+\.\d+\.\d+` from `git tag --list`, parse it, and bump the requested component.
- Otherwise, abort with a usage message.

### 2. Pre-flight checks

**Hard-block (abort with the failing condition):**

- `git status --porcelain | grep -v '^??'` is non-empty (working tree has staged or unstaged changes; untracked files are allowed since `.codex/` and `docs/superpowers/` live there).
- Current branch is not `main` (`git rev-parse --abbrev-ref HEAD`).
- `git log <last-tag>..HEAD --oneline` is empty (nothing to release).
- AUR repo at `/home/jaret/Projects/aur-toontown-multitool` does not exist OR `git -C <aur-path> status --porcelain` is non-empty.

**Soft-warn (print issue, ask "proceed anyway? [y/N]"):**

- `pytest tests/ -q` returns non-zero. Print the failing test count.

### 3. Bump version strings

Edit in place:

- `main.py`: `APP_VERSION = "<old>"` → `APP_VERSION = "<new>"`.
- `services/cc_login_service.py`: `"User-Agent": "ToontownMultiTool/<old>"` → new.
- `services/ttr_login_service.py`: same.

After editing, `git diff` is shown to confirm the bumps look right.

### 4. Draft release notes

Read `git log <last-tag>..HEAD --pretty=format:%s` and categorize by conventional-commit prefix:

- `fix:` → **Bug Fixes**.
- `feat:` → **Improvements**.
- `docs:`, `chore:`, `refactor:`, `build:`, `ci:`, `test:`, `style:` → skipped (internal-only; not user-facing).

For each kept commit:

- Strip the prefix (`fix:`, `feat:`).
- Strip the optional scope (`(scope)`).
- Replace any em dashes with `:` or rewrite the sentence to remove them.
- Keep one bullet per commit; if multiple commits describe the same fix, the user can collapse them in the next phase.

Commits without a recognized conventional-commit prefix go under **Improvements** as a fallback.

Render into the existing template format (header, two sections, downloads table with the new version, "Running from Source" block).

### 5. Iterate notes inline

Show the draft in chat. The user replies either with "good" / "ship it" (proceed) or with edits ("collapse the first two bullets", "drop the last fix", etc.). I revise and re-show. Loop until approved.

When approved, write to `RELEASE_NOTES.md` (overwriting the previous version's notes).

### 6. Contributor scan

Patterns (regex, case-insensitive):

- `claude`
- `anthropic`
- `noreply@anthropic\.com`
- `\bgpt[-\d]?\b`
- `\bllm\b`
- `\bcodex\b`
- `co-authored-by:`

Targets:

- `git log <last-tag>..HEAD --pretty="%H %an %ae %s%n%b"`: every commit's metadata + body since the last release.
- Every file in `git diff --name-only <last-tag>..HEAD`: grep file contents for the patterns.
- Always check `RELEASE_NOTES.md`, `README.md`, `AppDir/AppRun`, every file matching `flatpak/*.metainfo.xml`, `/home/jaret/Projects/aur-toontown-multitool/PKGBUILD`, `/home/jaret/Projects/aur-toontown-multitool/.SRCINFO`.

If any pattern matches anywhere, print the file, the line number, and the matching text, then abort. The user fixes the source of the leak (commit message, file content) and re-runs `/release`. No autofix: prior autofix attempts are how `Co-Authored-By: Claude` slipped through originally.

### 7. Ready-to-ship summary

Print:

- New version.
- Files about to be committed.
- Commit message.
- Tag name.
- Confirmation that the contributor scan passed.
- AUR repo and the version bump it will receive.

Ask "Ready to ship? [y/N]". Match `y`/`Y`/`yes` to proceed; anything else aborts. The bumps and `RELEASE_NOTES.md` stay on disk for the next attempt.

### 8. Commit, tag, push, AUR

In order:

1. `git add main.py services/cc_login_service.py services/ttr_login_service.py RELEASE_NOTES.md`
2. `git commit -m "chore: release v<new>"` (no coauthor trailer).
3. `git tag -a v<new> -m "v<new>"`.
4. `git push origin main`.
5. `git push origin v<new>` (triggers CI release workflow).
6. `cd /home/jaret/Projects/aur-toontown-multitool`.
7. `sed -i "s/^pkgver=.*/pkgver=<new>/" PKGBUILD`.
8. `sed -i "s/<old>/<new>/g" .SRCINFO`.
9. `git add PKGBUILD .SRCINFO`.
10. `git commit -m "Update to v<new>"`.
11. `git push aur master`.

If any push fails, abort and report. The local commit/tag persist; the user fixes the auth/network issue and re-runs the failing push manually.

### 9. Final summary

Print links to:

- GitHub Actions run page (so the user can monitor the build).
- New release page (will exist once CI uploads artifacts).
- AUR package page.

## Error handling

Each phase prints a clear marker (`▸ Phase 3: bumping version strings`) before running. On error, the phase prints what failed and the skill exits without continuing. There is no rollback: a partial run leaves on-disk edits and possibly a local commit/tag, all of which the user can resolve manually (`git reset --soft HEAD~1`, etc.).

Pushes (Phase 8 steps 4, 5, 11) are the only side-effects beyond the local repo and AUR worktree. If a push fails, nothing on the remote has changed (push is atomic per ref).

## Architecture / files

- `.claude/skills/release/SKILL.md` — the only file the skill itself adds. Contains frontmatter (`name: release`, `description: ...`) and a body documenting all phases with the exact shell commands to run.
- `docs/superpowers/specs/2026-04-26-release-skill-design.md` — this spec.
- Future implementation plan: `docs/superpowers/plans/2026-04-26-release-skill.md`.

## Open questions

None. All design decisions resolved during brainstorming.
