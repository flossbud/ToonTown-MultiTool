"""One running copy of the app per user and config directory.

A second copy would hook the keyboard again and draw a second set of strips
over the same game windows, while the first kept sending its own key table.
With the launchpad hiding to the tray while toons are up, starting the app
again from its shortcut is an easy way to get there. So a start that finds a
copy already running for the same user and the same (resolved) config
directory asks that copy to show its window and exits instead.

Two pieces:
- The lock file (instance.lock in the config directory, a QLockFile) is what
  makes a copy THE copy. Its holder keeps it open for the life of the process
  (a handle without delete sharing on Windows, flock on Unix), so a lock whose
  holder has died can be taken over and a live holder's cannot.
- A local server, named from a hash of the user and the config directory, is
  only the messenger: a later start connects and writes "show"; the installer
  and the update window write "quit" (the copy answers "bye" and quits as the
  tray's Quit does). It is created
  for the user's own account only (UserAccessOption): on Windows that is a
  pipe DACL for the token's user SID, which the elevated and the unelevated
  tokens of an administrator share, so an unelevated start can reach a copy
  running as administrator.

Hand-overs are not second copies. The administrator relaunch (at startup, or
"Restart as administrator" in a running window) and the Flatpak restart after
an update pass the old process's pid with --handover-from; the new process
waits for that process to let go of the lock and never asks it to show. The
restart after a source update execs in place: same pid, and the exec dropped
the old image's file lock, so the lock it finds under its own pid is taken
over at once. The venv re-exec supervisor exits at import, before main.py
gets here, so it never holds the lock.

The no-window modes (--self-check, --ghost-renderer, ...) never take or check
the lock.
"""
from __future__ import annotations

import getpass
import hashlib
import os
import sys
import time
from typing import Callable, NamedTuple

OWNER = "owner"              # this process is the copy
SHOWN = "shown"              # another copy runs and was asked to show its window
UNREACHABLE = "unreachable"  # another copy holds the lock and did not answer
UNGUARDED = "unguarded"      # the lock could not be used at all: run anyway

LOCK_FILE = "instance.lock"
HANDOVER_WAIT_S = 20.0       # an exiting predecessor's shutdown, generously
CONNECT_WAIT_S = 4.0         # a copy that is still starting has no server yet
POLL_S = 0.1
ANSWER_WAIT_MS = 3000

SHOW_REQUEST = b"show\n"
SHOW_ANSWER = b"ok\n"
QUIT_REQUEST = b"quit\n"       # utils/rollcall/winplat.py ask_quit sends it
QUIT_ANSWER = b"bye\n"
QUIT_DELAY_MS = 100            # the answer leaves before the shutdown starts

_ASFW_ANY = 0xFFFFFFFF


class Claim(NamedTuple):
    state: str
    holder: int | None = None    # the running copy's pid, when known
    reason: str = ""

    def line(self) -> str:
        """The one line a start that does not go ahead prints."""
        pid = f" (pid {self.holder})" if self.holder else ""
        if self.state == SHOWN:
            return "[NextUI] already running: asked the running copy to show its window"
        if self.state == UNREACHABLE:
            why = self.reason or "it did not answer"
            return (f"[NextUI] already running{pid}, but {why}: "
                    "not starting a second copy")
        if self.state == UNGUARDED:
            return (f"[NextUI] the single-copy lock is unavailable ({self.reason}): "
                    "starting without it")
        return ""


# ── Names ──────────────────────────────────────────────────────────────────

def current_user() -> str:
    try:
        return getpass.getuser()
    except Exception:  # noqa: BLE001 (no login name in the environment)
        return str(getattr(os, "getuid", lambda: "user")())


def resolved_dir(path: str) -> str:
    return os.path.normcase(os.path.realpath(path))


