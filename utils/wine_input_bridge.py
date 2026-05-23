"""Wine-side input bridge for Wine-hosted Corporate Clash windows.

XSendEvent is enough for native TTR, but Wine game clients (whether
launched via Proton, bottles, lutris, or plain system wine) commonly
ignore background synthetic X11 key events. This bridge compiles and
runs a small managed Windows helper inside the same Wine prefix as CC;
the helper posts Win32 keyboard messages to CC HWNDs directly.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

from utils import x11_discovery
from utils.build_flavor import config_dir


_BRIDGES: dict[str, "WineInputBridge"] = {}
_BRIDGES_LOCK = threading.Lock()
# Prefixes for which bridge setup recently failed. Maps prefix -> monotonic
# timestamp of the failure. Entries expire after _BAD_PREFIX_COOLDOWN, after
# which the bridge will be retried (so a user who fixes their Wine Mono
# install mid-session doesn't have to restart TTMT).
_BAD_PREFIXES: dict[str, float] = {}
_BAD_PREFIX_COOLDOWN = 300.0  # seconds; 5 minutes


def _port_for_prefix(prefix: str) -> int:
    """SHA1-derived per-prefix port. Must stay consistent with
    WineInputBridge.__init__ so the pre-launch sweep targets the same
    port the running helper bound to."""
    return 37377 + (int(hashlib.sha1(prefix.encode("utf-8")).hexdigest()[:6], 16) % 1000)


def _send_quit(port: int) -> None:
    """Best-effort TCP 'quit' to a bridge helper. Used when we don't
    have a WineInputBridge instance for the prefix (orphan from a
    prior TTMT session). Connection errors and timeouts are silent -
    no bridge to quit is the success case, not a failure."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5) as sock:
            sock.sendall(b"quit\n")
            sock.settimeout(0.5)
            try:
                sock.recv(64)
            except OSError:
                pass
    except OSError:
        pass


def shutdown_for_prefix(prefix: str) -> None:
    """Tear down the bridge for a single Wine prefix. Idempotent.

    Two paths:
      1. In-memory: if a WineInputBridge is in _BRIDGES for this prefix,
         pop and shutdown() it (sends 'quit' over TCP AND reaps the
         Linux-side Popen handle).
      2. Orphan: otherwise send 'quit' to the SHA1-derived port. Covers
         bridges left behind by a crashed prior TTMT session whose
         Popen handle is gone but whose .exe is still alive inside
         the Wine prefix, pinning wineserver.

    Either way, the wineserver should drain shortly after, freeing the
    prefix lock so Proton's waitforexitandrun on the next launch
    doesn't block in fcntl_setlk."""
    key = os.path.realpath(prefix.rstrip("/"))
    with _BRIDGES_LOCK:
        bridge = _BRIDGES.pop(key, None)
    if bridge is not None:
        try:
            bridge.shutdown()
        except Exception as e:
            print(f"[wine_input_bridge] shutdown_for_prefix error: {e}")
        return
    _send_quit(_port_for_prefix(key))


def shutdown_all() -> None:
    """Tear down every active bridge. Idempotent; safe to call on app exit."""
    with _BRIDGES_LOCK:
        bridges = list(_BRIDGES.values())
        _BRIDGES.clear()
    for bridge in bridges:
        try:
            bridge.shutdown()
        except Exception as e:
            print(f"[wine_input_bridge] shutdown error: {e}")


