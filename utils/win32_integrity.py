"""Windows integrity-level capability detection for synthetic-input delivery.

PostMessage to a higher-integrity window is silently dropped by UIPI (the call
still reports success). We therefore decide BEFORE sending whether a window is
reachable by comparing token integrity levels. Off Windows this whole module is
a no-op: capability checks resolve to OK so callers behave exactly as before.
"""
from __future__ import annotations

import enum
import sys


class Capability(enum.Enum):
    OK = "ok"                    # target integrity <= ours: deliverable
    BLOCKED_UIPI = "blocked"     # target integrity > ours: PostMessage silently dropped
    UNKNOWN = "unknown"          # could not determine; treat as unsafe for suppression


def classify_integrity(own_il, target_il) -> Capability:
    """Pure classifier. own_il/target_il are integrity RIDs (ints) or None.

    TTMT official builds are never uiAccess (unsigned, per-user, asInvoker), so
    own uiAccess is treated as always False; the uiAccess-bypass case is
    unreachable and needs no branch beyond that.
    """
    if own_il is None or target_il is None:
        return Capability.UNKNOWN
    if target_il > own_il:
        return Capability.BLOCKED_UIPI
    return Capability.OK


_IS_WINDOWS = sys.platform == "win32"


def own_integrity_level():
    """This process's integrity RID, or None off Windows / on failure."""
    if not _IS_WINDOWS:
        return None
    try:
        import win32api
        import win32security
        token = win32security.OpenProcessToken(
            win32api.GetCurrentProcess(), win32security.TOKEN_QUERY)
        return _integrity_rid_from_token(token)
    except Exception:
        return None


def _integrity_rid_from_token(token):
    import win32security
    sid_and_attr = win32security.GetTokenInformation(
        token, win32security.TokenIntegrityLevel)
    sid = sid_and_attr[0]
    count = sid.GetSubAuthorityCount()
    return sid.GetSubAuthority(count - 1)


def _read_integrities(hwnd):
    """Return (own_il, target_il) as RIDs (ints) or None each. Windows-only;
    called only when _IS_WINDOWS. window_capability wraps this and never lets it
    raise. NOTE: a SendMessageTimeout(WM_NULL) UIPI probe is intentionally NOT
    implemented here -- integrity comparison is authoritative; the probe is only
    an optional future diagnostic and must never overturn the BLOCKED_UIPI result.
    """
    import win32api
    import win32con
    import win32process
    import win32security

    own = own_integrity_level()
    _, pid = win32process.GetWindowThreadProcessId(hwnd)
    if not pid:
        return (own, None)
    h = win32api.OpenProcess(win32con.PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    try:
        token = win32security.OpenProcessToken(h, win32security.TOKEN_QUERY)
        target = _integrity_rid_from_token(token)
    finally:
        win32api.CloseHandle(h)
    return (own, target)


def window_capability(hwnd) -> Capability:
    """Capability for delivering synthetic input to `hwnd`. OK off Windows.
    Never raises: a read failure is logged and classified UNKNOWN."""
    if not _IS_WINDOWS:
        return Capability.OK
    try:
        own_il, target_il = _read_integrities(hwnd)
    except Exception as e:  # noqa: BLE001
        print(f"[win32_integrity] capability read failed for hwnd={hwnd!r}: {e}")
        return Capability.UNKNOWN
    return classify_integrity(own_il, target_il)


import threading
import time as _time

CAPABILITY_TTL_SECONDS = 3.0


class WindowCapabilityCache:
    """Caches window_capability per (hwnd, pid). Two accessors:

    - get(hwnd): refresh-or-cached. Calls the reader (OpenProcess) on a miss,
      TTL expiry, or pid change. Use OFF the input hot path (focus/assignment/
      timer handlers).
    - peek(hwnd): snapshot ONLY. NEVER calls the reader. Returns the last cached
      capability, or UNKNOWN if never refreshed or the live pid has changed since.
      Use ON the input hot path.

    pid_of (default: live GetWindowThreadProcessId) is a cheap call; only the
    reader does the expensive OpenProcess.
    """

    def __init__(self, reader=window_capability, pid_of=None,
                 ttl=CAPABILITY_TTL_SECONDS, clock=_time.monotonic):
        self._reader = reader
        self._pid_of = pid_of if pid_of is not None else _live_pid
        self._ttl = ttl
        self._clock = clock
        self._lock = threading.Lock()
        self._entries = {}     # hwnd -> (pid, capability, expires_at)

    def get(self, hwnd) -> Capability:
        now = self._clock()
        pid = self._pid_of(hwnd)
        with self._lock:
            ent = self._entries.get(hwnd)
            if ent is not None and ent[0] == pid and ent[2] > now:
                return ent[1]
        cap = self._reader(hwnd)            # outside the lock
        with self._lock:
            self._entries[hwnd] = (pid, cap, now + self._ttl)
        return cap

    # refresh is an explicit alias for get (forces a fresh read when stale).
    refresh = get

    def peek(self, hwnd) -> Capability:
        pid = self._pid_of(hwnd)
        with self._lock:
            ent = self._entries.get(hwnd)
            if ent is not None and ent[0] == pid:
                return ent[1]
        return Capability.UNKNOWN

    def invalidate(self, hwnd=None):
        with self._lock:
            if hwnd is None:
                self._entries.clear()
            else:
                self._entries.pop(hwnd, None)


def _live_pid(hwnd):
    if not _IS_WINDOWS:
        return None
    try:
        import win32process
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        return pid
    except Exception:
        return None
