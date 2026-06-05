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