def send_to_window(win_id: str, window_ids: list[str], action: str, keysym: str, modifiers=None) -> bool:
    """Send one key action to a CC window via the Wine helper.

    Returns False when the target is not a Wine/Proton CC window or the bridge
    cannot be prepared quickly; callers should fall back to their normal input
    backend in that case.
    """
    try:
        index = [str(w) for w in window_ids].index(str(win_id))
    except ValueError:
        return False

    try:
        from utils.game_registry import GameRegistry
        pid = GameRegistry._get_host_pid_for_window_xres(str(win_id))
    except Exception:
        pid = None
    if pid is None:
        pid = x11_discovery.get_window_pid(str(win_id))
    if pid is None:
        return False

    bridge = _bridge_for_pid(pid)
    if bridge is None:
        return False

    if not bridge.cross_check_sort_order([str(w) for w in window_ids]):
        print(
            f"[wine_input_bridge] sort-order disagreement between X11 and Win32 "
            f"for prefix={bridge.prefix}; falling back to Xlib"
        )
        return False

    active_index = _active_index(window_ids)

    if action == "keydown":
        return bridge.send("down", index, keysym, active_index)
    if action == "keyup":
        return bridge.send("up", index, keysym, active_index)
    if action == "key":
        ok = True
        for mod in modifiers or []:
            mod_key = _modifier_to_keysym(mod)
            if mod_key:
                ok = bridge.send("down", index, mod_key, active_index) and ok
        ok = bridge.send("tap", index, keysym, active_index) and ok
        for mod in reversed(modifiers or []):
            mod_key = _modifier_to_keysym(mod)
            if mod_key:
                ok = bridge.send("up", index, mod_key, active_index) and ok
        return ok
    return False


def _active_index(window_ids: list[str]) -> int:
    active = x11_discovery.get_active_window_id()
    if active is None:
        return -1
    try:
        return [str(w) for w in window_ids].index(str(active))
    except ValueError:
        return -1


def _modifier_to_keysym(modifier: str) -> str | None:
    return {
        "shift": "Shift_L",
        "ctrl": "Control_L",
        "alt": "Alt_L",
    }.get(str(modifier).lower())


def _bridge_for_pid(pid: int) -> "WineInputBridge | None":
    env = _read_process_env(pid)
    prefix = (env.get("WINEPREFIX") or "").rstrip("/")
    compatdata = (env.get("STEAM_COMPAT_DATA_PATH") or "").rstrip("/")
    if not prefix and compatdata:
        prefix = os.path.join(compatdata, "pfx")
    if not prefix:
        return None

    key = os.path.realpath(prefix)
    now = time.monotonic()
    cooldown_at = _BAD_PREFIXES.get(key)
    if cooldown_at is not None:
        if now - cooldown_at < _BAD_PREFIX_COOLDOWN:
            return None
        # Cooldown expired — drop the entry and re-attempt.
        _BAD_PREFIXES.pop(key, None)

    with _BRIDGES_LOCK:
        bridge = _BRIDGES.get(key)
        if bridge is None:
            wine_bin = _wine_bin_for_pid(pid, env)
            if wine_bin is None:
                _BAD_PREFIXES[key] = time.monotonic()
                print(f"[wine_input_bridge] could not resolve wine binary for pid={pid}; bridge disabled for prefix={key}")
                return None
            bridge = WineInputBridge(prefix=key, wine_bin=wine_bin, env=env)
            _BRIDGES[key] = bridge

    if not bridge.ensure_running():
        _BAD_PREFIXES[key] = time.monotonic()
        print(f"[wine_input_bridge] bridge unavailable for prefix={key}; falling back to Xlib for all future CC keys")
        return None
    return bridge


def _read_process_env(pid: int) -> dict[str, str]:
    try:
        raw = Path(f"/proc/{pid}/environ").read_bytes()
    except OSError:
        return {}
    env: dict[str, str] = {}
    for item in raw.split(b"\0"):
        if not item or b"=" not in item:
            continue
        key, value = item.split(b"=", 1)
        name = key.decode("utf-8", "replace")
        if name in {"WINESERVERSOCKET", "WINELOADERNOEXEC"}:
            continue
        env[name] = value.decode("utf-8", "replace")
    return env


# Wine preloader executable basenames that identify a plain-wine
# (non-Proton) game process. Intentionally duplicated from
# utils.game_registry._KNOWN_WINE_HELPERS to avoid coupling this
# bridge module to the GameRegistry singleton over a two-element set.
_PLAIN_WINE_PRELOADERS = {"wine-preloader", "wine64-preloader"}


