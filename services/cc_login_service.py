"""
Corporate Clash Login Service — handles the CC login API flow.

Supports:
  - Username/password login
  - Two-factor authentication (TOTP and email)
  - No queue system (CC does not have login queues)

Key differences from TTR:
  - Endpoint: POST https://corporateclash.net/api/v1/login
  - Response: { status: bool, osst: str, ... } instead of TTR's success string
  - Launch uses CLI args (-g, -t) instead of environment variables
  - No queue polling
"""

import os
import threading
import requests

from PySide6.QtCore import QObject, Signal
from services.ttr_login_service import LoginState


CC_API_URL = "https://corporateclash.net/api/v1/login"
assert CC_API_URL.startswith("https://"), "CC_API_URL must use HTTPS"
CC_HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": "ToontownMultiTool/2.0.3"
}

# Common locations to search for CorporateClash
CC_ENGINE_SEARCH_PATHS = [
    os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~\\AppData\\Local")), "Corporate Clash"),
    os.path.join(os.environ.get("PROGRAMFILES", "C:\\Program Files"), "Corporate Clash"),
    os.path.join(os.environ.get("PROGRAMFILES(X86)", "C:\\Program Files (x86)"), "Corporate Clash"),
    os.path.expanduser("~/Games/Corporate Clash"),
]


def get_cc_engine_executable_name() -> str:
    """Return the name of the Corporate Clash binary."""
    return "CorporateClash.exe"


def find_cc_engine_path() -> str | None:
    """Auto-detect CorporateClash binary. Returns path to directory containing it, or None."""
    binary_name = get_cc_engine_executable_name()

    for path in CC_ENGINE_SEARCH_PATHS:
        if os.path.isfile(os.path.join(path, binary_name)):
            return path

    return None


class CCLoginWorker(QObject):
    """
    Worker that handles a single Corporate Clash account's login flow.
    Lives on the main thread — spawns background threads for network calls.

    Reuses the same LoginState enum as TTR (it is game-agnostic).
    Emits login_success(gameserver, osst_token) on success — same signal
    signature as TTRLoginWorker so the launch tab can handle both uniformly.
    """

    # Signals — same signature as TTRLoginWorker
    state_changed = Signal(str, str)       # (state, message)
    queue_update = Signal(int, int)        # (position, eta_seconds) — unused for CC
    need_2fa = Signal(str)                 # (prompt_message)
    login_success = Signal(str, str)       # (gameserver, osst_token)
    login_failed = Signal(str)             # (error_message)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._state = LoginState.IDLE
        self._token_lock = threading.Lock()
        self._response_token = None  # for 2FA challenge
        self._stop_event = threading.Event()

    @property
    def state(self):
        return self._state

    def _set_state(self, state, msg=""):
        self._state = state
        self.state_changed.emit(state, msg)

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
                resp = requests.post(CC_API_URL, json={
                    "username": username,
                    "password": password,
                }, headers=CC_HEADERS, timeout=15, verify=True)
                data = self._decode_json_response(resp, "Invalid response from login server.")
                if data is None:
                    return
                self._handle_response(data)
            except requests.RequestException as e:
                print(f"[CCLoginWorker] Network error: {type(e).__name__}: {e}")
                self._set_state(LoginState.FAILED, "Network connection failed. Please check your connection and try again.")
                self.login_failed.emit("Network connection failed. Please check your connection and try again.")

        threading.Thread(target=_do, daemon=True).start()

    def submit_2fa(self, token: str):
        """Submit a 2FA token (TOTP or email code)."""
        with self._token_lock:
            if not self._response_token:
                self.login_failed.emit("No pending 2FA session.")
                return
            auth_token = self._response_token
            self._response_token = None
        self._set_state(LoginState.LOGGING_IN, "Verifying token…")

        def _do():
            try:
                resp = requests.post(CC_API_URL, json={
                    "token": token,
                    "authToken": auth_token,
                }, headers=CC_HEADERS, timeout=15, verify=True)
                data = self._decode_json_response(resp, "Invalid response from login server.")
                if data is None:
                    return
                self._handle_response(data)
            except requests.RequestException as e:
                print(f"[CCLoginWorker] Network error: {type(e).__name__}: {e}")
                self._set_state(LoginState.FAILED, "Network connection failed. Please check your connection and try again.")
                self.login_failed.emit("Network connection failed. Please check your connection and try again.")

        threading.Thread(target=_do, daemon=True).start()

    def _handle_response(self, data: dict):
        """Parse CC login response.

        CC responses differ from TTR:
          Success:  { "status": true,  "osst": "...", "gameserver": "..." }
          Failure:  { "status": false, "reason": "..." }
          2FA:      { "status": false, "reason": "2fa_required", "authToken": "..." }
        """
        status = data.get("status", False)

        if status is True:
            # Login succeeded
            osst = data.get("osst", "")
            gameserver = data.get("gameserver", "")
            if not osst:
                self._set_state(LoginState.FAILED, "Login succeeded but no token received.")
                self.login_failed.emit("Login succeeded but no token received.")
                return
            self._set_state(LoginState.LAUNCHING, "Login successful! Launching…")
            self.login_success.emit(gameserver, osst)

        elif data.get("reason") == "2fa_required":
            # Two-factor authentication needed
            with self._token_lock:
                self._response_token = data.get("authToken", "")
            prompt = data.get("message", "Please enter your authenticator or email code.")
            self._set_state(LoginState.NEED_2FA, prompt)
            self.need_2fa.emit(prompt)

        else:
            # Login failed
            reason = data.get("reason", "Login failed.")
            msg = data.get("message", reason)
            self._set_state(LoginState.FAILED, msg)
            self.login_failed.emit(msg)

    # ── Control ────────────────────────────────────────────────────────────

    def cancel(self):
        """Cancel any ongoing login."""
        self._stop_event.set()
        with self._token_lock:
            self._response_token = None
        if self._state != LoginState.RUNNING:
            self._set_state(LoginState.IDLE, "Cancelled.")
