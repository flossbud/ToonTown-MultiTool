"""
TTR Login Service — handles the login API flow and game launch.

Supports:
  - Username/password login
  - Two-factor authentication
  - Queue wait with progress
  - Game launch via direct engine execution or flatpak
"""

import os
import subprocess
import threading
import time
import requests

from PySide6.QtCore import QObject, Signal


API_URL = "https://www.toontownrewritten.com/api/login?format=json"
assert API_URL.startswith("https://"), "API_URL must use HTTPS"
HEADERS = {
    "Content-type": "application/x-www-form-urlencoded",
    "User-Agent": "ToontownMultiTool/2.0.2"
}

# Common locations to search for TTREngine
ENGINE_SEARCH_PATHS = [
    # Official TTR flatpak
    os.path.expanduser("~/.var/app/com.toontownrewritten.Launcher/data"),
    # Unofficial xytime flatpak
    os.path.expanduser("~/.var/app/xyz.xytime.Toontown/data"),
    os.path.expanduser("~/.var/app/xyz.xytime.Toontown/data/toontown-rewritten"),
    # Native / extracted
    os.path.expanduser("~/Toontown Rewritten"),
    os.path.expanduser("~/toontown-rewritten"),
    os.path.expanduser("~/Games/Toontown Rewritten"),
    os.path.expanduser("~/Games/toontown-rewritten"),
    os.path.expanduser("~/.local/share/toontown-rewritten"),
    os.path.join(os.environ.get("PROGRAMFILES(X86)", "C:\\Program Files (x86)"), "Toontown Rewritten"),
    os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~\\AppData\\Local")), "Toontown Rewritten"),
]


def get_engine_executable_name() -> str:
    """Return the platform-specific name of the TTREngine binary."""
    import sys
    return "TTREngine64.exe" if sys.platform == "win32" else "TTREngine"

def find_engine_path() -> str | None:
    """Auto-detect TTREngine binary. Returns path to directory containing it, or None."""
    binary_name = get_engine_executable_name()

    # Check standard paths
    for path in ENGINE_SEARCH_PATHS:
        if os.path.isfile(os.path.join(path, binary_name)):
            return path

    return None


class LoginState:
    """Enumeration of login states."""
    IDLE = "idle"
    LOGGING_IN = "logging_in"
    NEED_2FA = "need_2fa"
    QUEUED = "queued"
    LAUNCHING = "launching"
    RUNNING = "running"
    FAILED = "failed"


