"""Where the Accounts sheet gets its accounts and sends its changes.

``AccountsBackend`` is the whole surface the sheet uses: it never touches
the credential store, the keyring or the launcher itself. The launcher's
implementation lives with the launcher; ``FakeAccountsBackend`` is the same
surface in memory, for building and testing the sheet.

Every write that changes something emits ``changed``; the sheet re-reads.
"""

from __future__ import annotations

import time
from dataclasses import replace

from PySide6.QtCore import QObject, Signal

from utils.widgets.launchpad.accounts_model import (
    GAMES, LOGIN_FAILED, LOGIN_NONE, LOGIN_SAVED, MAX_ACCOUNTS_PER_GAME,
    AccountInfo, ToonInfo,
)


class AccountsBackend(QObject):
    changed = Signal()

    # ── Reads ──────────────────────────────────────────────────────────────

    def accounts(self, game: str) -> list:
        """The game's accounts as ``AccountInfo``, in launcher order."""
        raise NotImplementedError

    def account(self, account_id: str):
        for game in GAMES:
            for info in self.accounts(game):
                if info.id == account_id:
                    return info
        return None

    def keyring_available(self) -> bool:
        raise NotImplementedError

    def set_active(self, active: bool) -> None:
        """Whether anyone is looking. A backend whose reads are costly (the
        keyring) only follows changes while active, and announces once on
        becoming active if something changed meanwhile."""

    def look_entry(self, game: str, toon_name: str) -> dict:
        """The stored look of a toon (backdrop, pattern, accent, pose)."""
        return {}

    # ── Writes ─────────────────────────────────────────────────────────────

    def add_account(self, game: str, username: str, password: str,
                    keep: bool) -> str | None:
        """Add an account; the new id, or None when it could not be added.
        With ``keep`` off nothing is stored for the login."""
        raise NotImplementedError

    def save_login(self, account_id: str, username: str, password: str,
                   keep: bool) -> bool:
        """Replace an account's login. With ``keep`` off the stored password
        is removed and the account asks at launch."""
        raise NotImplementedError

    def forget_login(self, account_id: str) -> None:
        raise NotImplementedError

    def set_label(self, account_id: str, label: str) -> None:
        raise NotImplementedError

    def remove_account(self, account_id: str) -> None:
        raise NotImplementedError

    def set_primary(self, account_id: str, toon_name: str) -> None:
        raise NotImplementedError

    def open_appearance(self, account_id: str, toon_name: str) -> None:
        """Open the Appearance editor on one toon of an account."""
        raise NotImplementedError

    def launch_with_password(self, account_id: str, password: str, keep: bool) -> bool:
        """Launch an account that has no saved login, on the password just
        typed. With ``keep`` the login is saved first; without it the
        password is used for this launch only and nothing is stored."""
        raise NotImplementedError


