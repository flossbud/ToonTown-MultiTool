"""GrandstandView — the roster stack, and the composition root for sub-project A.

Owns layout and intent, never behaviour: it emits what the user asked for and
LaunchTab performs it. Nothing here touches a login worker, a patcher or a
credential.

Built only when TTMT_GRANDSTAND=1 until the cut-over task removes the flag.
"""
from __future__ import annotations

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget,
)

from utils.credential_copy import KEYRING_WARNING_COPY, MACOS_VAULT_COPY
from utils.widgets.grandstand import palette as gp

# Band geometry (handoff §4.1). The stack is fixed above the shelf; the shelf
# takes what is left of the 688px content area.
SELECTOR_H = 72
HERO_H = 232
STACK_MARGINS = (14, 14, 14, 16)
STACK_GAP = 10
ADVISORY_STACK_GAP = 8

# Bumped by each milestone so a live validator can tell which build is running.
MILESTONE = 1
STAMP_PREFIX = "[Grandstand] view active"

_FLAG = "TTMT_GRANDSTAND"


def grandstand_enabled() -> bool:
    """True when the new launcher view is selected. Any value other than "1"
    is off, so a stale empty export cannot half-enable it."""
    return os.environ.get(_FLAG, "") == "1"


class _AdvisoryLabel(QLabel):
    """Single-line strip copy that never dictates the view's width."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._full_text = ""
        self.setWordWrap(False)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)

    def set_copy(self, text: str, tooltip: str) -> None:
        self._full_text = text
        self.setToolTip(tooltip)
        super().setText(text)
        if self.isVisible():
            self._elide()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._elide()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._elide()

    def _elide(self) -> None:
        super().setText(self.fontMetrics().elidedText(
            self._full_text, Qt.ElideRight, self.contentsRect().width()))


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
        self._credential_kind = "ok"
        self._entries: dict[str, list] = {"ttr": [], "cc": []}
        self._main_names: dict[str, dict] = {"ttr": {}, "cc": {}}

        self.setObjectName("grandstand_view")

        root = QVBoxLayout(self)
        root.setContentsMargins(*STACK_MARGINS)
        root.setSpacing(STACK_GAP)

        self.advisory = QFrame(self)
        self.advisory.setObjectName("gs_advisory")
        self.advisory.setFixedHeight(26)
        self.advisory.setVisible(False)
        adv = QHBoxLayout(self.advisory)
        adv.setContentsMargins(12, 0, 12, 0)
        self.advisory_label = _AdvisoryLabel(self.advisory)
        adv.addWidget(self.advisory_label)
        root.addWidget(self.advisory)

        from utils.widgets.grandstand.game_selector import GameSelector
        self.selector = GameSelector(self)
        self.selector.setFixedHeight(SELECTOR_H)
        self.selector.set_active(self._party.active_game())
        self.selector.game_clicked.connect(self._on_game_clicked)
        root.addWidget(self.selector)

        from utils.widgets.grandstand.hero_stage import HeroStage
        self.hero = HeroStage(self)
        self.hero.setFixedHeight(HERO_H)
        self.hero.set_game(self._party.active_game())
        self.hero.play_clicked.connect(self._on_play)
        self.hero.official_clicked.connect(self._emit_official_launcher_intent)
        root.addWidget(self.hero)

        from utils.widgets.grandstand.card_shelf import CardShelf
        self.shelf = CardShelf(self)
        root.addWidget(self.shelf, 1)         # the only stretching band

        self.shelf.card_clicked.connect(self._on_card_clicked)
        self.shelf.star_clicked.connect(self._on_star_clicked)
        self.shelf.edit_clicked.connect(
            lambda aid: self.edit_requested.emit(
                self._party.active_game(), aid, "appearance"))
        self.shelf.gear_clicked.connect(
            lambda aid: self.edit_requested.emit(
                self._party.active_game(), aid, "account"))
        self.shelf.launch_clicked.connect(
            lambda aid: self._emit_card_launch_intent(self.launch_requested, aid))
        for shelf_sig, view_sig in (
                (self.shelf.cancel_clicked, self.cancel_requested),
                (self.shelf.quit_clicked, self.quit_requested),
                (self.shelf.enter_2fa_clicked, self.enter_2fa_requested)):
            shelf_sig.connect(
                lambda aid, s=view_sig: s.emit(self._party.active_game(), aid))
        self.shelf.retry_clicked.connect(
            lambda aid: self._emit_card_launch_intent(self.retry_requested, aid))
        self.shelf.add_account_clicked.connect(
            lambda: self.add_account_requested.emit(self._party.active_game()))
        self.shelf.manage_clicked.connect(
            lambda: self.manage_requested.emit(self._party.active_game()))
        self.shelf.clear_selection_clicked.connect(self._on_clear_selection)
        self.shelf.clear_main_clicked.connect(self._on_clear_main)

        self.apply_theme(self._is_dark)

    def _make_band(self, name: str, height: int) -> QFrame:
        f = QFrame(self)
        f.setObjectName(name)
        f.setFixedHeight(height)
        return f

    # ── inbound ────────────────────────────────────────────────────────────

    def active_game(self) -> str:
        return self._party.active_game()

    def party(self):
        return self._party

    def is_credential_blocked(self) -> bool:
        """Whether credential state forbids starting any new process."""
        return self._credential_kind == "blocked"

    def set_main_toon_names(self, game: str, mapping: dict) -> None:
        """account_id -> toon name for ONE game, used for the greeting and the
        party list. Per game because the greeting belongs to the active game;
        a single shared dict lets one game's render erase the other's."""
        self._main_names[game] = dict(mapping)
        self.refresh(game)

    def set_accounts(self, game: str, entries: list) -> None:
        self._entries[game] = list(entries)
        self.selector.set_counts(len(self._entries["ttr"]), len(self._entries["cc"]))
        if game == self._party.active_game():
            self.shelf.set_entries(self._entries[game])
            self.refresh(game)

    def set_account_state(self, game: str, account_id: str, state: str,
                          message: str = "", raw: str = "") -> None:
        """Route one account's live launch state to its card. Unknown ids are
        ignored — a state can arrive for an account already deleted."""
        if game == self._party.active_game():
            self.shelf.set_state(account_id, state, message, raw)

    def set_credential_state(self, kind: str, reason: str = "",
                             action_text: str = "", on_action=None) -> None:
        """Route a credential condition to the surface it deserves (spec Q6).

        'blocked' means launching is impossible, so the hero — which otherwise
        promises a greeting and a Play button — carries the reason instead.
        'advisory' means degraded but launchable, so it gets the slim strip and
        the launcher keeps working.
        """
        self._credential_kind = kind
        if kind == "blocked":
            self.advisory.setVisible(False)
            self.layout().setSpacing(STACK_GAP)
            fallback = MACOS_VAULT_COPY["denied"].hero_reason()
            self.hero.set_blocked(reason or fallback, action_text, on_action)
            return
        self.hero.set_blocked(None)
        if kind == "advisory":
            strip = reason or KEYRING_WARNING_COPY.advisory_reason()
            tooltip = reason or KEYRING_WARNING_COPY.body
            self.advisory.setVisible(True)
            self.advisory_label.set_copy(strip, tooltip)
            # The strip creates a fourth band. Tighten all three gaps by 2px
            # so the natural stack remains inside the fixed 688px content area.
            self.layout().setSpacing(ADVISORY_STACK_GAP)
        else:
            self.advisory.setVisible(False)
            self.layout().setSpacing(STACK_GAP)

    def apply_theme(self, is_dark: bool) -> None:
        self._is_dark = is_dark
        a = gp.advisory_strip(is_dark)
        self.advisory.setStyleSheet(
            f"QFrame#gs_advisory {{ background: {a['bg'].name(QColor.HexArgb)};"
            f" border: 1px solid {a['border'].name(QColor.HexArgb)};"
            " border-radius: 8px; }")
        self.advisory_label.setStyleSheet(
            f"color: {a['ink'].name()}; font-size: 11px; background: transparent;")
        self.selector.apply_theme(is_dark)
        self.hero.apply_theme(is_dark)
        self.hero.crew_area.apply_theme(is_dark)
        self.shelf.apply_theme(is_dark)

    def _on_game_clicked(self, game: str) -> None:
        if game == self._party.active_game():
            return
        self._party.set_active_game(game)
        self.selector.set_active(game)
        self.hero.set_game(game)
        self.shelf.set_entries(self._entries[game])
        self.refresh(game)
        self.game_changed.emit(game)

    def _on_card_clicked(self, account_id: str) -> None:
        game = self._party.active_game()
        if not self._party.toggle(game, account_id):
            self.shelf.shake(account_id)      # a refused fifth (spec §7)
            return
        self.refresh(game)
        self.party_changed.emit(game)

    def _emit_card_launch_intent(self, signal, account_id: str) -> None:
        """Forward Launch/Retry only while credentials permit new launches."""
        if not self.is_credential_blocked():
            signal.emit(self._party.active_game(), account_id)

    def _emit_official_launcher_intent(self) -> None:
        if not self.is_credential_blocked():
            self.official_launcher_requested.emit(self._party.active_game())

    def _on_star_clicked(self, account_id: str) -> None:
        game = self._party.active_game()
        new = None if self._party.star(game) == account_id else account_id
        self._party.set_star(game, new)
        self.refresh(game)
        self.star_changed.emit(game, new)

    def _on_clear_selection(self) -> None:
        game = self._party.active_game()
        self._party.clear(game)
        self.refresh(game)
        self.party_changed.emit(game)

    def _on_clear_main(self) -> None:
        game = self._party.active_game()
        self._party.set_star(game, None)
        self.refresh(game)
        self.star_changed.emit(game, None)

    def refresh(self, game: str) -> None:
        """Repaint every surface from current state. Cheap: the shelf only
        restyles, and the lineup diffs (Task 8), so a selection change animates
        rather than rebuilds."""
        if game != self._party.active_game():
            return
        from utils.widgets.grandstand.model import lineup_entries

        entries = self._entries[game]
        selected = self._party.selected(game)
        star = self._party.star(game)
        # One stage order for both surfaces: the ribbon shows the toon's
        # stage position (handoff §4.1d) and the star launches first (spec
        # Q3), so ribbons and lineup both read launch_order, never raw
        # selection order.
        order = self._party.launch_order(game)

        self.shelf.set_selection(order, star)
        self.shelf.set_links_enabled(
            clear_selection=bool(selected), clear_main=star is not None)

        by_id = {e.account_id: e for e in entries}
        self.hero.set_party([
            (by_id[aid].display_name if aid in by_id else aid) for aid in selected])
        names = self._main_names.get(game, {})
        self.hero.set_main(names.get(star) if star else None)
        poses = {entry.account_id: entry.pose for entry in entries}
        self.hero.set_lineup(lineup_entries(entries, order, poses=poses))

    def _on_play(self) -> None:
        if self.is_credential_blocked():
            return
        game = self._party.active_game()
        order = self._party.launch_order(game)
        if order:
            self.party_launch_requested.emit(game, order)
