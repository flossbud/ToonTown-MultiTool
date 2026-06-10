"""Git-aware adjudication of a SOURCE run against the latest release.

Used by the update checker to decide whether the auto-update banner is
justified when running from a git checkout. Suppression requires PROOF
(AT_OR_PAST or DIVERGENT); BEHIND and UNPROVABLE keep the banner.

Suppression needs the release commit object locally, i.e. having fetched
history that contains the release (the tag itself or the branch it was cut
from; a narrow-refspec or shallow fetch may not bring it). A tree that
never fetched it classifies UNPROVABLE and falls back to the plain version
comparison - which is exactly how a pristine stale clone still gets told
about updates.

Release tags are treated as trusted and immutable (the project never moves
released tags); a locally rewritten tag of the same name can misclassify.

All git access goes through an injected runner for testability. The
default runner pins cwd to the REPO ROOT (derived from this file), never
the process cwd: `python /repo/main.py` launched from $HOME must not query
$HOME. It catches missing-git/timeout/OS errors and returns the documented
error tuple (-1, ""); callers treat anything but the documented 0/1 codes
as UNPROVABLE.
"""
from __future__ import annotations

import subprocess
import urllib.parse
from enum import Enum, auto
from pathlib import Path
from typing import Callable, Optional, Tuple

_REPO_ROOT = Path(__file__).resolve().parents[1]
_GIT_TIMEOUT = 5.0
_MAX_TAG_DEREFS = 3  # deref calls AFTER the initial ref lookup

Runner = Callable[..., Tuple[int, str]]


class ReleaseState(Enum):
    AT_OR_PAST = auto()   # release commit is an ancestor of HEAD (or HEAD)
    DIVERGENT = auto()    # both sides have own commits; full (non-shallow) repo
    BEHIND = auto()       # HEAD is a strict ancestor of the release commit
    UNPROVABLE = auto()   # anything else; callers fall back to version compare


def _default_runner(args, timeout: float = _GIT_TIMEOUT) -> Tuple[int, str]:
    try:
        r = subprocess.run(
            ["git", *args],
            capture_output=True, text=True, timeout=timeout, cwd=_REPO_ROOT,
        )
        return (r.returncode, r.stdout)
    except (FileNotFoundError, OSError, subprocess.SubprocessError):
        return (-1, "")


def classify(release_sha: str, run: Runner = _default_runner) -> ReleaseState:
    """Strict decision table; check order makes HEAD == release_sha land
    AT_OR_PAST. merge-base --is-ancestor: rc 0 = yes, rc 1 = no, anything
    else = error. DIVERGENT requires two explicit "no"s AND a confirmed
    non-shallow repository."""
    rc, _ = run(["cat-file", "-e", f"{release_sha}^{{commit}}"])
    if rc != 0:
        return ReleaseState.UNPROVABLE
    rc, _ = run(["merge-base", "--is-ancestor", release_sha, "HEAD"])
    if rc == 0:
        return ReleaseState.AT_OR_PAST
    if rc != 1:
        return ReleaseState.UNPROVABLE
    rc, _ = run(["merge-base", "--is-ancestor", "HEAD", release_sha])
    if rc == 0:
        return ReleaseState.BEHIND
    if rc != 1:
        return ReleaseState.UNPROVABLE
    rc, out = run(["rev-parse", "--is-shallow-repository"])
    if rc == 0 and out.strip() == "false":
        return ReleaseState.DIVERGENT
    return ReleaseState.UNPROVABLE


def resolve_release_commit(tag: str, api_get,
                           run: Runner = _default_runner) -> Optional[str]:
    """Release tag -> commit sha. Local tag first (zero network); else the
    GitHub git-ref API with bounded annotated-tag dereferencing. None means
    unresolvable (callers treat as UNPROVABLE). NEVER uses the release's
    target_commitish (often a moving branch name).

    api_get(url_path) -> parsed JSON dict or None. The caller owns HTTP
    concerns (headers, timeouts, error mapping to None)."""
    rc, out = run(["rev-parse", "--verify", "--quiet",
                   f"refs/tags/{tag}^{{commit}}"])
    if rc == 0 and out.strip():
        return out.strip()

    quoted = urllib.parse.quote(tag, safe="")
    payload = api_get(f"/git/ref/tags/{quoted}")
    seen = set()
    for _ in range(_MAX_TAG_DEREFS + 1):
        if not isinstance(payload, dict):
            return None
        obj = payload.get("object")
        if not isinstance(obj, dict):
            return None
        otype, sha = obj.get("type"), obj.get("sha")
        if not isinstance(sha, str) or not sha:
            return None
        if otype == "commit":
            return sha
        if otype != "tag" or sha in seen:
            return None
        seen.add(sha)
        payload = api_get(f"/git/tags/{sha}")
    return None


def head_sha(run: Runner = _default_runner) -> Optional[str]:
    """Live HEAD sha, deliberately NOT cached: an external checkout while
    the app is running must be visible to the next update check."""
    rc, out = run(["rev-parse", "HEAD"])
    if rc == 0 and out.strip():
        return out.strip()
    return None
