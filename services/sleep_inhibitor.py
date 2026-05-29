"""System sleep + screen-lock inhibition for the Keep-Alive feature.

Holds OS-level locks so the machine neither sleeps nor locks the screen while
Keep-Alive runs. Cross-desktop on Linux (KDE, GNOME, others) via the XDG
Inhibit portal, with a session/system-bus fallback; SetThreadExecutionState on
Windows.

OS access goes through the module-level seams `_is_windows`, `_session_bus`,
`_system_bus`, `_kernel32`, and `_close_fd` so tests can inject fakes without
touching a real bus or the Win32 API. `import dbus` is kept lazy because dbus
is not importable on Windows.
"""

import sys

APP_NAME = "ToonTown MultiTool"
REASON = "Keep-Alive is active"

# Win32 SetThreadExecutionState flags.
ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
ES_DISPLAY_REQUIRED = 0x00000002

# XDG Inhibit portal flags: Suspend (4) | Idle (8).
PORTAL_SUSPEND_IDLE = 0x4 | 0x8


# ── Seams (monkeypatched in tests) ─────────────────────────────────────────
def _is_windows():
    return sys.platform == "win32"


def _session_bus():
    import dbus
    return dbus.SessionBus()


def _system_bus():
    import dbus
    return dbus.SystemBus()


def _kernel32():
    import ctypes
    return ctypes.windll.kernel32


def _close_fd(fd):
    import os
    os.close(fd)


class SleepInhibitor:
    """Acquire/release OS inhibition locks. Idempotent; release never raises."""

    def __init__(self):
        # Each entry is (label, release_callable). Holding more than one lock
        # is normal in the Linux fallback path.
        self._releases = []
        self.active_tier = None
        self._acquired = False

    def is_active(self):
        return bool(self._releases)

    def acquire(self):
        """Acquire inhibition. Returns a tier name string, or None if nothing
        could be acquired. Calling again while already held is a no-op."""
        if self._acquired:
            return self.active_tier
        self._acquired = True
        if _is_windows():
            self.active_tier = self._acquire_windows()
        else:
            self.active_tier = self._acquire_linux()
        return self.active_tier

    def release(self):
        """Release every held lock. Safe to call when nothing is held."""
        releases = list(self._releases)
        self._releases.clear()
        self._acquired = False
        self.active_tier = None
        for _label, thunk in releases:
            try:
                thunk()
            except Exception:
                pass

    # ── Windows ────────────────────────────────────────────────────────────
    def _acquire_windows(self):
        try:
            _kernel32().SetThreadExecutionState(
                ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED
            )
            self._releases.append(
                ("windows",
                 lambda: _kernel32().SetThreadExecutionState(ES_CONTINUOUS))
            )
            return "windows"
        except Exception:
            return None

    # ── Linux ───────────────────────────────────────────────────────────────
    def _acquire_linux(self):
        if self._acquire_portal():
            return "portal"
        tiers = []
        if self._acquire_screensaver():
            tiers.append("screensaver")
        if self._acquire_login1():
            tiers.append("login1")
        return "+".join(tiers) if tiers else None

    def _acquire_portal(self):
        return False

    def _acquire_screensaver(self):
        return False

    def _acquire_login1(self):
        return False
