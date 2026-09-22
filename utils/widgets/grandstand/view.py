"""GrandstandView — the roster stack, and the composition root for sub-project A.

Owns layout and intent, never behaviour: it emits what the user asked for and
LaunchTab performs it. Nothing here touches a login worker, a patcher or a
credential.

Built only when TTMT_GRANDSTAND=1 until the cut-over task removes the flag.
"""
from __future__ import annotations

import dataclasses
import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QSizePolicy, QStackedWidget, QVBoxLayout,
    QWidget,
)

from utils.credential_copy import KEYRING_WARNING_COPY, MACOS_VAULT_COPY
from utils.widgets.grandstand import palette as gp
from utils.widgets.grandstand.account_sheet import (
    CROSS_LINK, note_for, subtitle_for, title_for,
)
from utils.widgets.grandstand.draft import MODE_ADD, AccountDraft

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

# Running-code stamp for sub-project C, printed on every sheet-surface open:
# "[Grandstand] sheet: account <id>" / "... account add" / "... toon-browser <id>".
SHEET_STAMP_PREFIX = "[Grandstand] sheet:"

# Body pages and the shelf's slot (spec §2).
PAGE_ROSTER = 0
PAGE_SHEET = 1
SLOT_SHELF = 0
SLOT_BROWSER = 1

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

    # Sub-project C: the view emits intents; LaunchTab owns every write.
    account_save_requested = Signal(str, object)      # game, AccountDraft
    account_remove_requested = Signal(str, str)       # game, account_id
    toon_chosen = Signal(str, str, str)               # game, account_id, toon

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
        # Focus-mode state (spec §2): the sheet's game and the account's raw
        # toon records, kept so the browser can reopen the same sheet.
        self._sheet_game: str | None = None
        self._sheet_toons: list = []
        self._sheet_primary: str | None = None
        self._browser_account: str | None = None
        self._browser_return_to = "settings"
        # The last live launch state per (game, account): a RosterEntry only
        # carries the state at render time, and the sheet's preview must open
        # showing what the card shows now.
        self._live_states: dict[tuple[str, str], tuple] = {}

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

        # Page 0 is the roster stack, page 1 the focus-mode sheet (spec §2).
        # Both are plain containers under the app's global QWidget rule, so
        # each opts out of painting the page colour over its children.
        self.pages = QStackedWidget(self)
        self.pages.setObjectName("gs_pages")
        self.pages.setStyleSheet("#gs_pages { background: transparent; }")
        root.addWidget(self.pages, 1)

        self.roster_page = QWidget(self.pages)
        self.roster_page.setObjectName("gs_roster_page")
        self.roster_page.setStyleSheet("#gs_roster_page { background: transparent; }")
        stack = QVBoxLayout(self.roster_page)
        stack.setContentsMargins(0, 0, 0, 0)
        stack.setSpacing(STACK_GAP)

        from utils.widgets.grandstand.game_selector import GameSelector
        self.selector = GameSelector(self.roster_page)
        self.selector.setFixedHeight(SELECTOR_H)
        self.selector.set_active(self._party.active_game())
        self.selector.game_clicked.connect(self._on_game_clicked)
        stack.addWidget(self.selector)

        from utils.widgets.grandstand.hero_stage import HeroStage
        self.hero = HeroStage(self.roster_page)
        self.hero.setFixedHeight(HERO_H)
        self.hero.set_game(self._party.active_game())
        self.hero.play_clicked.connect(self._on_play)
        self.hero.official_clicked.connect(self._emit_official_launcher_intent)
        stack.addWidget(self.hero)

        # The shelf's slot: the shelf now, the toon browser beside it from
        # Task 6 (handoff §4.7 — the shelf swaps in place, the stage stays put).
        self.shelf_stack = QStackedWidget(self.roster_page)
        self.shelf_stack.setObjectName("gs_shelf_stack")
        self.shelf_stack.setStyleSheet("#gs_shelf_stack { background: transparent; }")
        from utils.widgets.grandstand.card_shelf import CardShelf
        from utils.widgets.grandstand.toon_browser import ToonBrowser
        self.shelf = CardShelf(self.shelf_stack)
        self.shelf_stack.addWidget(self.shelf)
        self.browser = ToonBrowser(self.shelf_stack)
        self.shelf_stack.addWidget(self.browser)
        self.shelf_stack.setCurrentIndex(SLOT_SHELF)
        stack.addWidget(self.shelf_stack, 1)          # the only stretching band
        self.pages.addWidget(self.roster_page)

        from utils.widgets.grandstand.sheet import SheetShell
        from utils.widgets.grandstand.account_sheet import AccountSheet
        self.sheet = SheetShell(self.pages)
        self.account_sheet = AccountSheet(self.sheet)
        self.sheet.set_body(self.account_sheet)
        self.pages.addWidget(self.sheet)
        self.pages.setCurrentIndex(PAGE_ROSTER)

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

        self.sheet.back_requested.connect(self.close_sheet)
        self.sheet.cancel_requested.connect(self.close_sheet)
        self.sheet.save_requested.connect(self._on_sheet_save)
        self.sheet.cross_link_requested.connect(self._on_sheet_cross_link)
        self.account_sheet.remove_requested.connect(self._on_sheet_remove)
        self.account_sheet.choose_toon_requested.connect(self._on_choose_toon)
        self.browser.back_requested.connect(self.close_toon_browser)
        self.browser.toon_picked.connect(self._on_toon_picked)

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

    def entry_for(self, game: str, account_id: str):
        """The RosterEntry the view currently holds for one account, or None.
        Lets the owner decide whether a fresh entry would change anything
        before it pays for a rebuild."""
        return next((e for e in self._entries[game]
                     if e.account_id == account_id), None)

    def set_accounts(self, game: str, entries: list) -> None:
        self._entries[game] = list(entries)
        # Fresh entries carry LaunchTab's effective state; anything remembered
        # from before this render is older than they are.
        self._live_states = {k: v for k, v in self._live_states.items()
                             if k[0] != game}
        self.selector.set_counts(len(self._entries["ttr"]), len(self._entries["cc"]))
        if game == self._party.active_game():
            self.shelf.set_entries(self._entries[game])
            self.refresh(game)
            self._reconcile_focus(game)

    def _reconcile_focus(self, game: str) -> None:
        """An open sheet or browser follows its account (spec §4): one removed
        underneath (Manage, another tab) closes the surface; one that
        survives feeds the preview its fresh state and accent."""
        ids = {e.account_id for e in self._entries[game]}
        if self._browser_account is not None and self._browser_account not in ids:
            self.close_sheet()
            return
        aid = self.account_sheet.account_id()
        if not aid:
            return                                   # closed, or add mode
        if aid not in ids:
            self.close_sheet()
            return
        self.account_sheet.set_base_entry(self.entry_for(game, aid))

    def set_account_state(self, game: str, account_id: str, state: str,
                          message: str = "", raw: str = "") -> None:
        """Route one account's live launch state to its card — and to the
        sheet's preview while that account is open (spec §4). Unknown ids
        are ignored: a state can arrive for an account already deleted."""
        self._live_states[(game, account_id)] = (state, message, raw)
        if game == self._party.active_game():
            self.shelf.set_state(account_id, state, message, raw)
            if self.account_sheet.account_id() == account_id:
                self.account_sheet.set_account_state(state, message, raw)

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
            self._set_stack_gap(STACK_GAP)
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
            self._set_stack_gap(ADVISORY_STACK_GAP)
        else:
            self.advisory.setVisible(False)
            self._set_stack_gap(STACK_GAP)

    def _set_stack_gap(self, gap: int) -> None:
        """The advisory strip's tighter gap applies between every band: the
        root gap (strip -> pages) and the roster page's own gaps."""
        self.layout().setSpacing(gap)
        self.roster_page.layout().setSpacing(gap)

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
        self.sheet.apply_theme(is_dark)               # forwards to the body
        self.browser.apply_theme(is_dark)

    def _on_game_clicked(self, game: str) -> None:
        if game == self._party.active_game():
            return
        # The selector lives on page 0, so this cannot happen from the UI
        # while a sheet is open; a programmatic switch drops the draft first.
        if self.in_focus_mode():
            self.close_sheet()
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
        # One stage order everywhere: the ribbon shows the toon's stage
        # position (handoff §4.1d) and the star launches first (spec Q3), so
        # ribbons, the names line and the lineup all read launch_order, never
        # raw selection order.
        order = self._party.launch_order(game)

        self.shelf.set_selection(order, star)
        self.shelf.set_links_enabled(
            clear_selection=bool(selected), clear_main=star is not None)

        by_id = {e.account_id: e for e in entries}
        self.hero.set_party([
            (by_id[aid].display_name if aid in by_id else aid) for aid in order])
        names = self._main_names.get(game, {})
        self.hero.set_main(names.get(star) if star else None)
        self.hero.set_lineup(lineup_entries(entries, order))

    def _on_play(self) -> None:
        if self.is_credential_blocked():
            return
        game = self._party.active_game()
        order = self._party.launch_order(game)
        if order:
            self.party_launch_requested.emit(game, order)

    # ── focus mode: the account sheet (spec §2, §3) ────────────────────────

    def in_focus_mode(self) -> bool:
        return self.pages.currentIndex() == PAGE_SHEET

    def browser_open(self) -> bool:
        return self.shelf_stack.currentIndex() == SLOT_BROWSER

    def open_account_sheet(self, game: str, draft: AccountDraft, toons: list,
                           primary_name) -> None:
        """Enter focus mode on the account surface. `toons` is the account's
        raw record list, newest first; the sheet collapses rename ghosts."""
        if self.browser_open():
            self.shelf_stack.setCurrentIndex(SLOT_SHELF)
        self._sheet_game = game
        self._sheet_toons = list(toons)
        self._sheet_primary = primary_name
        self._log(f"{SHEET_STAMP_PREFIX} account {draft.id or 'add'}")
        base = self.entry_for(game, draft.id) if draft.id else None
        self.account_sheet.open(draft, self._sheet_toons, primary_name, base)
        live = self._live_states.get((game, draft.id)) if draft.id else None
        if live is not None:
            self.account_sheet.set_account_state(*live)
        self.sheet.set_header(title_for(draft), subtitle_for(draft))
        self.sheet.set_cross_link("" if draft.mode == MODE_ADD else CROSS_LINK)
        self.sheet.set_note(note_for(self.account_sheet.toon_count()))
        self._go_to_page(PAGE_SHEET)
        self.account_sheet.focus_first()

    def close_sheet(self) -> None:
        """Leave focus mode. The draft is dropped; nothing is written."""
        if self.browser_open():
            self.shelf_stack.setCurrentIndex(SLOT_SHELF)
        self._browser_account = None
        if self.in_focus_mode():
            self._go_to_page(PAGE_ROSTER)
        self.account_sheet.clear()
        self._sheet_game = None
        self._sheet_toons = []
        self._sheet_primary = None

    def _go_to_page(self, index: int) -> None:
        """Plain switch for now; Task 7 adds the handoff's collapse."""
        self.pages.setCurrentIndex(index)

    def _on_sheet_save(self) -> None:
        """Validate, then hand the draft to the owner. Errors repaint inline
        and the sheet stays open; the view never writes and never closes on
        its own — LaunchTab calls close_sheet() after the write (spec §3)."""
        draft = self.account_sheet.draft()
        if draft is None or self._sheet_game is None:
            return
        errors = draft.validate()
        if errors:
            self.account_sheet.show_errors(errors)
            return
        self.account_sheet.clear_errors()
        # A snapshot, not the live draft: the sheet stays open across the
        # emit, so the consumer must not observe edits made afterwards.
        self.account_save_requested.emit(
            self._sheet_game, dataclasses.replace(draft))

    def _on_sheet_cross_link(self) -> None:
        """One cross-link, pointing at the surface you are not on (handoff
        §4.5). Until sub-project B it routes exactly where the pencil does."""
        draft = self.account_sheet.draft()
        if draft is None or self._sheet_game is None or not draft.id:
            return
        self.edit_requested.emit(self._sheet_game, draft.id, "appearance")

    def _on_sheet_remove(self) -> None:
        """The danger button. Confirmation and the delete belong to the owner
        (spec §3 "Remove"); the sheet stays until the owner closes it."""
        draft = self.account_sheet.draft()
        if draft is None or self._sheet_game is None or not draft.id:
            return
        self.account_remove_requested.emit(self._sheet_game, draft.id)

    # ── the choose-a-toon browser (spec §3 "Choose toon") ──────────────────

    def _on_choose_toon(self) -> None:
        draft = self.account_sheet.draft()
        if draft is None or self._sheet_game is None or not draft.id:
            return
        self.open_toon_browser(self._sheet_game, draft.id, self._sheet_toons,
                               self._sheet_primary, return_to="settings")

    def open_toon_browser(self, game: str, account_id: str, toons: list,
                          primary_name, return_to: str = "settings") -> None:
        """A shelf-level surface (handoff §4.7): the browser takes the shelf's
        slot on page 0 so the selector and hero stay put. An open sheet keeps
        its draft in memory; `return_to` says where Back / a pick lands."""
        self._browser_account = account_id
        self._browser_return_to = return_to
        self._log(f"{SHEET_STAMP_PREFIX} toon-browser {account_id}")
        draft = self.account_sheet.draft()
        if draft is not None and draft.id == account_id:
            display = draft.display_name
        else:
            entry = self.entry_for(game, account_id)
            display = (entry.label or entry.username) if entry is not None else account_id
        self.browser.open(game, account_id, display, toons, primary_name)
        self.shelf_stack.setCurrentIndex(SLOT_BROWSER)
        if self.in_focus_mode():
            self._go_to_page(PAGE_ROSTER)
        self.browser.focus_current()

    def close_toon_browser(self, primary_name=None) -> None:
        """Back to wherever the browser was opened from. With `primary_name`
        (a pick the owner just committed) the sheet's row follows and the
        hero is rebuilt for the new identity (handoff §6.3)."""
        self.shelf_stack.setCurrentIndex(SLOT_SHELF)
        self._browser_account = None
        game = self._sheet_game or self._party.active_game()
        if primary_name is not None:
            self._sheet_primary = primary_name
            if self.account_sheet.is_open():
                self.account_sheet.set_toons(self._sheet_toons, primary_name)
            self._rebuild_lineup(game)
        if self._browser_return_to == "settings" and self.account_sheet.is_open():
            self._go_to_page(PAGE_SHEET)
            self.account_sheet.choose_button.setFocus()

    def _rebuild_lineup(self, game: str) -> None:
        """Handoff §6.3: a primary-toon change is a new identity, not an
        animation between two, so the lineup is emptied and rebuilt rather
        than diffed into place."""
        self.hero.set_lineup([])
        self.refresh(game)

    def _on_toon_picked(self, toon_name: str) -> None:
        if self._browser_account is None:
            return
        self.toon_chosen.emit(self._party.active_game(), self._browser_account, toon_name)