def server_name(config_dir: str, user: str, *, platform: str | None = None,
                environ=None) -> str:
    """The messenger's name for this user and config directory. A Windows
    pipe name; elsewhere a socket path in the user's runtime directory when
    there is one (inside Flatpak, the part of it all instances of the app
    share), else a name Qt puts in the temp directory."""
    platform = sys.platform if platform is None else platform
    environ = os.environ if environ is None else environ
    key = hashlib.sha256(f"{user}\0{resolved_dir(config_dir)}".encode("utf-8"))
    base = f"ttmt-{key.hexdigest()[:24]}"
    if platform == "win32":
        return base
    runtime = environ.get("XDG_RUNTIME_DIR", "")
    if runtime and os.path.isdir(runtime):
        app_id = environ.get("FLATPAK_ID", "")
        shared = os.path.join(runtime, "app", app_id) if app_id else ""
        if shared and os.path.isdir(shared):
            runtime = shared
        return os.path.join(runtime, base + ".sock")
    return base


def is_window_run(argv) -> bool:
    """False for the modes that never open a window."""
    from utils.win32_elevation import NO_WINDOW_FLAGS
    return not any(tok.split("=", 1)[0] in NO_WINDOW_FLAGS for tok in argv)


def handover_arg() -> str:
    """The argument that makes a process started by this one its successor."""
    from utils.win32_elevation import HANDOVER_FLAG
    return f"{HANDOVER_FLAG}={os.getpid()}"


def predecessor_of(argv) -> int | None:
    """The pid passed with --handover-from, if any."""
    from utils.win32_elevation import HANDOVER_FLAG
    for tok in argv:
        name, _, value = tok.partition("=")
        if name == HANDOVER_FLAG:
            try:
                pid = int(value)
            except ValueError:
                return None
            return pid if pid > 0 else None
    return None


# ── The lock ───────────────────────────────────────────────────────────────

class QtLock:
    """The lock file, as the claim below uses it."""

    def __init__(self, path: str):
        from PySide6.QtCore import QLockFile
        self._lock = QLockFile(path)
        self._lock.setStaleLockTime(0)        # stale only when its holder is gone

    def try_lock(self) -> bool:
        # Takes over a lock whose holder Qt can tell is gone.
        return bool(self._lock.tryLock(0))

    def held_by_another(self) -> bool:
        from PySide6.QtCore import QLockFile
        return self._lock.error() == QLockFile.LockError.LockFailedError

    def error_text(self) -> str:
        return self._lock.error().name

    def holder_pid(self) -> int | None:
        try:
            info = self._lock.getLockInfo()
        except Exception:  # noqa: BLE001
            return None
        values = info if isinstance(info, (tuple, list)) else (info,)
        pid = next((v for v in values if isinstance(v, int) and not isinstance(v, bool)), 0)
        return pid if pid > 0 else None

    def remove_if_dead(self) -> bool:
        # Fails while the holder is alive: it keeps the file open (Windows)
        # or flocked (Unix). Catches a dead holder whose pid was reused.
        return bool(self._lock.removeStaleLockFile())

    def unlock(self) -> None:
        self._lock.unlock()


def claim(lock, ask: Callable[[int | None], bool], *,
          predecessor: int | None = None,
          clock: Callable[[], float] = time.monotonic,
          sleep: Callable[[float], None] = time.sleep,
          wait_s: float = HANDOVER_WAIT_S,
          own_pid: int | None = None) -> Claim:
    """Take the lock, or find out who has it.

    An ordinary start looks once. A hand-over (predecessor set) waits while
    the predecessor holds the lock; the moment anyone else holds it (an
    ordinary start that won the gap, or a copy that was already running) it
    stops waiting and asks that copy to show itself, so whichever start wins,
    one copy runs."""
    own_pid = os.getpid() if own_pid is None else own_pid
    deadline = clock() + (wait_s if predecessor is not None else 0.0)
    while True:
        if lock.try_lock():
            return Claim(OWNER)
        if not lock.held_by_another():
            return Claim(UNGUARDED, reason=lock.error_text())
        holder = lock.holder_pid()
        if holder == own_pid and lock.remove_if_dead() and lock.try_lock():
            # This process's own lock from before an exec: Qt sees its pid
            # running, but the file lock went with the old image.
            return Claim(OWNER, reason="took over this process's lock from before an exec")
        waiting_on_predecessor = predecessor is not None and holder in (None, predecessor)
        if not waiting_on_predecessor or clock() >= deadline:
            break
        sleep(POLL_S)
    if predecessor is not None and holder == predecessor:
        return Claim(UNREACHABLE, holder,
                     f"the copy this one replaces has not exited after {wait_s:.0f} s")
    if ask(holder):
        return Claim(SHOWN, holder)
    if lock.remove_if_dead() and lock.try_lock():
        return Claim(OWNER, reason="took over the lock of a copy that is gone")
    return Claim(UNREACHABLE, holder)


