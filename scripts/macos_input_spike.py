#!/usr/bin/env python3
"""macOS input feasibility spike (Phase 0). Standalone; do NOT import app modules.

Gates (see docs/superpowers/specs/2026-06-12-macos-support-design.md):
  P0a  inject  — background keyboard injection to a specific TTR PID
  P0b  loop    — real capture -> suppress -> reinject loop + echo + fail-open
  P0b  type    — typed-text + modifier delivery to a background TTR PID
  P0c  map     — port -> PID -> window identity mapping

Usage:
  python3 scripts/macos_input_spike.py list
  python3 scripts/macos_input_spike.py inject <pidA> <pidB> [--key w] [--reps 30]
  python3 scripts/macos_input_spike.py loop [--seconds 30] [--key w]
  python3 scripts/macos_input_spike.py type <pid> <text> [--mods shift,control,option]
  python3 scripts/macos_input_spike.py map [--port-min 1024] [--port-max 65535]

PyObjC is imported lazily inside the command functions so this file imports on
any platform (the pure-logic helpers are unit-tested on Linux/Windows CI).
"""
from __future__ import annotations

import dataclasses
import sys
import time

# Sentinel stamped into every event we post, so capture can recognise our own
# synthetic traffic regardless of what the P0b echo measurement concludes.
SPIKE_EVENT_TAG = 0x7474_6D74  # "ttmt" in hex; arbitrary non-zero marker

# TTR's macOS app reports this as the window owner name. Matched with startswith
# so a future "Toontown Rewritten (Beta)" suffix still matches, without admitting
# unrelated names that merely contain the marker mid-string. Title is NOT used:
# kCGWindowName may be withheld without Screen Recording.
TTR_OWNER_MARKER = "Toontown Rewritten"


@dataclasses.dataclass(frozen=True)
class WindowRecord:
    pid: int
    window_id: int
    owner: str
    bounds: tuple  # (x, y, width, height)
    bundle_id: str = None  # filled by enumerate_windows (PyObjC layer); None in pure tests


def identify_ttr_windows(window_info) -> list:
    """Filter a CGWindowListCopyWindowInfo-shaped list down to TTR WindowRecords.

    `window_info` is a list of dicts with string keys (kCGWindowOwnerPID,
    kCGWindowNumber, kCGWindowOwnerName, kCGWindowBounds). Windows missing a
    pid/number, or with zero area, are skipped.
    """
    out = []
    for w in window_info:
        owner = w.get("kCGWindowOwnerName") or ""
        if not owner.startswith(TTR_OWNER_MARKER):
            continue
        pid = w.get("kCGWindowOwnerPID")
        num = w.get("kCGWindowNumber")
        b = w.get("kCGWindowBounds") or {}
        width = int(b.get("Width", 0))
        height = int(b.get("Height", 0))
        if pid is None or num is None or width <= 0 or height <= 0:
            continue
        out.append(WindowRecord(
            pid=int(pid),
            window_id=int(num),
            owner=str(owner),
            bounds=(int(b.get("X", 0)), int(b.get("Y", 0)), width, height),
        ))
    return out


# ANSI hardware virtual keycodes from <HIToolbox/Events.h>. Covers the movement
# keyset plus the keys the spike exercises (chat letters, Return/Escape/Delete/Space).
_VK = {
    "a": 0x00, "s": 0x01, "d": 0x02, "f": 0x03, "h": 0x04, "g": 0x05,
    "z": 0x06, "x": 0x07, "c": 0x08, "v": 0x09, "b": 0x0B, "q": 0x0C,
    "w": 0x0D, "e": 0x0E, "r": 0x0F, "y": 0x10, "t": 0x11,
    "o": 0x1F, "u": 0x20, "i": 0x22, "p": 0x23, "l": 0x25, "j": 0x26,
    "k": 0x28, "n": 0x2D, "m": 0x2E,
    "1": 0x12, "2": 0x13, "3": 0x14, "4": 0x15, "5": 0x17,
    "6": 0x16, "7": 0x1A, "8": 0x1C, "9": 0x19, "0": 0x1D,
    "space": 0x31, "return": 0x24, "escape": 0x35, "delete": 0x33, "tab": 0x30,
    "up": 0x7E, "down": 0x7D, "left": 0x7B, "right": 0x7C,
}


