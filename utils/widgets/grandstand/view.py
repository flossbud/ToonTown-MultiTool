"""GrandstandView — the roster stack, and the composition root for sub-project A.

Owns layout and intent, never behaviour: it emits what the user asked for and
LaunchTab performs it. Nothing here touches a login worker, a patcher or a
credential.

Built only when TTMT_GRANDSTAND=1 until the cut-over task removes the flag.
"""
from __future__ import annotations

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QVBoxLayout, QWidget

from utils.widgets.grandstand import palette as gp

# Band geometry (handoff §4.1). The stack is fixed above the shelf; the shelf
# takes what is left of the 688px content area.
SELECTOR_H = 72
HERO_H = 232
STACK_MARGINS = (14, 14, 14, 16)
STACK_GAP = 10

# Bumped by each milestone so a live validator can tell which build is running.
MILESTONE = 1
STAMP_PREFIX = "[Grandstand] view active"

_FLAG = "TTMT_GRANDSTAND"


def grandstand_enabled() -> bool:
    """True when the new launcher view is selected. Any value other than "1"
    is off, so a stale empty export cannot half-enable it."""
    return os.environ.get(_FLAG, "") == "1"


class GrandstandView(QWidget):
    """The roster: game selector, hero stage, card shelf."""

    game_changed = Signal(str)                    # game
    party_changed = Signal(str)                   # game
    star_changed = Signal(str, object)            # game, account_id | None
    launch_requested = Signal(str, str)           # game, account_id
    party_launch_requested = Signal(str, list)    # game, ordered account ids
    edit_requested = Signal(str, str, str)        # game, account_id, surface
    cancel_requested = Signal(str, str)
    quit_requested = Signal(str, str)
    enter_2fa_requested = Signal(str, str)
    retry_requested = Signal(str, str)
    add_account_requested = Signal(str)
    manage_requested = Signal(str)
    official_launcher_requested = Signal(str)

    def __init__(self, party, log=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._log = log or (lambda _msg: None)
        # First statement with any observable effect: the running-code stamp.
        self._log(f"{STAMP_PREFIX} — {_FLAG}=1 (milestone {MILESTONE})")

        self._party = party
        self._is_dark = True
        self._entries: dict[str, list] = {"ttr": [], "cc": []}

        self.setObjectName("grandstand_view")

        root = QVBoxLayout(self)
        root.setContentsMargins(*STACK_MARGINS)
        root.setSpacing(STACK_GAP)

        self.advisory = QFrame(self)          # slim credential bar (Task 14)
        self.advisory.setObjectName("gs_advisory")
        self.advisory.setVisible(False)
        root.addWidget(self.advisory)

        from utils.widgets.grandstand.game_selector import GameSelector
        self.selector = GameSelector(self)
        self.selector.setFixedHeight(SELECTOR_H)
        self.selector.set_active(self._party.active_game())
        self.selector.game_clicked.connect(self._on_game_clicked)
        root.addWidget(self.selector)

        self.hero = self._make_band("gs_hero", HERO_H)
        root.addWidget(self.hero)

        self.shelf = QFrame(self)
        self.shelf.setObjectName("gs_shelf")
        root.addWidget(self.shelf, 1)         # the only stretching band

        self.apply_theme(self._is_dark)

    def _make_band(self, name: str, height: int) -> QFrame:
        f = QFrame(self)
        f.setObjectName(name)
        f.setFixedHeight(height)
        return f

    # ── inbound ────────────────────────────────────────────────────────────

    def active_game(self) -> str:
        return self._party.active_game()

    def set_accounts(self, game: str, entries: list) -> None:
        """Replace one game's roster. Entries are model.RosterEntry."""
        self._entries[game] = list(entries)
        self.selector.set_counts(
            len(self._entries["ttr"]), len(self._entries["cc"]))

    def set_account_state(self, game: str, account_id: str, state: str,
                          message: str = "", raw: str = "") -> None:
        """Route one account's live launch state to its card. Unknown ids are
        ignored — a state can arrive for an account already deleted."""
        return

    def apply_theme(self, is_dark: bool) -> None:
        self._is_dark = is_dark
        p = gp.panel(is_dark)
        for frame in (self.hero, self.shelf):
            frame.setStyleSheet(
                f"QFrame#{frame.objectName()} {{"
                f" background: {p['bg'].name()};"
                f" border: 1px solid {p['border'].name()};"
                f" border-radius: 9px; }}"
            )
        self.selector.apply_theme(is_dark)

    def _on_game_clicked(self, game: str) -> None:
        if game == self._party.active_game():
            return
        self._party.set_active_game(game)
        self.selector.set_active(game)
        self.game_changed.emit(game)
