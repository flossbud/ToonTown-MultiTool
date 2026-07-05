"""App-side client for the ghost-renderer helper process (see
utils/ghost_renderer.py and ledger CP17).

Spawns `<this app> --ghost-renderer` and feeds it over stdin. Position
writes happen on the CAPTURE THREAD (a Qt DirectConnection on the service's
ghost signal), so they must NEVER block: the pipe fd is O_NONBLOCK and a
full pipe DROPS the line (display-only data - the newest position
supersedes everything anyway; a stalled renderer must not stall capture).
A broken pipe marks the client dead; the ghost controller falls back to
in-process rendering on the next event.

Lifecycle: the renderer exits on stdin EOF, so it can never outlive the
app even on a hard kill; stop() sends the polite Q first. atexit closes
the pipe as a belt for exit paths that skip the controller.
"""
from __future__ import annotations

import atexit
import os
import subprocess
import sys
import threading

from utils import ghost_feed_protocol as proto


def _spawn_command() -> list[str]:
    """The command that re-enters THIS app as the renderer. Frozen builds
    re-exec their own binary (the --self-check precedent); source runs go
    through main.py with the venv re-exec disarmed (the client already
    runs on the right interpreter)."""
    if getattr(sys, "frozen", False):
        return [sys.executable, "--ghost-renderer"]
    main_py = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "main.py")
    return [sys.executable, main_py, "--ghost-renderer"]


class GhostRendererClient:
    def __init__(self):
        self._proc = None
        self._fd = None
        self._dead = False
        self._lock = threading.Lock()   # GUI control + capture positions
        self.dropped = 0                # full-pipe drops (diagnostic)

    @property
    def pid(self):
        return self._proc.pid if self._proc is not None else None

    def start(self) -> bool:
        """Spawn the renderer. False on any failure (caller stays
        in-process). stdout/stderr inherit so the renderer's stamps land
        in the app log."""
        try:
            env = dict(os.environ)
            env["TTMT_NO_VENV_REEXEC"] = "1"
            self._proc = subprocess.Popen(
                _spawn_command(), stdin=subprocess.PIPE,
                stdout=None, stderr=None, env=env)
            fd = self._proc.stdin.fileno()
            # fcntl is Unix-only; the renderer only ever spawns on real cocoa
            # (darwin), so import at USE, never at module level - the frozen
            # Windows self-check imports every module and a top-level import
            # broke it (ModuleNotFoundError: fcntl, CI 2026-07-05).
            import fcntl
            fcntl.fcntl(fd, fcntl.F_SETFL,
                        fcntl.fcntl(fd, fcntl.F_GETFL) | os.O_NONBLOCK)
            self._fd = fd
            atexit.register(self.stop)
            return True
        except Exception as e:                        # noqa: BLE001
            print(f"[GhostRenderer] spawn failed: {e}")
            self._proc = None
            self._fd = None
            self._dead = True
            return False

    def alive(self) -> bool:
        return (not self._dead and self._proc is not None
                and self._proc.poll() is None)

    # -- feed (any thread; never blocks) --------------------------------

    def send_positions(self, points, t_ms=None) -> bool:
        """points: iterable of (slot, x, y, wid); t_ms = the batch's EVENT
        time (capture stamp, monotonic-basis ms). One write per batch."""
        data = "".join(proto.encode_position(s, x, y, w, t_ms)
                       for s, x, y, w in points)
        return self._write(data)

    def send_focus(self, wid) -> bool:
        return self._write(proto.encode_focus(wid))

    def send_clear(self) -> bool:
        return self._write(proto.encode_clear())

    def _write(self, data: str) -> bool:
        if self._dead or self._fd is None:
            return False
        try:
            with self._lock:
                os.write(self._fd, data.encode("ascii"))
            return True
        except BlockingIOError:
            self.dropped += 1
            return True    # renderer alive but momentarily behind: drop
        except OSError:
            self._dead = True   # broken pipe: renderer died
            return False

    # -- lifecycle -------------------------------------------------------

    def stop(self) -> None:
        proc, self._proc = self._proc, None
        fd, self._fd = self._fd, None
        self._dead = True
        if proc is None:
            return
        try:
            if fd is not None:
                try:
                    os.write(fd, proto.encode_quit().encode("ascii"))
                except OSError:
                    pass
                try:
                    proc.stdin.close()   # EOF: the renderer's hard signal
                except OSError:
                    pass
            proc.wait(timeout=2.0)
        except Exception:                              # noqa: BLE001
            try:
                proc.terminate()
                proc.wait(timeout=1.0)
            except Exception:
                pass
