"""GitHub Releases API client + comparator + cache. Emits Qt signals.

The check_sync() entry point is exposed for unit tests; production code
calls check_async() which dispatches to a QThread+worker pair matching
the pattern already used elsewhere in this codebase (e.g.
tabs/launch_tab.py's _start_keyring_probe).
"""
from __future__ import annotations

import json
import re
import time
from typing import List, Optional

import requests
from PySide6.QtCore import QObject, QThread, Signal

from utils import build_info, version
from utils.settings_keys import (
    UPDATE_LAST_CHECK_AT,
    UPDATE_LAST_CHECK_RESULT,
    UPDATE_SKIPPED_VERSION,
)
from utils.version_compare import (
    is_newer,
    parse,
)
from utils.source_release_state import (
    ReleaseState,
    classify as _classify,
    head_sha as _head_sha,
    resolve_release_commit as _resolve_release_commit,
)


GITHUB_API = "https://api.github.com/repos/flossbud/ToonTown-MultiTool/releases"
CACHE_TTL_SECONDS = 6 * 60 * 60  # 6 hours
HTTP_TIMEOUT = 5.0

GITHUB_API_ROOT = "https://api.github.com/repos/flossbud/ToonTown-MultiTool"


def _api_get(path: str):
    """GET a GitHub API path (e.g. /git/ref/tags/v1.2.3) -> JSON dict or
    None. Errors (incl. 403/429 rate limits) map to None, which callers
    treat as UNPROVABLE."""
    try:
        resp = requests.get(
            f"{GITHUB_API_ROOT}{path}",
            headers={
                "User-Agent": f"ToonTownMultiTool/{version.APP_VERSION}",
                "Accept": "application/vnd.github+json",
            },
            timeout=HTTP_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, dict) else None
    except (requests.RequestException, ValueError, json.JSONDecodeError):
        return None


_BUILD_RE = re.compile(r"^Build:\s*(\d+)\s*$", re.MULTILINE)


def parse_build_from_body(body: str) -> Optional[int]:
    if not body:
        return None
    m = _BUILD_RE.search(body)
    return int(m.group(1)) if m else None


def select_release(releases: List[dict]) -> Optional[dict]:
    """Pick the highest non-draft release by tuple compare + suffix
    ordering + build number tiebreaker.

    Post-rebrand: no channel filtering. Every install (stable AUR,
    ttmt-beta AUR, AppImage, Flatpak, EXE, .deb) reads the same release
    feed. The prerelease flag is informational only; it surfaces in the
    GitHub UI but does not gate updater visibility. See
    docs/superpowers/specs/2026-05-27-release-flow-restructure-design.md.
    """
    best = None
    best_parsed = None
    best_build = -1
    for r in releases:
        if r.get("draft"):
            continue
        parsed = parse(r.get("tag_name", ""))
        if parsed is None:
            continue
        build = parse_build_from_body(r.get("body", "")) or 0
        if best_parsed is None or is_newer(best_parsed, best_build, parsed, build):
            best = r
            best_parsed = parsed
            best_build = build
    if best is None:
        return None
    # Don't mutate the caller's dict; return a shallow copy with the
    # parsed build number attached.
    result = dict(best)
    result["build_number"] = best_build
    return result


class _CheckWorker(QObject):
    finished = Signal(dict)  # {"kind": "update", "info": ...} / {"kind": "none"} / {"kind": "failed", "reason": ...}

    def __init__(self, settings_manager, manual: bool):
        super().__init__()
        self._sm = settings_manager
        self._manual = manual

    def run(self):
        # Belt-and-suspenders: ensure `finished` always emits, even if
        # _perform_check raises an unhandled exception. Without this, the
        # checker would get stuck with _in_flight=True forever.
        try:
            result = _perform_check(self._sm, manual=self._manual)
        except Exception as e:  # noqa: BLE001
            result = {"kind": "failed", "reason": f"unexpected: {e}"}
        self.finished.emit(result)


