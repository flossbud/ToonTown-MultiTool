"""The launcher as other surfaces see it: a list of accounts with a launch
state each, and a way to launch one.

``LauncherPort`` adapts ``LaunchTab`` for the float strips' compact launcher
(and anything else that lists accounts without mounting the launcher). It
holds no state of its own beyond the last list it announced.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QObject, Signal

from services.ttr_login_service import LoginState

STATE_IDLE = "idle"
STATE_LAUNCHING = "launching"
STATE_RUNNING = "running"

_LAUNCHING = frozenset({
    LoginState.LOGGING_IN, LoginState.NEED_2FA, LoginState.QUEUED,
    LoginState.LAUNCHING, LoginState.LOADING,
})


def port_state(login_state: str) -> str:
    """idle | launching | running for one of the launcher's own states."""
    if login_state == LoginState.RUNNING:
        return STATE_RUNNING
    if login_state in _LAUNCHING:
        return STATE_LAUNCHING
    return STATE_IDLE


@dataclass(frozen=True)
class PortAccount:
    account_id: str
    game: str           # "ttr" | "cc"
    label: str          # what the launcher card shows
    state: str          # idle | launching | running
    toon: str           # the running toon's name, else ""


class LauncherPort(QObject):
    # The account list, or some account's state, changed. GUI thread.
    changed = Signal()

    def __init__(self, launch_tab, parent: QObject | None = None):
        super().__init__(parent)
        self._launch_tab = launch_tab
        self._last = tuple(self.accounts())
        launch_tab.accounts_changed.connect(self._on_launcher_changed)

    def accounts(self) -> list:
        """Every saved account in the launcher's own order."""
        out = []
        for item in self._launch_tab.launch_overview():
            state = port_state(item["state"])
            out.append(PortAccount(
                account_id=item["account_id"], game=item["game"],
                label=item["label"], state=state,
                # A toon is only "the running toon" while the account runs.
                toon=item["toon"] if state == STATE_RUNNING else ""))
        return out

    def launch(self, account_id: str) -> bool:
        """Start that account exactly as its card's play button does, with
        the launcher's own guards and error dialogs. False for an id the
        launcher does not know."""
        game = self._launch_tab.game_of_account(account_id)
        if game is None:
            return False
        self._launch_tab.launch_account(game, account_id)
        return True

    def _on_launcher_changed(self) -> None:
        current = tuple(self.accounts())
        if current != self._last:
            self._last = current
            self.changed.emit()
