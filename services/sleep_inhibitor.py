"""System sleep + screen-lock inhibition for the Keep-Alive feature.

Holds OS-level locks so the machine neither sleeps nor locks the screen while
Keep-Alive runs. On Linux the primary, verified layer is a `systemd-inhibit
--what=sleep:idle --mode=block` holder subprocess released via pipe-EOF and
verified by finding a per-acquire UUID token in `systemd-inhibit --list`, with
a QtDBus login1 fallback and a best-effort QtDBus ScreenSaver cookie;
SetThreadExecutionState on Windows.

OS access goes through module-level seams (`_is_windows`, `_kernel32`,
`_uuid_token`, `_popen_holder`, `_close_write_fd`, `_reap`, `_run_list`, and
the QtDBus seams) so tests can inject fakes without spawning a real holder or
touching a real bus.
"""

import os
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass

APP_NAME = "ToonTown MultiTool"
REASON = "Keep-Alive is active"

# Win32 SetThreadExecutionState flags.
ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
ES_DISPLAY_REQUIRED = 0x00000002

# XDG Inhibit portal flags: Suspend (4) | Idle (8).
PORTAL_SUSPEND_IDLE = 0x4 | 0x8

# Verification budget: per-call timeout and overall wall-clock deadline.
# Each `systemd-inhibit --list` call is bounded below the overall poll deadline
# so a single slow/hung call cannot blow the whole budget.
_LIST_CALL_TIMEOUT = 0.5      # seconds, each `systemd-inhibit --list`
_VERIFY_DEADLINE = 1.5        # seconds, total poll budget (worker thread)
_VERIFY_INTERVAL = 0.1        # seconds between polls
_REAP_TIMEOUT = 1.0           # seconds to wait for holder/wrapper to die


@dataclass
class InhibitStatus:
    sleep_blocked: bool = False
    screen_lock_cookie_held: bool = False
    method: str = ""    # "systemd" | "login1" | ""
    detail: str = ""    # optional human-readable reason for logs/warning text


# ── Seams (monkeypatched in tests) ─────────────────────────────────────────
def _is_windows():
    return sys.platform == "win32"


def _kernel32():
    import ctypes
    return ctypes.windll.kernel32


def _uuid_token():
    return uuid.uuid4().hex


def _popen_holder(token):
    """Spawn `systemd-inhibit ... -- cat` with a parent-owned pipe as the
    holder's stdin. Returns (proc, write_fd). Closing write_fd (or process
    death) sends EOF to cat, which exits and releases the logind lock.

    `host_popen` applies `flatpak-spawn --host` wrapping internally when
    sandboxed, so argv is passed unwrapped."""
    r_fd, w_fd = os.pipe()
    argv = [
        "systemd-inhibit", "--what=sleep:idle", "--mode=block",
        f"--who={APP_NAME}", f"--why={REASON} [{token}]",
        "--", "cat",
    ]
    from utils.host_spawn import host_popen
    try:
        proc = host_popen(argv, stdin=r_fd, pass_fds=(r_fd,))
    except BaseException:
        # Spawn failed after the pipe was created (missing binary, sandbox
        # denial, ENOMEM): close both ends so neither fd leaks, then re-raise
        # so the caller can degrade to the fallback. Close both defensively so
        # a failing read-fd close cannot skip the write-fd close.
        _close_write_fd(r_fd)
        _close_write_fd(w_fd)
        raise
    os.close(r_fd)  # parent keeps only the write end
    return proc, w_fd


def _close_write_fd(fd):
    try:
        os.close(fd)
    except OSError:
        pass


def _reap(proc):
    try:
        proc.wait(timeout=_REAP_TIMEOUT)
    except subprocess.TimeoutExpired:
        try:
            proc.kill()
            proc.wait(timeout=_REAP_TIMEOUT)
        except Exception:
            pass


def _run_list(timeout=_LIST_CALL_TIMEOUT):
    """Return `systemd-inhibit --list` text (LC_ALL=C, host-routed under
    Flatpak). Empty string on any failure. `timeout` is bounded by the caller
    to the remaining verify budget so a single call cannot overrun it."""
    from utils.host_spawn import host_run
    env = dict(os.environ)
    env["LC_ALL"] = "C"
    try:
        cp = host_run(
            ["systemd-inhibit", "--list", "--no-pager", "--no-legend"],
            capture_output=True, text=True, timeout=timeout, env=env,
        )
        return cp.stdout or ""
    except Exception:
        return ""


