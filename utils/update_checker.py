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

from utils import build_flavor, build_info, version
from utils.settings_keys import (
    UPDATE_LAST_CHECK_AT,
    UPDATE_LAST_CHECK_RESULT,
    UPDATE_SKIPPED_VERSION,
)
from utils.version_compare import (
    is_beta_tag,
    is_newer,
    parse,
)


GITHUB_API = "https://api.github.com/repos/flossbud/ToonTownMultiTool-v2/releases"
CACHE_TTL_SECONDS = 6 * 60 * 60  # 6 hours
HTTP_TIMEOUT = 5.0


_BUILD_RE = re.compile(r"^Build:\s*(\d+)\s*$", re.MULTILINE)


def parse_build_from_body(body: str) -> Optional[int]:
    if not body:
        return None
    m = _BUILD_RE.search(body)
    return int(m.group(1)) if m else None


def select_release(releases: List[dict], *, is_beta: bool) -> Optional[dict]:
    """Pick the highest in-channel non-draft release from a list."""
    best = None
    best_parsed = None
    best_build = -1
    for r in releases:
        if r.get("draft"):
            continue
        tag = r.get("tag_name", "")
        parsed = parse(tag)
        if parsed is None:
            continue
        tag_is_beta = is_beta_tag(tag)
        # Defensive: cross-check with the API's prerelease boolean.
        if tag_is_beta != bool(r.get("prerelease")):
            continue
        if tag_is_beta != is_beta:
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
    Not on a thread; the worker calls this on its thread."""
    local_app_version = version.APP_VERSION
    local_build = build_info.build_number()
    local_parsed = parse(f"v{local_app_version}")
    if local_parsed is None:
        return {"kind": "failed", "reason": f"can't parse local version {local_app_version}"}

    # 1. Try cache (auto only, not manual).
    if not manual:
        cached = _read_cache(sm, local_app_version, local_build)
        if cached is not None:
            return cached

    # 2. Network call.
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

    chosen = select_release(releases, is_beta=build_flavor.is_beta())
    if chosen is None:
        _write_cache(sm, None, local_app_version, local_build)
        return {"kind": "none"}

    remote_parsed = parse(chosen["tag_name"])
    remote_build = chosen.get("build_number", 0)

    if not is_newer(local_parsed, local_build, remote_parsed, remote_build):
        _write_cache(sm, None, local_app_version, local_build)
        return {"kind": "none"}

    # 3. Skip list (auto only).
    skipped = sm.get(UPDATE_SKIPPED_VERSION) if not manual else None
    if skipped and skipped == chosen["tag_name"]:
        _write_cache(sm, chosen, local_app_version, local_build)
        return {"kind": "none"}

    info = {
        "tag_name": chosen["tag_name"],
        "body": chosen.get("body", ""),
        "html_url": chosen.get("html_url", ""),
        "build_number": remote_build,
        "assets": chosen.get("assets", []),
    }
    _write_cache(sm, chosen, local_app_version, local_build)
    return {"kind": "update", "info": info}


def _read_cache(sm, local_app_version: str, local_build: int) -> Optional[dict]:
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
    release = cached.get("release")
    if release is None:
        # Cached "no update" - still valid only if stamps match.
        stamped_v = cached.get("stamped_app_version")
        stamped_b = cached.get("stamped_build")
        if stamped_v == local_app_version and stamped_b == local_build:
            return {"kind": "none"}
        return None
    if release.get("stamped_app_version") != local_app_version or release.get("stamped_build") != local_build:
        return None
    info = {
        "tag_name": release["tag_name"],
        "body": release["body"],
        "html_url": release["html_url"],
        "build_number": release["build_number"],
        "assets": release.get("assets", []),
    }
    return {"kind": "update", "info": info}


def _write_cache(sm, chosen: Optional[dict], local_app_version: str, local_build: int) -> None:
    payload: dict
    if chosen is None:
        payload = {
            "release": None,
            "stamped_app_version": local_app_version,
            "stamped_build": local_build,
        }
    else:
        payload = {
            "release": {
                "tag_name": chosen["tag_name"],
                "body": chosen.get("body", ""),
                "html_url": chosen.get("html_url", ""),
                "build_number": chosen.get("build_number", 0),
                "assets": chosen.get("assets", []),
                "stamped_app_version": local_app_version,
                "stamped_build": local_build,
            },
        }
    try:
        sm.set(UPDATE_LAST_CHECK_AT, time.time())
        sm.set(UPDATE_LAST_CHECK_RESULT, json.dumps(payload))
    except Exception:
        # Cache write is best-effort; never fail the check.
        pass
