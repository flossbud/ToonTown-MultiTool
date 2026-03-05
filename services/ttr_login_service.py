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
HEADERS = {"Content-type": "application/x-www-form-urlencoded"}

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
]


def find_engine_path() -> str | None:
    """Auto-detect TTREngine binary. Returns path to directory containing it, or None."""
    # Check all flatpak data dirs first (covers unknown app IDs)
    flatpak_data = os.path.expanduser("~/.var/app")
    if os.path.isdir(flatpak_data):
        for app_dir in os.listdir(flatpak_data):
            full = os.path.join(flatpak_data, app_dir)
            if not os.path.isdir(full):
                continue
            # Check data/ directly
            candidate = os.path.join(full, "data")
            if os.path.isfile(os.path.join(candidate, "TTREngine")):
                return candidate
            # Check data/toontown-rewritten/
            candidate2 = os.path.join(candidate, "toontown-rewritten")
            if os.path.isfile(os.path.join(candidate2, "TTREngine")):
                return candidate2

    # Check standard paths
    for path in ENGINE_SEARCH_PATHS:
        if os.path.isfile(os.path.join(path, "TTREngine")):
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
        self._queue_token = None
        self._response_token = None  # for 2FA
        self._polling = False

    @property
    def state(self):
        return self._state

    def _set_state(self, state, msg=""):
        self._state = state
        self.state_changed.emit(state, msg)

    # ── Login Flow ─────────────────────────────────────────────────────────

    def login(self, username: str, password: str):
        """Start login. Call from main thread."""
        self._set_state(LoginState.LOGGING_IN, "Authenticating…")
        self._polling = True

        def _do():
            try:
                resp = requests.post(API_URL, data={
                    "username": username, "password": password,
                }, headers=HEADERS, timeout=15)
                data = resp.json()
                self._handle_response(data)
            except requests.RequestException as e:
                self._set_state(LoginState.FAILED, f"Network error: {e}")
                self.login_failed.emit(f"Network error: {e}")

        threading.Thread(target=_do, daemon=True).start()

    def submit_2fa(self, token: str):
        """Submit a 2FA token."""
        if not self._response_token:
            self.login_failed.emit("No pending 2FA session.")
            return
        self._set_state(LoginState.LOGGING_IN, "Verifying token…")

        auth_token = self._response_token
        self._response_token = None

        def _do():
            try:
                resp = requests.post(API_URL, data={
                    "appToken": token, "authToken": auth_token,
                }, headers=HEADERS, timeout=15)
                data = resp.json()
                self._handle_response(data)
            except requests.RequestException as e:
                self._set_state(LoginState.FAILED, f"Network error: {e}")
                self.login_failed.emit(f"Network error: {e}")

        threading.Thread(target=_do, daemon=True).start()

    def _handle_response(self, data: dict):
        success = data.get("success", "false")

        if success == "false":
            msg = data.get("banner", "Login failed.")
            self._set_state(LoginState.FAILED, msg)
            self.login_failed.emit(msg)

        elif success == "partial":
            # Two-factor authentication needed
            self._response_token = data.get("responseToken", "")
            banner = data.get("banner", "Please enter your authenticator token.")
            self._set_state(LoginState.NEED_2FA, banner)
            self.need_2fa.emit(banner)

        elif success == "delayed":
            # Queued — need to poll
            self._queue_token = data.get("queueToken", "")
            position = int(data.get("position", 0))
            eta = int(data.get("eta", 60))
            self._set_state(LoginState.QUEUED, f"In queue — position {position}, ~{eta}s")
            self.queue_update.emit(position, eta)
            self._start_queue_polling()

        elif success == "true":
            gameserver = data.get("gameserver", "")
            cookie = data.get("cookie", "")
            self._set_state(LoginState.LAUNCHING, "Login successful! Launching…")
            self.login_success.emit(gameserver, cookie)

    # ── Queue Polling ──────────────────────────────────────────────────────

    def _start_queue_polling(self):
        def _poll():
            while self._polling and self._state == LoginState.QUEUED:
                time.sleep(10)  # Poll every 10 seconds (well within 30s limit)
                if not self._polling:
                    break
                try:
                    resp = requests.post(API_URL, data={
                        "queueToken": self._queue_token,
                    }, headers=HEADERS, timeout=15)
                    data = resp.json()
                    success = data.get("success", "false")

                    if success == "delayed":
                        position = int(data.get("position", 0))
                        eta = int(data.get("eta", 60))
                        self._set_state(LoginState.QUEUED, f"In queue — position {position}, ~{eta}s")
                        self.queue_update.emit(position, eta)
                    else:
                        self._handle_response(data)
                        break
                except requests.RequestException:
                    continue  # Retry on network errors

        threading.Thread(target=_poll, daemon=True).start()

    # ── Control ────────────────────────────────────────────────────────────

    def cancel(self):
        """Cancel any ongoing login/queue."""
        self._polling = False
        self._queue_token = None
        self._response_token = None
        if self._state != LoginState.RUNNING:
            self._set_state(LoginState.IDLE, "Cancelled.")