def _wine_bin_for_pid(pid: int, env: dict[str, str]) -> str | None:
    """Resolve the wine binary path for a running game process.

    Proton path: /proc/<pid>/exe lives under <proton_root>/files/lib/wine/
    (or WINEDLLPATH points at it). The wine binary is then at
    <proton_root>/files/bin/wine.

    Plain-wine path: /proc/<pid>/exe basename is a known wine preloader
    (e.g. wine64-preloader installed by the distro at /usr/lib/wine/).
    Resolve the user-facing wine binary via shutil.which('wine').

    Bottles / Lutris / Faugus path: WINELOADER in the game's env is the
    canonical wine binary that started the running wineserver. Prefer it
    over every other heuristic, since it is the only binary guaranteed
    ABI-compatible with the wineserver this bridge needs to talk to.
    (System wine resolved by shutil.which can disagree on protocol
    version: e.g. wine 11.0 client speaks 931, Bottles soda-9.0 runner
    speaks 787, and the connection aborts with "wine client error:0:
    version mismatch".)

    Returns None for non-wine processes; caller falls back to Xlib.
    """
    loader = env.get("WINELOADER")
    if loader and os.access(loader, os.X_OK):
        return loader

    try:
        exe = os.readlink(f"/proc/{pid}/exe")
    except OSError:
        exe = ""

    marker = "/files/lib/wine/"
    if marker in exe:
        proton_root = exe.split(marker, 1)[0]
        return os.path.join(proton_root, "files", "bin", "wine")

    winedll = env.get("WINEDLLPATH", "")
    for part in winedll.split(":"):
        if part.endswith("/files/lib/wine"):
            proton_root = part[: -len("/files/lib/wine")]
            return os.path.join(proton_root, "files", "bin", "wine")

    if os.path.basename(exe) in _PLAIN_WINE_PRELOADERS:
        return shutil.which("wine")

    return None