class UpdateChecker(QObject):
    update_available = Signal(dict)
    no_update = Signal()
    check_failed = Signal(str)

    def __init__(self, settings_manager, parent=None):
        super().__init__(parent)
        self._sm = settings_manager
        self._thread: Optional[QThread] = None
        self._worker: Optional[_CheckWorker] = None
        self._in_flight = False

    def check_async(self, *, manual: bool) -> bool:
        """Start a background check. Returns False if one is already in
        flight. Connect to update_available / no_update / check_failed
        for results."""
        if self._in_flight:
            return False
        self._in_flight = True
        self._thread = QThread(self)
        self._worker = _CheckWorker(self._sm, manual)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_finished)
        self._worker.finished.connect(self._thread.quit)
        # No finished->worker.deleteLater: that DeferredDelete posted on the
        # worker thread races with PySide6's wrapper deletion when
        # _cleanup_thread drops self._worker = None on the main thread. Same
        # double-delete / shiboken-Python-access crash as the keyring probe
        # had before its fix in tabs/launch_tab.py. _cleanup_thread now
        # waits for the worker thread before clearing refs, so PySide6's
        # ref-drop deletion is the only actor.
        self._thread.finished.connect(self._cleanup_thread)
        self._thread.start()
        return True

    def check_sync(self, *, manual: bool) -> None:
        """Synchronous variant used by unit tests."""
        result = _perform_check(self._sm, manual=manual)
        self._dispatch(result)

    def _on_finished(self, result: dict) -> None:
        self._dispatch(result)
        self._in_flight = False

    def _cleanup_thread(self) -> None:
        # Block on the worker thread's true exit before dropping refs.
        # See check_async for the full rationale: clearing self._worker = None
        # while the worker thread is mid-shutdown raced with shiboken's
        # Python-state access from ~QObject() and crashed with SIGBUS /
        # SIGSEGV in Sbk_GetPyOverride during posted-event delivery.
        if self._thread is not None:
            self._thread.wait(2000)
        self._thread = None
        self._worker = None
        # Reset here as the guaranteed-final path. _on_finished also
        # resets, but _cleanup_thread fires even when no `finished`
        # signal was emitted (e.g. if QThread terminates abnormally).
        self._in_flight = False

    def shutdown(self) -> None:
        """Drain any in-flight check before the owning widget closes.

        Matches the pattern in tabs/launch_tab.py for thread teardown.
        Wait up to 2 seconds for a clean exit; Qt will terminate
        thereafter on process exit anyway.
        """
        if self._thread is not None and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(2000)

    def _dispatch(self, result: dict) -> None:
        kind = result.get("kind")
        if kind == "update":
            self.update_available.emit(result["info"])
        elif kind == "none":
            self.no_update.emit()
        elif kind == "failed":
            self.check_failed.emit(result.get("reason", "unknown"))


def _perform_check(sm, *, manual: bool) -> dict:
    """Pure(ish) function: takes a settings_manager, returns a dict.
    Not on a thread; the worker calls this on its thread.

    Policy (version compare -> skip list -> source adjudication) is
    re-applied on EVERY read path - cache hits included - so a cached
    release can never bypass a policy that would have suppressed it."""
    local_app_version = version.APP_VERSION
    local_build = build_info.build_number()
    local_parsed = parse(f"v{local_app_version}")
    if local_parsed is None:
        return {"kind": "failed", "reason": f"can't parse local version {local_app_version}"}
    source_run = build_info.is_source_run()
    local_head = _head_sha() if source_run else None

    ctx = {
        "sm": sm,
        "manual": manual,
        "source_run": source_run,
        "local_parsed": local_parsed,
        "local_build": local_build,
        "local_app_version": local_app_version,
        "local_head": local_head,
    }

    # 1. Cache (auto only).
    if not manual:
        hit = _read_cache(sm, local_app_version, local_build, local_head)
        if hit is not None:
            release, resolved_sha = hit
            if release is None:
                return {"kind": "none"}
            return _apply_policy(release, resolved_sha, ctx, from_cache=True)

    # 2. Network.
    try:
        resp = requests.get(
            f"{GITHUB_API}?per_page=30",
            headers={
                "User-Agent": f"ToonTownMultiTool/{local_app_version}",
                "Accept": "application/vnd.github+json",
            },
            timeout=HTTP_TIMEOUT,
        )
        resp.raise_for_status()
        releases = resp.json()
    except requests.RequestException as e:
        return {"kind": "failed", "reason": str(e)}
    except (ValueError, json.JSONDecodeError) as e:
        return {"kind": "failed", "reason": f"bad JSON: {e}"}

    chosen = select_release(releases)
    if chosen is None:
        _write_cache(sm, None, None, local_app_version, local_build, local_head)
        return {"kind": "none"}
    return _apply_policy(chosen, None, ctx, from_cache=False)