def vk_for_key(name: str) -> int:
    """Map a key name (single char or 'up'/'return'/etc.) to a CGKeyCode.

    Case-insensitive. Raises KeyError for unmapped keys.
    """
    return _VK[name.lower()]


def call_pynput_handler(handler):
    """Wrap a `handler(key, injected)` so it works under pynput 1.7 and 1.8.

    pynput 1.8 invokes callbacks as cb(key, injected); 1.7 as cb(key). The
    returned callable accepts either and always forwards (key, injected) with
    injected defaulting to False on 1.7.
    """
    def _cb(key, injected=False):
        return handler(key, injected)
    return _cb


def is_spike_event(user_data: int) -> bool:
    """True if a kCGEventSourceUserData value marks one of our injected events."""
    return user_data == SPIKE_EVENT_TAG


# The TTR local API binds to loopback; only loopback-bound listeners are the
# game's API. Wildcard (0.0.0.0/::) and LAN-bound sockets are excluded so an
# unrelated socket on a TTR PID is never mistaken for the API port.
def _is_loopback(ip) -> bool:
    """True for any IPv4 127.0.0.0/8 address or the IPv6 loopback ::1."""
    return isinstance(ip, str) and (ip == "::1" or ip.startswith("127."))


def resolve_port_pid_window(connections, windows) -> dict:
    """Map listening loopback ports owned by TTR PIDs to (pid, window_id).

    `connections` are psutil-sconn-like (`.pid`, `.laddr` with `.ip`/`.port`,
    `.status`). `windows` are WindowRecords. A TTR PID with multiple windows
    takes the first. Only loopback-bound LISTEN sockets are considered.
    """
    pid_to_window = {}
    for w in windows:
        pid_to_window.setdefault(w.pid, w.window_id)
    mapping = {}
    for c in connections:
        if c.status != "LISTEN":
            continue
        pid = c.pid
        if pid not in pid_to_window:
            continue
        laddr = c.laddr
        ip = getattr(laddr, "ip", None)
        port = getattr(laddr, "port", None)
        if port is None or not _is_loopback(ip):
            continue
        mapping[int(port)] = (int(pid), pid_to_window[pid])
    return mapping


# ── PyObjC harness (lazy imports; only runs on macOS) ────────────────────────
def _quartz():
    """Lazy import of the Quartz bridge (raises on non-macOS)."""
    import Quartz
    return Quartz


def preflight_post_access() -> bool:
    """Whether this process may post synthetic events (Accessibility)."""
    Q = _quartz()
    return bool(Q.CGPreflightPostEventAccess())


def preflight_listen_access() -> bool:
    """Whether this process may listen to events (Input Monitoring)."""
    Q = _quartz()
    return bool(Q.CGPreflightListenEventAccess())


def preflight_screen_recording() -> bool:
    """Whether this process may read OTHER apps' window info / titles.

    On macOS Tahoe, CGWindowListCopyWindowInfo only returns the caller's own
    windows (plus Window Server) unless Screen Recording is granted, so this
    gates whether enumerate_windows can see TTR at all. Returns True on older
    systems where the preflight API is unavailable.
    """
    Q = _quartz()
    fn = getattr(Q, "CGPreflightScreenCaptureAccess", None)
    return True if fn is None else bool(fn())


def process_bundle_id(pid: int):
    """Stable process identity for a PID via NSRunningApplication (or None).

    Used to harden against PID reuse: we record the bundle id at enumeration and
    re-confirm it is unchanged before posting (see pid_alive_and_ttr). This does
    NOT hardcode TTR's bundle id — it checks identity *consistency* for the PID.
    """
    from AppKit import NSRunningApplication
    app = NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
    if app is None:
        return None
    bid = app.bundleIdentifier()
    return str(bid) if bid is not None else None


def frontmost_pid():
    """PID of the frontmost application (NSWorkspace), or None."""
    from AppKit import NSWorkspace
    app = NSWorkspace.sharedWorkspace().frontmostApplication()
    return int(app.processIdentifier()) if app is not None else None


