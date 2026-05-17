"""Wine-side input bridge for Proton-hosted Corporate Clash windows.

XSendEvent is enough for native TTR, but Proton/Wine game clients commonly
ignore background synthetic X11 key events. This bridge compiles and runs a
small managed Windows helper inside the same Wine prefix as CC; the helper
posts Win32 keyboard messages to CC HWNDs directly.
"""

from __future__ import annotations

import hashlib
import os
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
            proton_dir = _proton_dir_for_pid(pid, env)
            if proton_dir is None:
                _BAD_PREFIXES[key] = time.monotonic()
                print(f"[wine_input_bridge] could not resolve Proton dir for pid={pid}; bridge disabled for prefix={key}")
                return None
            bridge = WineInputBridge(prefix=key, proton_dir=proton_dir, env=env)
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


def _proton_dir_for_pid(pid: int, env: dict[str, str]) -> str | None:
    try:
        exe = os.readlink(f"/proc/{pid}/exe")
    except OSError:
        exe = ""
    marker = "/files/lib/wine/"
    if marker in exe:
        return exe.split(marker, 1)[0]

    winedll = env.get("WINEDLLPATH", "")
    for part in winedll.split(":"):
        if part.endswith("/files/lib/wine"):
            return part[: -len("/files/lib/wine")]
    return None


def _resource_path(*parts: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    return base.joinpath(*parts)


class WineInputBridge:
    def __init__(self, prefix: str, proton_dir: str, env: dict[str, str]):
        self.prefix = prefix
        self.proton_dir = proton_dir
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
        self.port = 37377 + (int(hashlib.sha1(prefix.encode("utf-8")).hexdigest()[:6], 16) % 1000)
        self._process: subprocess.Popen | None = None
        self._lock = threading.Lock()

    @property
    def wine_bin(self) -> str:
        return os.path.join(self.proton_dir, "files", "bin", "wine")

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