def _apply_policy(release, resolved_sha, ctx, *, from_cache: bool) -> dict:
    """Single policy funnel for cache hits AND fresh fetches."""
    sm = ctx["sm"]

    def cache(sha):
        if not from_cache:
            _write_cache(sm, release, sha, ctx["local_app_version"],
                         ctx["local_build"], ctx["local_head"])

    remote_parsed = parse(release["tag_name"])
    remote_build = release.get("build_number", 0)
    if not is_newer(ctx["local_parsed"], ctx["local_build"],
                    remote_parsed, remote_build):
        if not from_cache:
            _write_cache(sm, None, None, ctx["local_app_version"],
                         ctx["local_build"], ctx["local_head"])
        return {"kind": "none"}

    skipped = sm.get(UPDATE_SKIPPED_VERSION) if not ctx["manual"] else None
    if skipped and skipped == release["tag_name"]:
        cache(resolved_sha)
        return {"kind": "none"}

    if ctx["source_run"] and not ctx["manual"]:
        if resolved_sha is None:
            resolved_sha = _resolve_release_commit(release["tag_name"], _api_get)
        state = (_classify(resolved_sha) if resolved_sha
                 else ReleaseState.UNPROVABLE)
        if state in (ReleaseState.AT_OR_PAST, ReleaseState.DIVERGENT):
            print(f"[update] source run {state.name.lower()} vs "
                  f"{release['tag_name']}; banner suppressed")
            cache(resolved_sha)
            return {"kind": "none"}

    info = {
        "tag_name": release["tag_name"],
        "body": release.get("body", ""),
        "html_url": release.get("html_url", ""),
        "build_number": remote_build,
        "assets": release.get("assets", []),
    }
    cache(resolved_sha)
    return {"kind": "update", "info": info}


def _read_cache(sm, local_app_version: str, local_build: int,
                local_head):
    """Returns None on miss; (None, None) for a cached version-compare
    no-update; (release_dict, resolved_sha_or_None) for a cached release.
    Policy is NOT applied here - the caller re-applies it."""
    last_at = sm.get(UPDATE_LAST_CHECK_AT)
    try:
        last_at_f = float(last_at) if last_at is not None else None
    except (TypeError, ValueError):
        return None
    if last_at_f is None or (time.time() - last_at_f) > CACHE_TTL_SECONDS:
        return None
    raw = sm.get(UPDATE_LAST_CHECK_RESULT)
    if not raw:
        return None
    try:
        cached = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if (cached.get("stamped_app_version") != local_app_version
            or cached.get("stamped_build") != local_build
            or cached.get("stamped_head") != local_head):
        return None
    release = cached.get("release")
    if release is None:
        return (None, None)
    if "tag_name" not in release:
        return None
    return (release, cached.get("resolved_sha"))


def _write_cache(sm, chosen, resolved_sha, local_app_version: str,
                 local_build: int, local_head) -> None:
    payload = {
        "stamped_app_version": local_app_version,
        "stamped_build": local_build,
        "stamped_head": local_head,
        "resolved_sha": resolved_sha,
        "release": None,
    }
    if chosen is not None:
        payload["release"] = {
            "tag_name": chosen["tag_name"],
            "body": chosen.get("body", ""),
            "html_url": chosen.get("html_url", ""),
            "build_number": chosen.get("build_number", 0),
            "assets": chosen.get("assets", []),
        }
    try:
        sm.set(UPDATE_LAST_CHECK_AT, time.time())
        sm.set(UPDATE_LAST_CHECK_RESULT, json.dumps(payload))
    except Exception:
        # Cache write is best-effort; never fail the check.
        pass
