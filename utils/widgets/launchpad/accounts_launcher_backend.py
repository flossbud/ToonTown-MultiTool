"""The Accounts sheet's backend over the real launcher.

Reads accounts from ``LaunchTab`` (roster order, launch state, the toons
seen on each account) and the credential manager (login state), and sends
every change back through ``LaunchTab`` so the launcher's cards follow.

Telling a saved login from none reads the keyring, which can be slow, so
each account's answer is cached and only asked again when something that
could change it happened: a write through this backend, a change to the
roster, or that account's launch state moving.
"""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import QObject

from services.ttr_login_service import LoginState
from utils.widgets.launchpad.accounts_backend import AccountsBackend
from utils.widgets.launchpad.accounts_model import (
    GAMES, LOGIN_FAILED, LOGIN_NONE, LOGIN_SAVED, AccountInfo, ToonInfo,
)


def _toon_info(record) -> ToonInfo:
    return ToonInfo(
        name=record.toon_name, game=record.game, dna=record.dna or "",
        species=record.species, laff=record.laff, max_laff=record.max_laff,
        accent=record.accent, played_at=getattr(record, "played_at", None))


def _signature(accounts: list) -> tuple:
    """What a change must touch to be worth a rebuild. A toon's laff ticks
    with every hit it takes; the sheet shows it as of the last rebuild."""
    return tuple(
        replace(a, toons=tuple(replace(t, laff=None, max_laff=None) for t in a.toons))
        for a in accounts)


class LauncherAccountsBackend(AccountsBackend):
    def __init__(self, launch_tab, customizations=None, appearance_opener=None,
                 parent: QObject | None = None):
        """``appearance_opener(account_id, game, toon_name)`` opens the looks
        editor on one toon; without one the launcher's editor is opened
        directly."""
        super().__init__(parent)
        self._tab = launch_tab
        self._creds = launch_tab.cred_manager
        self._customizations = customizations
        self._appearance_opener = appearance_opener
        self._login_cache: dict[str, str] = {}
        self._states: dict[str, str] = {}
        self._last = None
        self._active = False
        self._dirty = False
        launch_tab.accounts_changed.connect(self._on_launcher_changed)
        on_change = getattr(self._creds, "on_change", None)
        if on_change is not None:
            on_change(self._on_roster_changed)

    # ── Reads ──────────────────────────────────────────────────────────────

    def _login(self, account_id: str) -> str:
        creds = self._creds
        if creds.is_login_failed(account_id):
            return LOGIN_FAILED
        cached = self._login_cache.get(account_id)
        if cached is not None:
            return cached
        status = creds.login_status(account_id)
        status = LOGIN_SAVED if status == LOGIN_SAVED else LOGIN_NONE
        if not getattr(creds, "keyring_probe_pending", False):
            # While the keyring is still being probed a saved login can read
            # as none; do not remember that answer.
            self._login_cache[account_id] = status
        return status

    def accounts(self, game: str) -> list:
        out = []
        for item in self._tab.sheet_accounts(game):
            account = item["account"]
            running = item["state"] == LoginState.RUNNING
            login = self._login(account.id)
            out.append(AccountInfo(
                id=account.id, game=game, username=account.username or "",
                label=account.label or "", login=login,
                failed_reason=(self._creds.login_failed_reason(account.id)
                               if login == LOGIN_FAILED else None),
                running=running,
                toons=tuple(_toon_info(rec) for rec in item["records"]),
                primary_name=item["primary"]))
        return out

    def keyring_available(self) -> bool:
        return bool(getattr(self._creds, "keyring_available", False))

    def look_entry(self, game: str, toon_name: str) -> dict:
        if self._customizations is None or not toon_name:
            return {}
        try:
            return self._customizations.get(game, toon_name) or {}
        except Exception:  # noqa: BLE001
            return {}

    # ── Change tracking ────────────────────────────────────────────────────

    def _snapshot(self) -> tuple:
        return tuple(_signature(self.accounts(game)) for game in GAMES)

    def set_active(self, active: bool) -> None:
        """The sheet is showing (or not). Reading a login's state asks the
        keyring, so nothing is read while nobody is looking; what changed
        meanwhile is announced once when the sheet comes back."""
        active = bool(active)
        if active == self._active:
            return
        self._active = active
        if active and self._dirty:
            self._dirty = False
            self._announce()

    def _announce(self) -> None:
        if not self._active:
            self._dirty = True
            return
        current = self._snapshot()
        if current != self._last:
            self._last = current
            self.changed.emit()

    def _on_launcher_changed(self) -> None:
        # An account whose launch state moved may have a different login now
        # (a first Corporate Clash sign-in earns a token; a sign-in may have
        # been rejected or accepted). No keyring is read here.
        states = {}
        for game in GAMES:
            for item in self._tab.sheet_accounts(game):
                states[item["account"].id] = item["state"]
        for account_id, state in states.items():
            if self._states.get(account_id, state) != state:
                self._login_cache.pop(account_id, None)
        self._states = states
        self._announce()

    def _on_roster_changed(self) -> None:
        self._login_cache.clear()

    def _wrote(self, account_id: str | None = None) -> None:
        if account_id is None:
            self._login_cache.clear()
        else:
            self._login_cache.pop(account_id, None)
        self._announce()

    # ── Writes ─────────────────────────────────────────────────────────────

    def add_account(self, game, username, password, keep):
        stored = password if (keep and self.keyring_available()) else ""
        account_id = self._tab.sheet_add_account(game, username, stored)
        self._wrote()
        return account_id

    def save_login(self, account_id, username, password, keep):
        info = self.account(account_id)
        if info is None:
            return False
        if keep and self.keyring_available():
            # A blank password keeps the stored one.
            ok = self._tab.sheet_update_account(
                account_id, username=username, password=password or None)
        else:
            ok = self._tab.sheet_update_account(account_id, username=username, password="")
            if info.game == "cc":
                self._creds.clear_launcher_token(account_id)
        self._wrote(account_id)
        return bool(ok)

    def forget_login(self, account_id):
        info = self.account(account_id)
        if info is None:
            return
        self._tab.sheet_update_account(account_id, password="")
        if info.game == "cc":
            self._creds.clear_launcher_token(account_id)
        self._creds.drop_session_password(account_id)
        self._wrote(account_id)

    def set_label(self, account_id, label):
        self._tab.sheet_update_account(account_id, label=label)
        self._wrote(account_id)

    def remove_account(self, account_id):
        game = self._tab.game_of_account(account_id)
        if game is not None:
            self._tab.delete_account_confirmed(game, account_id)
        self._wrote()

    def set_primary(self, account_id, toon_name):
        self._tab.set_primary_toon(account_id, toon_name)
        self._announce()

    def open_appearance(self, account_id, toon_name):
        game = self._tab.game_of_account(account_id)
        if game is None:
            return
        if self._appearance_opener is not None:
            self._appearance_opener(account_id, game, toon_name)
        else:
            self._tab.open_appearance_for_toon(game, toon_name, account_id)

    def launch_with_password(self, account_id, password, keep):
        game = self._tab.game_of_account(account_id)
        if game is None or not password:
            return False
        if keep and self.keyring_available():
            self._tab.sheet_update_account(account_id, password=password)
            self._login_cache.pop(account_id, None)
            self._tab.launch_account(game, account_id)
        else:
            self._tab.launch_account_once(game, account_id, password)
        self._announce()
        return True