def enumerate_windows() -> list:
    """Return TTR WindowRecords (with bundle_id) from the live window list."""
    Q = _quartz()
    import objc
    with objc.autorelease_pool():
        opts = Q.kCGWindowListOptionOnScreenOnly | Q.kCGWindowListExcludeDesktopElements
        info = Q.CGWindowListCopyWindowInfo(opts, Q.kCGNullWindowID) or []
        recs = identify_ttr_windows(list(info))
        return [dataclasses.replace(r, bundle_id=process_bundle_id(r.pid)) for r in recs]


def _event_source(state_name="combined"):
    # Per spec: combined is primary; private/none are the conditional fallback
    # matrix. HID state is intentionally NOT offered (spec: do not default to it).
    Q = _quartz()
    if state_name == "none":
        return None
    state = {
        "combined": Q.kCGEventSourceStateCombinedSessionState,
        "private": Q.kCGEventSourceStatePrivate,
    }[state_name]
    return Q.CGEventSourceCreate(state)


def pid_alive_and_ttr(pid: int, window_id: int, expected_bundle="__unset__") -> bool:
    """Re-validate immediately before posting: the window still exists, still
    belongs to this PID, and (if a bundle id was captured) the PID's identity is
    unchanged. Guards against PID and window-ID reuse (posting has no failure
    result). `expected_bundle` defaults to a sentinel meaning 'do not check'."""
    for r in enumerate_windows():
        if r.window_id == window_id and r.pid == pid:
            if expected_bundle != "__unset__" and r.bundle_id != expected_bundle:
                return False  # PID reused by a different app
            return True
    return False


def post_key(pid: int, window_id: int, key: str, down: bool,
             source=None, state_name="combined", flags=None,
             expected_bundle="__unset__") -> bool:
    """Post one key event to `pid`, tagged for echo detection. Returns False
    (does not raise) if the target failed re-validation or access is missing."""
    Q = _quartz()
    if not preflight_post_access():
        print("  REFUSED: no post-event access (grant Accessibility)")
        return False
    if not pid_alive_and_ttr(pid, window_id, expected_bundle):
        print(f"  REFUSED: target pid={pid} window_id={window_id} no longer valid")
        return False
    src = source if source is not None else _event_source(state_name)
    ev = Q.CGEventCreateKeyboardEvent(src, vk_for_key(key), bool(down))
    Q.CGEventSetIntegerValueField(ev, Q.kCGEventSourceUserData, SPIKE_EVENT_TAG)
    if flags is not None:
        Q.CGEventSetFlags(ev, flags)
    Q.CGEventPostToPid(pid, ev)
    return True


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print(__doc__)
        return 2
    cmd, rest = argv[0], argv[1:]
    if cmd == "list":
        return cmd_list(rest)
    if cmd == "inject":
        return cmd_inject(rest)
    if cmd == "loop":
        return cmd_loop(rest)
    if cmd == "type":
        return cmd_type(rest)
    if cmd == "map":
        return cmd_map(rest)
    print(__doc__)
    return 2


# Command + PyObjC-harness functions are added by the empirical tasks (8-12, 11b).
def cmd_list(rest):
    screen = preflight_screen_recording()
    print(f"post-access(Accessibility)={preflight_post_access()} "
          f"listen-access(Input Monitoring)={preflight_listen_access()} "
          f"screen-recording={screen}")
    front = frontmost_pid()
    print(f"frontmost_pid={front}")
    recs = enumerate_windows()
    if not recs:
        if not screen:
            print("No TTR windows visible AND Screen Recording is not granted. On "
                  "macOS Tahoe, window enumeration of other apps requires Screen "
                  "Recording — grant it to this terminal and retry.")
        else:
            print("No TTR windows found. Launch Toontown Rewritten first.")
        return 1
    for r in recs:
        x, y, w, h = r.bounds
        mark = " <FRONT>" if r.pid == front else ""
        print(f"pid={r.pid} window_id={r.window_id} pos=({x},{y}) size={w}x{h} "
              f"owner={r.owner!r} bundle={r.bundle_id!r}{mark}")
    return 0