class TTRLoginWorker(QObject):
    """
    Worker that handles a single account's login flow.
    Lives on the main thread — spawns background threads for network calls.
    """

    # Signals
    state_changed = Signal(str, str)       # (state, message)
    queue_update = Signal(int, int)        # (position, eta_seconds)
    need_2fa = Signal(str)                 # (banner_prompt)
    login_success = Signal(str, str)       # (gameserver, cookie)
    login_failed = Signal(str)             # (error_message)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._state = LoginState.IDLE
        self._token_lock = threading.Lock()
        self._queue_token = None
        self._response_token = None  # for 2FA
        self._stop_event = threading.Event()

    @property
    def state(self):
        return self._state

    def _set_state(self, state, msg=""):
        self._state = state
        self.state_changed.emit(state, msg)

    def _parse_queue_int(self, value, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _decode_json_response(self, resp, failure_message: str) -> dict | None:
        try:
            return resp.json()
        except ValueError:
            msg = f"{failure_message} (HTTP {resp.status_code})"
            self._set_state(LoginState.FAILED, msg)
            self.login_failed.emit(msg)
            return None

    # ── Login Flow ─────────────────────────────────────────────────────────

    def login(self, username: str, password: str):
        """Start login. Call from main thread."""
        self._set_state(LoginState.LOGGING_IN, "Authenticating…")
        self._stop_event.clear()

        def _do():
            try:
                resp = requests.post(API_URL, data={
                    "username": username, "password": password,
                }, headers=HEADERS, timeout=15, verify=True)
                data = self._decode_json_response(resp, "Invalid response from login server.")
                if data is None:
                    return
                self._handle_response(data)
            except requests.RequestException as e:
                print(f"[TTRLoginWorker] Network error: {type(e).__name__}: {e}")
                self._set_state(LoginState.FAILED, "Network connection failed. Please check your connection and try again.")
                self.login_failed.emit("Network connection failed. Please check your connection and try again.")

        threading.Thread(target=_do, daemon=True).start()

    def submit_2fa(self, token: str):
        """Submit a 2FA token."""
        with self._token_lock:
            if not self._response_token:
                self.login_failed.emit("No pending 2FA session.")
                return
            auth_token = self._response_token
            self._response_token = None
        self._set_state(LoginState.LOGGING_IN, "Verifying token…")

        def _do():
            try:
                resp = requests.post(API_URL, data={
                    "appToken": token, "authToken": auth_token,
                }, headers=HEADERS, timeout=15, verify=True)
                data = self._decode_json_response(resp, "Invalid response from login server.")
                if data is None:
                    return
                self._handle_response(data)
            except requests.RequestException as e:
                print(f"[TTRLoginWorker] Network error: {type(e).__name__}: {e}")
                self._set_state(LoginState.FAILED, "Network connection failed. Please check your connection and try again.")
                self.login_failed.emit("Network connection failed. Please check your connection and try again.")

        threading.Thread(target=_do, daemon=True).start()

    def _handle_response(self, data: dict):
        success = data.get("success", "false")

        if success == "false":
            msg = data.get("banner", "Login failed.")
            self._set_state(LoginState.FAILED, msg)
            self.login_failed.emit(msg)

        elif success == "partial":
            # Two-factor authentication needed
            with self._token_lock:
                self._response_token = data.get("responseToken", "")
            banner = data.get("banner", "Please enter your authenticator token.")
            self._set_state(LoginState.NEED_2FA, banner)
            self.need_2fa.emit(banner)

        elif success == "delayed":
            # Queued — need to poll
            with self._token_lock:
                self._queue_token = data.get("queueToken", "")
            position = self._parse_queue_int(data.get("position", 0), 0)
            eta = self._parse_queue_int(data.get("eta", 60), 60)
            self._set_state(LoginState.QUEUED, f"In queue — position {position}, ~{eta}s")
            self.queue_update.emit(position, eta)
            self._start_queue_polling()

        elif success == "true":
            gameserver = data.get("gameserver", "")
            cookie = data.get("cookie", "")
            self._set_state(LoginState.LAUNCHING, "Login successful! Launching…")
            self.login_success.emit(gameserver, cookie)

    # ── Queue Polling ──────────────────────────────────────────────────────

    _MAX_QUEUE_POLLS = 60  # 60 × 10s = 10 minutes max queue wait

    def _start_queue_polling(self):
        def _poll():
            polls = 0
            retry_delay = 1.0
            consecutive_failures = 0
            while not self._stop_event.is_set() and self._state == LoginState.QUEUED:
                time.sleep(10)  # Poll every 10 seconds (well within 30s limit)
                if self._stop_event.is_set():
                    break
                polls += 1
                if polls > self._MAX_QUEUE_POLLS:
                    self._set_state(LoginState.FAILED, "Queue timed out after 10 minutes.")
                    self.login_failed.emit("Queue timed out after 10 minutes.")
                    break
                with self._token_lock:
                    queue_token = self._queue_token
                try:
                    resp = requests.post(API_URL, data={
                        "queueToken": queue_token,
                    }, headers=HEADERS, timeout=15, verify=True)
                    data = self._decode_json_response(resp, "Invalid response while polling queue.")
                    if data is None:
                        break
                    success = data.get("success", "false")
                    consecutive_failures = 0
                    retry_delay = 1.0

                    if success == "delayed":
                        position = self._parse_queue_int(data.get("position", 0), 0)
                        eta = self._parse_queue_int(data.get("eta", 60), 60)
                        self._set_state(LoginState.QUEUED, f"In queue — position {position}, ~{eta}s")
                        self.queue_update.emit(position, eta)
                    else:
                        self._handle_response(data)
                        break
                except requests.RequestException as e:
                    consecutive_failures += 1
                    print(f"[TTRLoginWorker] Queue poll failed ({consecutive_failures}): {e}. Retrying in {retry_delay:.1f}s.")
                    if consecutive_failures >= 10:
                        self._set_state(LoginState.FAILED, "Network error while polling queue.")
                        self.login_failed.emit("Network error while polling queue.")
                        break
                    time.sleep(retry_delay)
                    retry_delay = min(5.0, retry_delay * 2.0)
                    continue

        threading.Thread(target=_poll, daemon=True).start()

    # ── Control ────────────────────────────────────────────────────────────

    def cancel(self):
        """Cancel any ongoing login/queue."""
        self._stop_event.set()
        with self._token_lock:
            self._queue_token = None
            self._response_token = None
        if self._state != LoginState.RUNNING:
            self._set_state(LoginState.IDLE, "Cancelled.")