def _close_fd(fd):
    try:
        os.close(fd)
    except OSError:
        pass


def _fd_open(fd):
    try:
        os.fstat(fd)
        return True
    except OSError:
        return False


def _qt_login1_inhibit(who, why):
    """Call login1.Manager.Inhibit('sleep:idle', who, why, 'block') over
    QtDBus on the application-lifetime system bus, dup the returned unix fd
    out of the wrapper, and return the duped int (or None)."""
    from PySide6.QtDBus import (
        QDBusConnection, QDBusInterface, QDBusUnixFileDescriptor,
    )
    bus = QDBusConnection.systemBus()
    iface = QDBusInterface("org.freedesktop.login1", "/org/freedesktop/login1",
                           "org.freedesktop.login1.Manager", bus)
    if not iface.isValid():
        return None
    iface.setTimeout(3000)  # ms; never block the worker on a slow system bus
    reply = iface.call("Inhibit", "sleep:idle", who, why, "block")
    args = reply.arguments()
    if not args or not isinstance(args[0], QDBusUnixFileDescriptor):
        return None
    qfd = args[0]
    if not qfd.isValid():
        return None
    return os.dup(qfd.fileDescriptor())  # survives qfd GC


def _qt_login1_list_inhibitors():
    """Return login1 ListInhibitors() rows as (what, who, why, mode) tuples.
    Returns [] on a D-Bus error reply or a structurally unexpected row, so a
    malformed reply is treated as 'not verified' rather than raising."""
    from PySide6.QtDBus import QDBusConnection, QDBusInterface
    bus = QDBusConnection.systemBus()
    iface = QDBusInterface("org.freedesktop.login1", "/org/freedesktop/login1",
                           "org.freedesktop.login1.Manager", bus)
    iface.setTimeout(3000)  # ms; bound verification too, not just Inhibit()
    reply = iface.call("ListInhibitors")
    if reply.errorName():
        return []
    args = reply.arguments()
    rows = []
    for entry in (args[0] if args else []):
        # (what, who, why, mode, uid, pid)
        try:
            rows.append((entry[0], entry[1], entry[2], entry[3]))
        except (IndexError, TypeError):
            continue
    return rows


def _session_bus():
    import dbus
    return dbus.SessionBus()


def _system_bus():
    import dbus
    return dbus.SystemBus()


