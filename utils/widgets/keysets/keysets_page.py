"""KeysetsPage — the top-level Keysets container Settings mounts.

Owns the picker<->editor swap and the game gate. Given the set of *active*
games (a game is active when its install is detected OR the user has accounts
for it), it decides what to show:

  * >= 2 active  -> GamePickerView, with a "‹ All games" back button in the
                    editor so the user can return to the picker.
  * == 1 active  -> that game's SplitEditor directly (no picker, no back).
  * == 0 active  -> the TTR SplitEditor directly (keysets are always sendable).

The game-detection predicates and the Detect-apply path are ported out of the
old tabs/keymap_tab.py (which is being deleted); the predicates are byte-
faithful, and the detect-apply logic lives in the sibling detect.py module.

Importing this module builds NOTHING at import time — no tab, no InputService,
no credentials probe. Widgets are constructed only when KeysetsPage() is
instantiated.
"""

from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QPushButton, QStackedWidget, QVBoxLayout, QWidget,
)

from utils.theme_manager import resolve_theme
from . import detect
from .game_meta import GAME_META
from .game_picker import GamePickerView
from .split_editor import SplitEditor


class KeysetsPage(QWidget):
    """Picker/editor state machine + game gate for the Keysets surface."""

    def __init__(self, keymap_manager, settings_manager, credentials_manager,
                 parent=None):
        super().__init__(parent)
        self.keymap_manager = keymap_manager
        self.settings_manager = settings_manager
        self.credentials_manager = credentials_manager

        is_dark = resolve_theme(self.settings_manager) == "dark"

        # Guards re-entrant re-gating from showEvent.
        self._regating = False
        # The game currently loaded in the editor (None while the picker shows).
        self._current_game: str | None = None
        # Snapshot of the active-game set at last render, for showEvent re-gate.
        self._last_active: set = set()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._stack = QStackedWidget(self)
        outer.addWidget(self._stack)

        # ── Page 0: the game picker ─────────────────────────────────────────
        self._picker = GamePickerView(is_dark, self)
        self._picker.game_chosen.connect(self._show_editor)
        self._stack.addWidget(self._picker)

        # ── Page 1: back button + the split editor ─────────────────────────
        editor_container = QWidget(self)
        ec_layout = QVBoxLayout(editor_container)
        ec_layout.setContentsMargins(0, 0, 0, 0)
        ec_layout.setSpacing(0)

        self._back_btn = QPushButton("‹ All games", editor_container)
        self._back_btn.setCursor(Qt.PointingHandCursor)
        self._back_btn.setFixedHeight(30)
        self._back_btn.clicked.connect(self._show_picker)
        ec_layout.addWidget(self._back_btn, 0, Qt.AlignLeft)

        self._editor = SplitEditor(self.keymap_manager, is_dark, editor_container)
        self._editor.set_detect_callback(self._on_detect_settings_for_game)
        ec_layout.addWidget(self._editor, 1)

        self._stack.addWidget(editor_container)

        self._style_back_button(is_dark)

        # ── Initial gate ────────────────────────────────────────────────────
        active = self._active_games()
        self._last_active = set(active)
        if len(active) >= 2:
            self._show_picker()
        elif len(active) == 1:
            self._show_editor(next(iter(active)))
        else:
            self._show_editor("ttr")

    # ── Game detection predicates (ported verbatim from keymap_tab.py) ──────
    def _ttr_detected(self) -> bool:
        if self.settings_manager is None:
            return False
        engine = self.settings_manager.get("ttr_engine_dir", "")
        if engine and os.path.exists(engine):
            return True
        try:
            from services.ttr_login_service import find_engine_path
            return bool(find_engine_path())
        except Exception:
            return False

    def _cc_detected(self) -> bool:
        if self.settings_manager is None:
            return False
        engine = self.settings_manager.get("cc_engine_dir", "")
        if engine and os.path.exists(engine):
            return True
        try:
            from services.wine_runtimes import discover_cc_installs
            return bool(discover_cc_installs())
        except Exception:
            return False

    def _default_set_locked(self, game: str) -> bool:
        """True when a game config file is present and drives this game's
        Default set, so its key fields must not be hand-editable.

        TTR: settings.json is located (the startup auto-detect re-applies it
        every launch, so hand edits are clobbered anyway), OR the cached
        last-detected keymap exists (the startup fallback re-applies THAT
        when settings.json is momentarily unreadable - edits made in such a
        window would be silently lost, so the lock holds).
        CC: any discovered install resolves a preferences.json.
        No config source at all -> editable."""
        if game == "ttr":
            try:
                from utils.ttr_settings import locate_settings_file
                from services.ttr_login_service import find_engine_path
            except Exception:
                return False
            engine = ""
            if self.settings_manager is not None:
                engine = self.settings_manager.get("ttr_engine_dir", "") or ""
            if not engine or not os.path.exists(engine):
                try:
                    engine = find_engine_path() or ""
                except Exception:
                    engine = ""
            try:
                if locate_settings_file(engine_dir=engine or None):
                    return True
            except Exception:
                pass
            if self.settings_manager is not None:
                cached = self.settings_manager.get("last_detected_keymap", None)
                if isinstance(cached, dict) and cached:
                    return True
            return False
        try:
            from utils.cc_settings import locate_cc_preferences
            from services.wine_runtimes import discover_cc_installs
        except Exception:
            return False
        try:
            installs = discover_cc_installs() or []
        except Exception:
            return False
        for install in installs:
            try:
                if locate_cc_preferences(install):
                    return True
            except Exception:
                continue
        return False

    def _has_accounts(self, game: str) -> bool:
        if self.credentials_manager is None:
            return False
        return bool(self.credentials_manager.get_accounts_metadata(game=game))

    def _active_games(self) -> set:
        games = set()
        if self._ttr_detected() or self._has_accounts("ttr"):
            games.add("ttr")
        if self._cc_detected() or self._has_accounts("cc"):
            games.add("cc")
        return games

    # ── Navigation ──────────────────────────────────────────────────────────
    def _show_picker(self) -> None:
        active = self._active_games()
        # Present games in canonical order (TTR before CC), not alphabetical.
        entries = [(g, self.keymap_manager.num_sets(g))
                   for g in GAME_META if g in active]
        self._picker.set_games(entries)
        self._current_game = None
        self._back_btn.setVisible(False)
        self._stack.setCurrentIndex(0)

    def _show_editor(self, game: str) -> None:
        active = self._active_games()
        self._editor.set_game(game, default_locked=self._default_set_locked(game))
        self._current_game = game
        self._back_btn.setVisible(len(active) >= 2)
        self._stack.setCurrentIndex(1)

    def current_game(self) -> str | None:
        """The game shown in the editor, or None while the picker is up."""
        if self._stack.currentIndex() == 0:
            return None
        return self._current_game

    def show_picker_if_available(self) -> bool:
        """Return to the game picker - the same action as the editor's
        "All games" back button. No-op (returns False) when fewer than two
        games are active (no picker exists) or the picker is already showing.
        Lets the host treat a re-click on the Keysets chip as a back action."""
        if len(self._active_games()) >= 2 and self._stack.currentIndex() != 0:
            self._show_picker()
            return True
        return False

    # ── Detect-apply (Detect button in the editor) ─────────────────────────
    def _on_detect_settings_for_game(self, game: str) -> None:
        """Apply the live game config to the Default set, then reload the
        editor so its lock state + values reflect the freshly detected keys.
        SplitEditor._on_detect refreshes the detail view after this returns."""
        updates = detect.detect_settings_for_game(
            game, self.keymap_manager, self.settings_manager)
        if updates > 0:
            self._editor.set_game(
                game, default_locked=self._default_set_locked(game))

    # ── Theme ────────────────────────────────────────────────────────────────
    def refresh_theme(self) -> None:
        is_dark = resolve_theme(self.settings_manager) == "dark"
        self._picker.apply_theme(is_dark)
        self._editor.apply_theme(is_dark)
        self._style_back_button(is_dark)

    def _style_back_button(self, is_dark: bool) -> None:
        self._back_btn.setStyleSheet(
            "QPushButton {"
            " background: rgba(255,255,255,0.05);"
            " border: 1px solid rgba(255,255,255,0.14);"
            " border-radius: 8px;"
            " color: #ffffff;"
            " padding: 0 14px;"
            " font-size: 12px; font-weight: 600;"
            "}"
            "QPushButton:hover {"
            " background: rgba(255,255,255,0.10);"
            " border: 1px solid rgba(255,255,255,0.22);"
            "}"
        )

    # ── Re-gate on show ──────────────────────────────────────────────────────
    def showEvent(self, e) -> None:
        super().showEvent(e)
        if self._regating:
            return
        active = self._active_games()
        if active == self._last_active:
            return
        # A game was installed/removed since we last rendered: re-run the gate.
        # Don't clobber an in-progress edit when the shown game is still valid.
        self._regating = True
        try:
            self._last_active = set(active)
            if len(active) >= 2:
                if self.current_game() is None:
                    self._show_picker()
                else:
                    # Keep editing the current game, but surface the back button.
                    self._back_btn.setVisible(True)
            elif len(active) == 1:
                self._show_editor(next(iter(active)))
            else:
                self._show_editor("ttr")
        finally:
            self._regating = False