class FakeAccountsBackend(AccountsBackend):
    """In-memory accounts. ``calls`` records each write that was asked for."""

    def __init__(self, accounts=(), *, keyring_available: bool = True,
                 looks: dict | None = None, parent: QObject | None = None):
        super().__init__(parent)
        self._accounts: list = list(accounts)
        self._keyring = bool(keyring_available)
        self._looks = dict(looks or {})
        self._next_id = 1
        self.calls: list = []

    @classmethod
    def demo(cls, now: float | None = None, parent: QObject | None = None):
        """The accounts of the design's Accounts render."""
        now = time.time() if now is None else now
        day = 86400.0

        def toon(name, game, species, laff, accent, days, dna="demo"):
            return ToonInfo(name, game, dna if game == "ttr" else "", species, laff,
                            laff, accent, now - days * day)

        six = (
            toon("Hector Pepperoni", "ttr", "duck", 96, "#e8c14d", 1),
            toon("Loopy Sparklesnout", "ttr", "dog", 110, "#e7894a", 4),
            toon("Zippy McMuffin", "ttr", "cat", 71, "#9b6be0", 14),
            toon("Doctor Bumbleflip", "ttr", "dog", 45, "#4cb960", 30),
            toon("Quackers Von Zoom", "ttr", "duck", 58, "#3fc7c0", 61),
            toon("Whiskers McGee", "ttr", "cat", 34, "#d4548a", 150),
        )
        accounts = [
            AccountInfo("t1", "ttr", "flossbud", login=LOGIN_SAVED, toons=(
                toon("Flossbud", "ttr", "dog", 137, "#4a8fe7", 0),
                toon("Sir Hopper", "ttr", "rabbit", 60, "#56c856", 9),
                toon("Blue Cat", "ttr", "cat", 25, "#4a8fe7", 40)),
                primary_name="Flossbud"),
            AccountInfo("t2", "ttr", "flossbud27", login=LOGIN_SAVED, toons=six,
                        primary_name="Hector Pepperoni"),
            AccountInfo("t3", "ttr", "hirofloss", login=LOGIN_SAVED, toons=(
                toon("Hiro", "ttr", "dog", 88, "#9b6be0", 2),
                toon("Mini Hiro", "ttr", "mouse", 15, "#e05252", 20)),
                primary_name="Hiro"),
            AccountInfo("t4", "ttr", "crimsondeku", login=LOGIN_SAVED),
            AccountInfo("t5", "ttr", "flossbud3", login=LOGIN_FAILED,
                        failed_reason="Incorrect username or password.",
                        toons=(toon("Katsuro", "ttr", "cat", 74, "#4a8fe7", 3),),
                        primary_name="Katsuro"),
            AccountInfo("c1", "cc", "flossbud", login=LOGIN_SAVED, toons=(
                toon("Cogsworth", "cc", "bear", None, "#e7894a", 5),
                toon("Gearloose", "cc", "cat", None, "#9b6be0", 12))),
            AccountInfo("c2", "cc", "clashmain", login=LOGIN_SAVED, running=True, toons=(
                toon("Bean Counter", "cc", "cat", None, "#9b6be0", 0),
                toon("Ledger", "cc", "duck", None, "#3fc7c0", 33))),
            AccountInfo("c3", "cc", "fizz@example", login=LOGIN_SAVED, toons=(
                toon("Sir Fizzlewick", "cc", "duck", None, "#3fc7c0", 8),)),
        ]
        return cls(accounts, parent=parent)

    # ── Reads ──────────────────────────────────────────────────────────────

    def accounts(self, game: str) -> list:
        return [a for a in self._accounts if a.game == game]

    def keyring_available(self) -> bool:
        return self._keyring

    def look_entry(self, game: str, toon_name: str) -> dict:
        return dict(self._looks.get((game, toon_name), {}))

    # ── Writes ─────────────────────────────────────────────────────────────

    def _replace(self, account_id: str, **fields) -> bool:
        for index, info in enumerate(self._accounts):
            if info.id == account_id:
                new = replace(info, **fields)
                if new == info:
                    return False
                self._accounts[index] = new
                self.changed.emit()
                return True
        return False

    def add_account(self, game, username, password, keep):
        self.calls.append(("add_account", game, username, password, keep))
        if len(self.accounts(game)) >= MAX_ACCOUNTS_PER_GAME:
            return None
        account_id = f"new-{self._next_id}"
        self._next_id += 1
        saved = keep and self._keyring and bool(password)
        self._accounts.append(AccountInfo(
            account_id, game, username, login=LOGIN_SAVED if saved else LOGIN_NONE))
        self.changed.emit()
        return account_id

    def save_login(self, account_id, username, password, keep):
        self.calls.append(("save_login", account_id, username, password, keep))
        info = self.account(account_id)
        if info is None:
            return False
        if not (keep and self._keyring):
            login = LOGIN_NONE
        elif password:
            login = LOGIN_SAVED
        else:
            # A blank password keeps the stored one; a rejected login stays
            # rejected until a new password is saved.
            login = info.login
        self._replace(account_id, username=username, login=login,
                      failed_reason=None if login != LOGIN_FAILED else info.failed_reason)
        return True

    def forget_login(self, account_id):
        self.calls.append(("forget_login", account_id))
        self._replace(account_id, login=LOGIN_NONE, failed_reason=None)

    def set_label(self, account_id, label):
        self.calls.append(("set_label", account_id, label))
        self._replace(account_id, label=label)

    def remove_account(self, account_id):
        self.calls.append(("remove_account", account_id))
        before = len(self._accounts)
        self._accounts = [a for a in self._accounts if a.id != account_id]
        if len(self._accounts) != before:
            self.changed.emit()

    def set_primary(self, account_id, toon_name):
        self.calls.append(("set_primary", account_id, toon_name))
        info = self.account(account_id)
        if info is None or not any(t.name == toon_name for t in info.toons):
            return
        self._replace(account_id, primary_name=toon_name)

    def open_appearance(self, account_id, toon_name):
        self.calls.append(("open_appearance", account_id, toon_name))

    def launch_with_password(self, account_id, password, keep):
        self.calls.append(("launch_with_password", account_id, password, keep))
        info = self.account(account_id)
        if info is None or not password:
            return False
        fields = {"running": True}
        if keep and self._keyring:
            fields["login"] = LOGIN_SAVED
        self._replace(account_id, **fields)
        return True

    # ── Drivers ────────────────────────────────────────────────────────────

    def set_keyring_available(self, available: bool) -> None:
        if bool(available) != self._keyring:
            self._keyring = bool(available)
            self.changed.emit()

    def update(self, account_id: str, **fields) -> None:
        """Something outside the sheet changed an account (a launch started,
        a sign-in was rejected, a toon was discovered)."""
        self._replace(account_id, **fields)