def _resource_path(*parts: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    return base.joinpath(*parts)


class WineInputBridge:
    def __init__(self, prefix: str, wine_bin: str, env: dict[str, str]):
        self.prefix = prefix
        self.wine_bin = wine_bin
        self.env = dict(env)
        # Deterministic per-prefix port: SHA1(prefix) mod 1000 added to a base.
        # Tradeoff vs. OS-assigned ports (binding port 0, reading the port from
        # the helper's stdout): the deterministic approach lets Python query
        # the running helper without needing to remember a port across TTMT
        # restarts, and avoids a stdout-pipe lifecycle. Birthday-problem
        # collision math: two prefixes collide with p ~ 0.1%; ten prefixes
        # with p ~ 4.4%. On a collision the second helper's listener.Start()
        # raises SocketException, the process exits, _ping() times out, and
        # the prefix lands in _BAD_PREFIXES (Task 5 added a cooldown so this
        # isn't permanent). If multi-prefix users start hitting collisions
        # in practice, switch to OS-assigned ports + stdout handshake.
        self.port = _port_for_prefix(prefix)
        self._process: subprocess.Popen | None = None
        self._lock = threading.Lock()

    @property
    def exe_path(self) -> Path:
        out_dir = Path(config_dir()) / "wine-input-bridge"
        return out_dir / "TTMTWineInputBridge.exe"

    def ensure_running(self) -> bool:
        with self._lock:
            if not os.path.isfile(self.wine_bin):
                print(
                    f"[wine_input_bridge] wine binary not found at {self.wine_bin}; "
                    f"bridge cannot start for prefix={self.prefix}"
                )
                return False
            if self._ping():
                return True
            if not self._ensure_compiled():
                return False
            self._process = subprocess.Popen(
                [self.wine_bin, "Z:" + str(self.exe_path).replace("/", "\\"), "--port", str(self.port)],
                env=self.env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            deadline = time.monotonic() + 3.0
            while time.monotonic() < deadline:
                if self._ping():
                    return True
                time.sleep(0.05)
        return False

    def send(self, op: str, index: int, keysym: str, active_index: int = -1) -> bool:
        if not self.ensure_running():
            return False
        response = self._request(f"{op} {index} {keysym} {active_index}")
        return bool(response and response.startswith("OK "))

    def _ping(self) -> bool:
        response = self._request("list", timeout=0.15)
        return bool(response and response.startswith("OK "))

    def cross_check_sort_order(self, window_ids: list[str]) -> bool:
        """Verify that the helper's window-list sort order agrees with the
        caller's. Returns True when the agreement holds (so positional
        indices are safe to use), False on disagreement (caller should
        fall back to the X11 backend).

        Strategy: ask the helper for its window list, parse the per-window
        Left coordinates, and verify they are monotonically non-decreasing.
        Python's window_ids are already sorted left-to-right by
        WindowManager.assign_windows; the helper's response is sorted
        left-to-right by GetWindowRect().Left in FindCorporateClashWindows.
        If both axes agree, the Left values come out non-decreasing. A
        mismatch fires when XWayland's coord space and Win32's coord
        space diverge (e.g. hypothetical multi-monitor edge case)."""
        response = self._request("list", timeout=0.3)
        if not response or not response.startswith("OK"):
            return False
        payload = response[3:].strip()
        if not payload:
            return len(window_ids) == 0
        cs_entries = []
        for tok in payload.split(","):
            parts = tok.split(":")
            if len(parts) < 2:
                return False
            try:
                cs_entries.append(int(parts[1]))  # Left
            except ValueError:
                return False
        if len(cs_entries) != len(window_ids):
            return False
        # Verify Left values are monotonically non-decreasing.
        for a, b in zip(cs_entries, cs_entries[1:]):
            if a > b:
                return False
        return True

    _MAX_RESPONSE_BYTES = 64 * 1024  # generous cap; helper responses are short

    def _request(self, line: str, timeout: float = 0.5) -> str | None:
        try:
            with socket.create_connection(("127.0.0.1", self.port), timeout=timeout) as sock:
                sock.sendall((line + "\n").encode("utf-8"))
                sock.settimeout(timeout)
                # Helper writes exactly one newline-terminated line per command.
                # Loop until we see a newline or hit the cap so multi-recv
                # responses (rare on loopback but not guaranteed by TCP) are
                # handled correctly.
                buf = bytearray()
                while b"\n" not in buf and len(buf) < self._MAX_RESPONSE_BYTES:
                    chunk = sock.recv(4096)
                    if not chunk:
                        break
                    buf.extend(chunk)
        except OSError:
            return None
        return buf.decode("utf-8", "replace").strip()

    def shutdown(self) -> None:
        """Best-effort: ask the helper to quit, then ensure the process is gone."""
        try:
            self._request("quit", timeout=0.5)
        except Exception:
            pass
        proc = self._process
        self._process = None
        if proc is None:
            return
        try:
            if proc.poll() is None:
                try:
                    proc.wait(timeout=1.0)
                except subprocess.TimeoutExpired:
                    try:
                        proc.terminate()
                        proc.wait(timeout=0.5)
                    except (OSError, subprocess.TimeoutExpired):
                        try:
                            proc.kill()
                        except OSError:
                            pass
        except OSError:
            pass

    def _ensure_compiled(self) -> bool:
        exe = self.exe_path
        source = _resource_path("tools", "wine_input_bridge", "TTMTWineInputBridge.cs")
        if not source.exists():
            print(f"[wine_input_bridge] C# source not found at {source}; bridge unavailable")
            return False
        if exe.exists() and exe.stat().st_mtime >= source.stat().st_mtime:
            return True
        exe.parent.mkdir(parents=True, exist_ok=True)
        csc = "C:\\windows\\Microsoft.NET\\Framework64\\v4.0.30319\\csc.exe"
        cmd = [
            self.wine_bin,
            csc,
            "/nologo",
            "/target:exe",
            "/out:Z:" + str(exe).replace("/", "\\"),
            "Z:" + str(source).replace("/", "\\"),
        ]
        try:
            result = subprocess.run(
                cmd,
                env=self.env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired) as e:
            print(f"[wine_input_bridge] csc compile failed for prefix={self.prefix}: {e}")
            return False
        if result.returncode != 0 or not exe.exists():
            print(
                f"[wine_input_bridge] csc compile non-zero (rc={result.returncode}) "
                f"or missing output for prefix={self.prefix}; "
                f"wine-mono may be absent or csc.exe path wrong"
            )
            return False
        return True