def _parse_opts(rest, defaults):
    """Tiny --flag value parser. defaults is {flag: (type, value)}.

    Returns (positional_args, options_dict). Unknown --flags raise SystemExit.
    """
    out = {k: v for k, (t, v) in defaults.items()}
    i = 0
    pos = []
    while i < len(rest):
        tok = rest[i]
        if tok.startswith("--"):
            name = tok[2:]
            if name not in defaults:
                raise SystemExit(f"unknown option --{name}")
            if i + 1 >= len(rest) or rest[i + 1].startswith("--"):
                raise SystemExit(f"option --{name} requires a value")
            typ = defaults[name][0]
            out[name] = typ(rest[i + 1])
            i += 2
        else:
            pos.append(tok)
            i += 1
    return pos, out


_STATES = ("combined", "private", "none")


def _hold(pid, window_id, key, seconds, state_name):
    """Hold a key for `seconds`, ALWAYS releasing in finally. Returns True only
    if the key-down post succeeded."""
    src = _event_source(state_name)
    ok = False
    try:
        ok = post_key(pid, window_id, key, True, source=src, state_name=state_name)
        time.sleep(seconds)
    finally:
        post_key(pid, window_id, key, False, source=src, state_name=state_name)
    return ok


def cmd_inject(rest):
    pos, opts = _parse_opts(rest, {
        "key": (str, "w"), "reps": (int, 30), "state": (str, "combined"),
    })
    if len(pos) != 2:
        print("usage: inject <pidA> <pidB> [--key w] [--reps 30] [--state combined|private|none]")
        return 2
    if opts["state"] not in _STATES:
        print(f"invalid --state {opts['state']!r}; choose from {'|'.join(_STATES)}")
        return 2
    pidA, pidB = int(pos[0]), int(pos[1])
    if pidA == pidB:
        print("pidA and pidB must differ (background isolation needs two processes).")
        return 2
    wins = {r.pid: r.window_id for r in enumerate_windows()}
    if pidA not in wins or pidB not in wins:
        print(f"pidA/pidB not both present as TTR windows; found {sorted(wins)}")
        return 1
    widA, widB = wins[pidA], wins[pidB]
    key, reps, state = opts["key"], opts["reps"], opts["state"]
    refused = 0  # count posts the backend refused (no access / stale target)

    print(f"[baseline] bring pid={pidB} to FRONT, then watch it move on '{key}'.")
    input("  press Enter when pidB is frontmost... ")
    refused += not _hold(pidB, widB, key, 0.6, state)

    print(f"[central] keep pid={pidA} FRONT; posting '{key}' ONLY to background pid={pidB}.")
    input("  press Enter when pidA is frontmost... ")
    print("  -> expect: pidB moves, pidA does NOT.")
    refused += not _hold(pidB, widB, key, 0.8, state)

    print(f"[reverse] keep pid={pidB} FRONT; posting '{key}' ONLY to background pid={pidA}.")
    input("  press Enter when pidB is frontmost... ")
    print("  -> expect: pidA moves, pidB does NOT.")
    refused += not _hold(pidA, widA, key, 0.8, state)

    print(f"[third-app] bring Finder/Terminal FRONT; posting '{key}' to pid={pidB}.")
    input("  press Enter when a non-game app is frontmost... ")
    print("  -> expect: pidB still moves while neither game is frontmost.")
    refused += not _hold(pidB, widB, key, 0.8, state)

    print(f"[stress] {reps} alternating taps/holds to background pid={pidB}.")
    input("  press Enter to start the stress loop... ")
    for n in range(reps):
        src = _event_source(state)
        try:
            if not post_key(pidB, widB, key, True, source=src, state_name=state):
                refused += 1
            time.sleep(0.05 if n % 2 else 0.25)
        finally:
            post_key(pidB, widB, key, False, source=src, state_name=state)
    print("  -> expect: no stuck key after the loop (tap 'key' in pidB to confirm released).")

    if refused:
        print(f"WARNING: {refused} post(s) were REFUSED (no access / stale target). "
              f"Grant Accessibility and re-check the results above.")
    return 0


def cmd_loop(rest):
    raise NotImplementedError


def cmd_type(rest):
    raise NotImplementedError


def cmd_map(rest):
    raise NotImplementedError


if __name__ == "__main__":
    raise SystemExit(main())