# ── The messenger ──────────────────────────────────────────────────────────

def allow_foreground(pid: int | None, *, platform: str | None = None) -> bool:
    """Windows only gives the foreground to a process the foreground process
    allows: let the running copy bring its window to the front."""
    platform = sys.platform if platform is None else platform
    if platform != "win32":
        return False
    try:
        import ctypes
        from ctypes import wintypes
        fn = ctypes.windll.user32.AllowSetForegroundWindow
        fn.argtypes = [wintypes.DWORD]
        fn.restype = wintypes.BOOL
        return bool(fn(pid if pid else _ASFW_ANY))
    except Exception:  # noqa: BLE001
        return False


def ask_to_quit(name: str, *, wait_ms: int = ANSWER_WAIT_MS) -> bool:
    """Ask the running copy to quit. True once it said it will. (Roll Call
    sends the same request through its own pipe client on Windows.)"""
    from PySide6.QtNetwork import QLocalSocket
    sock = QLocalSocket()
    sock.connectToServer(name)
    if not sock.waitForConnected(1000):
        sock.abort()
        return False
    sock.write(QUIT_REQUEST)
    sock.waitForBytesWritten(1000)
    answer = b""
    if sock.waitForReadyRead(wait_ms):
        answer = bytes(sock.readAll())
    sock.abort()
    return answer.startswith(QUIT_ANSWER.strip())


def ask_to_show(name: str, holder: int | None = None, *,
                connect_wait_s: float = CONNECT_WAIT_S,
                clock: Callable[[], float] = time.monotonic,
                sleep: Callable[[float], None] = time.sleep) -> bool:
    """Ask the running copy to show its window. True once it answered. Keeps
    trying for a few seconds: a copy that is still starting takes the lock
    before its server is up. Needs no QCoreApplication."""
    from PySide6.QtNetwork import QLocalSocket
    allow_foreground(holder)
    deadline = clock() + connect_wait_s
    while True:
        sock = QLocalSocket()
        sock.connectToServer(name)
        if sock.waitForConnected(500):
            sock.write(SHOW_REQUEST)
            sock.waitForBytesWritten(1000)
            answer = b""
            if sock.waitForReadyRead(ANSWER_WAIT_MS):
                answer = bytes(sock.readAll())
            sock.abort()
            return answer.startswith(SHOW_ANSWER.strip())
        sock.abort()
        if clock() >= deadline:
            return False
        sleep(0.25)