class SleepInhibitor:
    """Acquire/release OS inhibition locks. Idempotent; release never raises."""

    def __init__(self):
        # Each entry is (label, release_callable). Holding more than one lock
        # is normal in the Linux fallback path.
        self._releases = []
        self.active_tier = None
        self._acquired = False
        self._token = None
        self.status = InhibitStatus()

    def is_active(self):
        return bool(self.status.sleep_blocked) or self.active_tier == "windows"

    def acquire(self):
        """Acquire inhibition. Returns a tier name string, or None if nothing
        could be acquired. Re-acquiring releases first so locks never stack."""
        if self._acquired:
            self.release()  # release-before-acquire: never stack locks
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
        self.status = InhibitStatus()  # nothing held -> is_active() reads False
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
        self.status = InhibitStatus()
        self._acquire_sleep_layer()                # sets release thunks + status
        screensaver = self._acquire_screensaver_qtdbus()
        if screensaver is not None:
            self._releases.append(("screensaver", screensaver))
            self.status.screen_lock_cookie_held = True
        if not self.status.sleep_blocked:
            # Screensaver-only must NOT look like success to `if tier:` callers.
            return None
        tiers = [self.status.method]
        if self.status.screen_lock_cookie_held:
            tiers.append("screensaver")
        return "+".join(tiers)

    def _acquire_sleep_layer(self):
        token = self._token = _uuid_token()
        try:
            proc, w_fd = _popen_holder(token)
        except Exception:
            # Spawn failed (no systemd-inhibit/cat, sandbox denial, ENOMEM):
            # degrade to the QtDBus login1 fallback rather than propagating.
            proc = None
        if proc is not None:
            if self._verify_systemd(token):
                self._releases.append(
                    ("systemd",
                     lambda p=proc, fd=w_fd: (_close_write_fd(fd), _reap(p))))
                self.status.sleep_blocked = True
                self.status.method = "systemd"
                return "systemd"
            # Partial-acquire cleanup: EOF the holder, reap both processes.
            _close_write_fd(w_fd)
            _reap(proc)
        fd = self._acquire_login1_qtdbus()
        if fd is not None:
            self._releases.append(("login1", lambda: _close_fd(fd)))
            self.status.sleep_blocked = True
            self.status.method = "login1"
            return "login1"
        return ""

    def _verify_systemd(self, token):
        deadline = time.monotonic() + _VERIFY_DEADLINE
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            # Never start a list call that could run past the overall deadline.
            if token in _run_list(timeout=min(_LIST_CALL_TIMEOUT, remaining)):
                return True
            time.sleep(min(_VERIFY_INTERVAL, max(0.0, deadline - time.monotonic())))

    # QtDBus seams (screensaver implemented in Task 3).
    def _acquire_login1_qtdbus(self):
        """Hold a logind sleep:idle inhibitor over QtDBus, verifying that our
        own per-acquire token shows up in ListInhibitors(). Returns the duped
        fd to hold, or None (closing the fd on any unverified path)."""
        token = self._token  # set by _acquire_sleep_layer before fallback
        try:
            fd = _qt_login1_inhibit(APP_NAME, f"{REASON} [{token}]")
        except Exception:
            return None  # QtDBus error before we own an fd -> nothing to leak
        if fd is None:
            return None
        # From here we own a duped fd; every non-success path must close it and
        # no QtDBus error may propagate out of acquire().
        try:
            if _fd_open(fd):
                for (_what, _who, why, _mode) in _qt_login1_list_inhibitors():
                    if token in (why or ""):
                        return fd
        except Exception:
            pass
        _close_fd(fd)  # unverified, fd closed, or a QtDBus error -> not held
        return None

    def _acquire_screensaver_qtdbus(self):
        return None

    def _acquire_portal(self):
        try:
            import dbus
            bus = _session_bus()
            obj = bus.get_object(
                "org.freedesktop.portal.Desktop",
                "/org/freedesktop/portal/desktop",
            )
            handle = obj.Inhibit(
                "",
                dbus.UInt32(PORTAL_SUSPEND_IDLE),
                {"reason": REASON},
                dbus_interface="org.freedesktop.portal.Inhibit",
            )
            path = str(handle)

            def _close(bus=bus, path=path):
                req = bus.get_object("org.freedesktop.portal.Desktop", path)
                req.Close(dbus_interface="org.freedesktop.portal.Request")

            self._releases.append(("portal", _close))
            return True
        except Exception:
            return False

    def _acquire_screensaver(self):
        try:
            bus = _session_bus()
            obj = bus.get_object(
                "org.freedesktop.ScreenSaver", "/org/freedesktop/ScreenSaver"
            )
            cookie = obj.Inhibit(
                APP_NAME, REASON,
                dbus_interface="org.freedesktop.ScreenSaver",
            )

            def _uninhibit(bus=bus, cookie=cookie):
                o = bus.get_object(
                    "org.freedesktop.ScreenSaver", "/org/freedesktop/ScreenSaver"
                )
                o.UnInhibit(cookie, dbus_interface="org.freedesktop.ScreenSaver")

            self._releases.append(("screensaver", _uninhibit))
            return True
        except Exception:
            return False

    def _acquire_login1(self):
        try:
            bus = _system_bus()
            obj = bus.get_object(
                "org.freedesktop.login1", "/org/freedesktop/login1"
            )
            fd = obj.Inhibit(
                "sleep:idle", APP_NAME, REASON, "block",
                dbus_interface="org.freedesktop.login1.Manager",
            )
            real_fd = fd.take()
            self._releases.append(
                ("login1", lambda real_fd=real_fd: _close_fd(real_fd))
            )
            return True
        except Exception:
            return False
