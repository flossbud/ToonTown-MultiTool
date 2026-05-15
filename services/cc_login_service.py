"""
Corporate Clash Login Service — register / login / metadata for CC's
launcher API (https://apidocs.corporateclash.net/).

Auth flow:
  1. /register (one-time per account): username+password+friendly → launcher_token
  2. /login (per launch): Bearer launcher_token → game_token
  3. /metadata (per launch): Bearer launcher_token → realms (gameserver)
  4. /revoke_self (on account delete): Bearer launcher_token → status

Storage model is token-only: TTMT stores launcher tokens, never passwords.
Existing accounts with stored passwords are migrated lazily on first
Launch click (register → store token → discard password).

Key differences from TTR:
  - Launch uses the game token via CLI/env, similar to old osst.
  - No queue polling.
"""

from __future__ import annotations

import os
import threading
import requests

from PySide6.QtCore import QObject, Signal
from services.ttr_login_service import LoginState
from services.wine_runtimes import discover_cc_installs


CC_REGISTER_URL = "https://corporateclash.net/api/launcher/v1/register"
CC_LOGIN_URL    = "https://corporateclash.net/api/launcher/v1/login"
CC_METADATA_URL = "https://corporateclash.net/api/launcher/v1/metadata"
CC_REVOKE_URL   = "https://corporateclash.net/api/launcher/v1/revoke_self"
CC_FALLBACK_GAMESERVER = "gs-prd.corporateclash.net:7198"

CC_HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": "ToontownMultiTool/2.3.0-a",
}


def _friendly_name(label: str = "") -> str:
    """Build the CC-launcher 'friendly' name shown in CC's authorized-
    launchers list. Format: 'ToontownMultiTool (<hostname>)' or
    'ToontownMultiTool (<hostname>) - <label>' when a label is supplied.

    ASCII-only (no unicode middle-dot) for maximum API compatibility.
    """
    import socket
    base = f"ToontownMultiTool ({socket.gethostname()})"
    return f"{base} - {label}" if label else base


def revoke_launcher_token(launcher_token: str, timeout: float = 5.0) -> bool:
    """Best-effort: POST /revoke_self with the given token.

    Returns ``True`` only on HTTP 200 with ``status: True`` in the
    response body. Returns ``False`` on any other shape or any error.
    Never raises.

    Intended to run on a daemon thread fired from the delete-account
    flow so UI deletion is instant.
    """
    if not launcher_token:
        return False
    try:
        headers = dict(CC_HEADERS)
        headers["Authorization"] = f"Bearer {launcher_token}"
        resp = requests.post(
            CC_REVOKE_URL, headers=headers, timeout=timeout, verify=True,
        )
        data = resp.json()
        return bool(data.get("status") is True)
    except Exception as e:
        print(f"[CC] revoke_launcher_token: {type(e).__name__}: {e}")
        return False


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
    """Auto-detect CorporateClash binary.

    Returns the directory containing CorporateClash.exe for the
    preference-sorted first match, or None if none found.

    Detection now covers Bottles, Lutris, Steam Proton, plain Wine prefixes,
    and the existing Windows-native search list.
    """
    installs = discover_cc_installs()
    if not installs:
        return None
    return os.path.dirname(installs[0].exe_path)