class InstanceGuard:
    """The single-copy guard for one config directory."""

    def __init__(self, config_dir: str, *, user: str | None = None,
                 lock_factory=QtLock, platform: str | None = None, environ=None):
        self.config_dir = os.path.realpath(config_dir)
        self.lock_path = os.path.join(self.config_dir, LOCK_FILE)
        self.name = server_name(self.config_dir, user or current_user(),
                                platform=platform, environ=environ)
        self._lock_factory = lock_factory
        self._lock = None
        self._server = None
        self._on_show = None
        self._asked_early = 0
        self._on_quit = None
        self._quit_asked_early = False

    @property
    def owned(self) -> bool:
        return self._lock is not None

    def claim(self, predecessor: int | None = None, **kwargs) -> Claim:
        try:
            os.makedirs(self.config_dir, exist_ok=True)
            lock = self._lock_factory(self.lock_path)
        except Exception as exc:  # noqa: BLE001
            return Claim(UNGUARDED, reason=str(exc))
        result = claim(lock, lambda pid: ask_to_show(self.name, pid),
                       predecessor=predecessor, **kwargs)
        if result.state == OWNER:
            self._lock = lock
        return result

    def listen(self) -> bool:
        """Start answering later starts. Needs the QApplication."""
        if self._lock is None or self._server is not None:
            return False
        from PySide6.QtNetwork import QLocalServer
        server = QLocalServer()
        server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        # A socket file a dead copy left behind; the lock says it is ours now.
        QLocalServer.removeServer(self.name)
        if not server.listen(self.name):
            print(f"[NextUI] single-copy messenger did not start: {server.errorString()}")
            return False
        server.newConnection.connect(self._on_connection)
        self._server = server
        return True

    def on_show(self, handler: Callable[[], None]) -> None:
        """What to do when another start asks for the window. A request that
        came before there was a window is carried out now."""
        self._on_show = handler
        if self._asked_early:
            self._asked_early = 0
            self._show()

    def on_quit(self, handler: Callable[[], None]) -> None:
        """What to do when the installer asks this copy to quit. A request
        that came before there was a window is carried out now."""
        self._on_quit = handler
        if self._quit_asked_early:
            self._quit_asked_early = False
            self._quit()

    def release(self) -> None:
        if self._server is not None:
            self._server.close()
            self._server = None
        if self._lock is not None:
            self._lock.unlock()
            self._lock = None

    def _on_connection(self) -> None:
        server = self._server
        while server is not None and server.hasPendingConnections():
            sock = server.nextPendingConnection()
            sock.readyRead.connect(lambda s=sock: self._read(s))
            sock.disconnected.connect(sock.deleteLater)
            if sock.bytesAvailable():
                self._read(sock)

    def _read(self, sock) -> None:
        data = bytes(sock.readAll())
        if QUIT_REQUEST.strip() in data:
            sock.write(QUIT_ANSWER)
            sock.flush()
            sock.disconnectFromServer()
            print("[NextUI] the installer asked this copy to quit")
            if self._on_quit is None:
                self._quit_asked_early = True
            else:
                from PySide6.QtCore import QTimer
                QTimer.singleShot(QUIT_DELAY_MS, self._quit)
            return
        if SHOW_REQUEST.strip() not in data:
            return
        sock.write(SHOW_ANSWER)
        sock.flush()
        sock.disconnectFromServer()
        print("[NextUI] another start asked this copy to show its window")
        if self._on_show is None:
            self._asked_early += 1
        else:
            self._show()

    def _show(self) -> None:
        try:
            self._on_show()
        except Exception as exc:  # noqa: BLE001
            print(f"[NextUI] could not show the window for another start: {exc}")

    def _quit(self) -> None:
        if self._on_quit is None:
            return
        try:
            self._on_quit()
        except Exception as exc:  # noqa: BLE001
            print(f"[NextUI] could not quit for the installer: {exc}")


# ── Startup ────────────────────────────────────────────────────────────────

class Startup(NamedTuple):
    guard: InstanceGuard | None
    elevation: object
    exit_code: int | None        # set when this process must exit now


def run_startup(argv, elevate, *, make_guard=None, out=print) -> Startup:
    """The start of main.py, in order: the single-copy claim, then the
    administrator step. A window run claims the lock BEFORE elevation, so a
    second start never shows a UAC prompt first. If the elevated copy is
    started, the lock is released for it to take over; if the prompt was
    declined or failed, this process carries on and keeps the lock."""
    from utils.win32_elevation import RELAUNCHED
    if not is_window_run(argv):
        return Startup(None, elevate(), None)
    if make_guard is None:
        from utils.build_flavor import config_dir
        guard = InstanceGuard(config_dir())
    else:
        guard = make_guard()
    result = guard.claim(predecessor=predecessor_of(argv))
    if result.state in (SHOWN, UNREACHABLE):
        out(result.line())
        return Startup(None, None, 0)
    if result.state == UNGUARDED:
        out(result.line())
    elevation = elevate()
    if getattr(elevation, "state", None) == RELAUNCHED:
        guard.release()                     # the elevated copy takes it over
        return Startup(None, elevation, 0)
    return Startup(guard, elevation, None)