class CCLoginWorker(QObject):
    """
    Worker that handles a single Corporate Clash account's login flow.
    Lives on the main thread — spawns background threads for network calls.

    Reuses the same LoginState enum as TTR (it is game-agnostic).
    Emits login_success(gameserver, game_token) on success — same signal
    signature as TTRLoginWorker so the launch tab can handle both uniformly.
    """

    # Signals — same signature as TTRLoginWorker
    state_changed = Signal(str, str)       # (state, message)
    queue_update = Signal(int, int)        # (position, eta_seconds) — unused for CC
    need_2fa = Signal(str)                 # (prompt_message)
    launcher_token_obtained = Signal(str)   # NEW: from /register, before /login
    login_success = Signal(str, str)       # (gameserver, game_token)
    login_failed = Signal(str)             # (error_message)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._state = LoginState.IDLE
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

    def submit_2fa(self, token: str) -> None:
        """Compatibility no-op.

        The new launcher API does not document a 2FA challenge response.
        Kept on the worker so the launch tab's signal wiring (which expects
        a ``submit_2fa`` method symmetric with the TTR worker) doesn't
        break. If a real 2FA flow is ever needed under the new API, this
        method becomes the place to implement it.
        """
        msg = ("2FA submission is not supported in this build of TTMT. "
               "If you saw a 2FA prompt, your CC account may require "
               "verification via CC's website first.")
        self._set_state(LoginState.FAILED, msg)
        self.login_failed.emit(msg)

    def register_and_login(self, username: str, password: str,
                           label: str = "") -> None:
        """Onboarding + legacy-migration path. POSTs /register with the
        user's credentials; on success emits ``launcher_token_obtained``
        (so the caller can persist the token BEFORE /login runs, which
        means the token survives a /login failure), then chains directly
        into /login and /metadata. Call from the main thread.
        """
        self._set_state(LoginState.LOGGING_IN, "Registering with CC…")
        self._stop_event.clear()
        friendly = _friendly_name(label)

        def _do():
            try:
                resp = requests.post(
                    CC_REGISTER_URL,
                    json={
                        "username": username,
                        "password": password,
                        "friendly": friendly,
                    },
                    headers=CC_HEADERS,
                    timeout=15,
                    verify=True,
                )
                data = self._decode_json_response(
                    resp, "Invalid response from registration server.")
                if data is None:
                    return
                token = self._handle_register_response(data)
                if token is None:
                    return  # _handle_register_response already emitted failure
                self.launcher_token_obtained.emit(token)
                # Chain into /login on the same daemon thread.
                self._do_login_chain(token)
            except requests.RequestException as e:
                print(f"[CCLoginWorker] /register network error: {type(e).__name__}: {e}")
                msg = "Network connection failed. Please check your connection and try again."
                self._set_state(LoginState.FAILED, msg)
                self.login_failed.emit(msg)

        threading.Thread(target=_do, daemon=True).start()

    def _handle_register_response(self, data: dict) -> str | None:
        """Return the launcher token on success, or None and emit
        login_failed on any failure. Runs on the daemon thread.
        """
        if data.get("status") is True:
            token = data.get("token", "")
            if not token:
                msg = "Registration succeeded but no launcher token received."
                self._set_state(LoginState.FAILED, msg)
                self.login_failed.emit(msg)
                return None
            return token
        msg = data.get("message") or data.get("reason") or "Registration failed."
        self._set_state(LoginState.FAILED, msg)
        self.login_failed.emit(msg)
        return None

    def _do_login_chain(self, launcher_token: str) -> None:
        """Inner /login + /metadata, called from the daemon thread after
        a successful /register. Reuses the same daemon thread for the
        whole register→login chain to avoid extra thread setup.
        """
        try:
            headers = dict(CC_HEADERS)
            headers["Authorization"] = f"Bearer {launcher_token}"
            resp = requests.post(
                CC_LOGIN_URL, headers=headers, timeout=15, verify=True,
            )
            data = self._decode_json_response(
                resp, "Invalid response from login server.")
            if data is None:
                return
            self._handle_login_response(launcher_token, data)
        except requests.RequestException as e:
            print(f"[CCLoginWorker] /login network error: {type(e).__name__}: {e}")
            msg = "Network connection failed. Please check your connection and try again."
            self._set_state(LoginState.FAILED, msg)
            self.login_failed.emit(msg)

    def login_with_token(self, launcher_token: str) -> None:
        """Per-launch path for accounts that already have a stored launcher
        token. POSTs /login with the Bearer header; on success fetches the
        gameserver via /metadata and emits login_success(gameserver,
        game_token). On bad_token, emits a user-actionable login_failed.

        Call from the main thread.
        """
        self._set_state(LoginState.LOGGING_IN, "Authenticating…")
        self._stop_event.clear()

        def _do():
            try:
                headers = dict(CC_HEADERS)
                headers["Authorization"] = f"Bearer {launcher_token}"
                resp = requests.post(
                    CC_LOGIN_URL, headers=headers, timeout=15, verify=True,
                )
                data = self._decode_json_response(
                    resp, "Invalid response from login server.")
                if data is None:
                    return
                self._handle_login_response(launcher_token, data)
            except requests.RequestException as e:
                print(f"[CCLoginWorker] /login network error: {type(e).__name__}: {e}")
                msg = "Network connection failed. Please check your connection and try again."
                self._set_state(LoginState.FAILED, msg)
                self.login_failed.emit(msg)

        threading.Thread(target=_do, daemon=True).start()

    def _handle_login_response(self, launcher_token: str, data: dict) -> None:
        """Process /login JSON. Runs on the daemon thread."""
        if data.get("status") is True:
            game_token = data.get("token", "")
            if not game_token:
                msg = "Login succeeded but no game token received."
                self._set_state(LoginState.FAILED, msg)
                self.login_failed.emit(msg)
                return
            gameserver = self._fetch_gameserver(launcher_token)
            self._set_state(LoginState.LAUNCHING, "Login successful! Launching…")
            self.login_success.emit(gameserver, game_token)
            return

        if data.get("bad_token") is True:
            msg = ("Your CC launcher token is no longer valid. "
                   "Click Edit on this account to re-enter your password.")
            self._set_state(LoginState.FAILED, msg)
            self.login_failed.emit(msg)
            return

        msg = data.get("message") or data.get("reason") or "Login failed."
        self._set_state(LoginState.FAILED, msg)
        self.login_failed.emit(msg)

    def _fetch_gameserver(self, launcher_token: str) -> str:
        """GET /metadata; return the first realm's hostname. Fallback to
        CC_FALLBACK_GAMESERVER on any error. Never raises.
        """
        try:
            headers = dict(CC_HEADERS)
            headers["Authorization"] = f"Bearer {launcher_token}"
            resp = requests.get(
                CC_METADATA_URL, headers=headers, timeout=10, verify=True,
            )
            data = resp.json()
            if data.get("bad_token") is True:
                print(f"[CC] /metadata returned bad_token; using fallback gameserver")
                return CC_FALLBACK_GAMESERVER
            realms = data.get("realms") or []
            if realms and isinstance(realms[0], dict) and realms[0].get("hostname"):
                return realms[0]["hostname"]
            print(f"[CC] /metadata returned no realms; using fallback gameserver")
            return CC_FALLBACK_GAMESERVER
        except Exception as e:
            print(f"[CC] /metadata error: {type(e).__name__}: {e}; using fallback")
            return CC_FALLBACK_GAMESERVER

    # ── Control ────────────────────────────────────────────────────────────

    def cancel(self):
        """Cancel any ongoing login."""
        self._stop_event.set()
        if self._state != LoginState.RUNNING:
            self._set_state(LoginState.IDLE, "Cancelled.")
