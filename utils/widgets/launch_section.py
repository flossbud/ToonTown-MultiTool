"""Section in the Launch tab: header strip (game icon + title + launcher
button) + 2-column tile grid + empty-state fallback. Owns the per-tile
widgets and re-emits their signals with the section_index attached."""
from __future__ import annotations

from PySide6.QtCore import QPropertyAnimation, QTimer, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget,
)

import utils.motion as motion
from utils.theme_manager import get_theme_colors
from utils.widgets.account_tile import AccountTile
from utils.widgets.chip_button import QuietChipButton
from utils.widgets.empty_state import EmptyState


_GAME_NAMES = {"ttr": "Toontown Rewritten", "cc": "Corporate Clash"}
_GAME_SHORT = {"ttr": "TTR", "cc": "CC"}
_LAYOUT_MAX_WIDTH = {"compact": 720, "full": 860}
# Reference widths for content-scale calc. At reference width, scale=1.0.
# Below reference, scale=1.0 (we never shrink content). Above reference,
# scale grows linearly with width, clamped to [1.0, 1.4] so that fonts
# don't grow absurdly on 4K monitors.
# Reference is lower than the mode's max-width so there is headroom for
# the scale to exceed 1.0 before the widget hits its maximum-width cap.
_REF_WIDTH = {"compact": 540, "full": 720}
_SCALE_CLAMP_MAX = 1.4


class _AddTile(QuietChipButton):
    """Dashed-outline "+ Add Account" tile, matches grid cell size.
    Uses QuietChipButton (no hover upscale, 0.96 press scale)."""
    def __init__(self, game: str, parent=None):
        super().__init__(parent)
        self._game = game
        self.setText(f"+ Add {_GAME_SHORT[game]} Account")
        self.setMinimumHeight(130)
        self.setCursor(Qt.PointingHandCursor)
        self.apply_theme(get_theme_colors(True))

    def apply_theme(self, c: dict) -> None:
        """Rebuild QSS from the theme dict `c`."""
        self.setStyleSheet(
            "QToolButton { background: transparent;"
            f" border: 2px dashed {c['border_card']};"
            " border-radius: 10px;"
            f" color: {c['text_muted']};"
            " font-size: 13px; }"
            "QToolButton:hover {"
            f" border-color: {c['border_light']};"
            f" color: {c['text_secondary']};"
            f" background: {c['bg_card_inner_hover']};"
            " }"
        )


class LaunchSection(QWidget):
    REVEAL_STAGGER_MS = 30
    REVEAL_DURATION_MS = 150

    launcher_clicked       = Signal()
    add_account_clicked    = Signal()
    tile_launch            = Signal(int)
    tile_quit              = Signal(int)
    tile_cancel            = Signal(int)
    tile_retry             = Signal(int)
    tile_enter_2fa         = Signal(int)
    tile_edit              = Signal(int)
    tile_delete            = Signal(int)
    tile_expand_error      = Signal(int)
    # Fires when the section's natural sizeHint changes (content scale
    # bump on resize, account list change). LaunchTab listens so it can
    # re-equalize sibling section heights in compact mode.
    content_size_changed   = Signal()

    def __init__(self, game: str, icon_path: str, max_accounts: int = 8, parent=None):
        super().__init__(parent)
        # Compact-mode horizontal cap. Mirrors tabs/multitoon/_compact_layout.py:38-44.
        # In full mode (set via set_layout_mode), the cap is lifted so the
        # two sections can sit side-by-side and each fill ~half the window.
        self._max_width = 720
        self.setMaximumWidth(self._max_width)
        # Floor min-height keeps a card from collapsing visually when
        # empty; the actual matched-height enforcement is done at the
        # LaunchTab level via _sync_compact_section_heights.
        self.setMinimumHeight(380)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self._layout_mode = "compact"
        self._content_scale = 1.0
        assert game in ("ttr", "cc")
        self._game = game
        self._max = max_accounts
        self.tiles: list[AccountTile] = []
        self.add_tile: _AddTile | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Per-game card: a flat neutral container that wraps the header AND
        # the tile grid (or empty state) so the section reads as a unified
        # region. A 2 px coloured top stripe identifies the game without a
        # gradient wash competing with per-tile accent borders inside.
        self.card = QFrame()
        self.card.setObjectName("section_card")
        self.card.setAttribute(Qt.WA_StyledBackground, True)
        # Vertical Expanding so the card fills the section's allocated
        # height instead of shrinking to content. Without this the card
        # border ends just below the empty-state content, leaving the
        # bottom of the section bare and producing visibly uneven cards
        # when one section is populated and another is empty.
        self.card.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        # QSS applied via apply_theme(...) below so theme switches work.
        card_lay = QVBoxLayout(self.card)
        # 1px inset prevents children from overpainting the card's
        # rounded corners + border. The card's QSS bg fills the inset
        # gap so the border is visible all the way around.
        card_lay.setContentsMargins(1, 1, 1, 1)
        card_lay.setSpacing(0)
        outer.addWidget(self.card)

        # Header strip — sits inside the card. Transparent background with
        # a hairline below to separate it from the tile region. QSS applied
        # via apply_theme so theme switches work.
        header = QFrame()
        header.setObjectName("section_header")
        header.setAttribute(Qt.WA_StyledBackground, True)
        # QSS applied via apply_theme.
        self._header_frame = header  # save reference for re-styling
        head_lay = QHBoxLayout(header)
        head_lay.setContentsMargins(18, 14, 18, 14)
        head_lay.setSpacing(12)

        icon_box = QLabel()
        icon_box.setFixedSize(40, 40)
        # background: transparent so the flat card surface shows through
        # behind the icon (without it, Qt paints QLabel's default opaque
        # bg as soon as ANY QSS is applied, cutting out a rectangle).
        icon_box.setStyleSheet("background: transparent; border-radius: 8px;")
        pm = QPixmap(icon_path)
        if not pm.isNull():
            icon_box.setPixmap(pm.scaled(40, 40, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        head_lay.addWidget(icon_box)

        title_col = QVBoxLayout()
        title_col.setSpacing(0)
        self.title_label = QLabel(_GAME_NAMES[game])
        # QSS applied via apply_theme.
        title_col.addWidget(self.title_label)
        self.subline = QLabel("No accounts yet")
        # QSS applied via apply_theme.
        title_col.addWidget(self.subline)
        head_lay.addLayout(title_col)
        head_lay.addStretch()

        self.launcher_btn = QuietChipButton()
        self.launcher_btn.setText(f"↗ Launch {_GAME_SHORT[game]} Launcher")
        self.launcher_btn.setCursor(Qt.PointingHandCursor)
        # QSS applied via apply_theme.
        self.launcher_btn.clicked.connect(self.launcher_clicked.emit)
        head_lay.addWidget(self.launcher_btn)

        card_lay.addWidget(header)

        # _body_wrap holds everything that collapses (grid + empty state).
        # Lives between the header and the bottom stretch. Transparent so the
        # card surface paints through; otherwise QWidget's default opaque
        # background would cover the card's bg_card fill.
        self._body_wrap = QWidget()
        self._body_wrap.setAttribute(Qt.WA_TranslucentBackground, True)
        body_lay = QVBoxLayout(self._body_wrap)
        body_lay.setContentsMargins(0, 0, 0, 0)
        body_lay.setSpacing(0)

        # Make grid_container transparent so the flat card surface shows
        # through behind the tiles (otherwise QWidget paints its default
        # solid bg and covers the card's bg_card fill).
        self.grid_container = QWidget()
        self.grid_container.setAttribute(Qt.WA_TranslucentBackground, True)
        self.grid = QGridLayout(self.grid_container)
        self.grid.setContentsMargins(14, 14, 14, 14)
        self.grid.setSpacing(10)
        body_lay.addWidget(self.grid_container)

        self.empty_state = EmptyState(game=game)
        self.empty_state.setAttribute(Qt.WA_TranslucentBackground, True)
        self.empty_state.add_clicked.connect(self.add_account_clicked.emit)
        body_lay.addWidget(self.empty_state)

        card_lay.addWidget(self._body_wrap)

        # A bottom stretch absorbs slack so the card keeps the header +
        # content at the TOP and any extra vertical space (e.g. when a
        # sibling card in full mode is taller) becomes empty card area
        # at the bottom rather than vertically-stretching the content.
        card_lay.addStretch(1)

        # Cache dark default before apply_theme so _current_theme exists
        # even if anything triggers a recompute before apply_theme runs.
        self._current_theme = get_theme_colors(True)
        # Initial styling: dark default. LaunchTab.apply_theme() overrides
        # immediately with the user's actual theme.
        self.apply_theme(self._current_theme)

        self.set_accounts([])

    def apply_theme(self, c: dict) -> None:
        """Rebuild every QSS string against the theme dict `c`.
        Called on construction (dark default) and on every theme switch."""
        self._current_theme = c
        stripe = c["game_pill_ttr"] if self._game == "ttr" else c["game_pill_cc"]
        self.card.setStyleSheet(
            "QFrame#section_card {"
            f" background: {c['bg_card']};"
            f" border-left: 1px solid {c['border_card']};"
            f" border-right: 1px solid {c['border_card']};"
            f" border-bottom: 1px solid {c['border_card']};"
            f" border-top: 2px solid {stripe};"
            " border-radius: 10px;"
            "}"
        )
        self._header_frame.setStyleSheet(
            "QFrame#section_header {"
            " background: transparent;"
            f" border-bottom: 1px solid {c['border_muted']};"
            "}"
        )
        base_font_px = int(15 * self._content_scale)
        self.title_label.setStyleSheet(
            f"background: transparent; color: {c['text_primary']};"
            f" font-weight: 700; font-size: {base_font_px}px;"
        )
        self.subline.setStyleSheet(
            f"background: transparent; color: {c['text_muted']}; font-size: 12px;"
        )
        self.launcher_btn.setStyleSheet(
            "QToolButton {"
            " background: transparent;"
            f" border: 1px solid {c['border_muted']};"
            f" color: {c['text_secondary']};"
            " border-radius: 8px; padding: 8px 14px; font-size: 12px;"
            " font-weight: 600;"
            "}"
            "QToolButton:hover {"
            f" background: {c['bg_card_inner_hover']};"
            f" border-color: {c['border_card']};"
            "}"
        )
        # Propagate to children that own their own QSS.
        for tile in self.tiles:
            if hasattr(tile, "apply_theme"):
                tile.apply_theme(c)
        if self.add_tile is not None and hasattr(self.add_tile, "apply_theme"):
            self.add_tile.apply_theme(c)
        if hasattr(self.empty_state, "apply_theme"):
            self.empty_state.apply_theme(c)

    def set_accounts(self, accounts: list[dict]) -> None:
        while self.grid.count():
            item = self.grid.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        self.tiles = []
        self.add_tile = None

        if not accounts:
            self.empty_state.setVisible(True)
            self.grid_container.setVisible(False)
            self.subline.setText("No accounts yet")
            return

        self.empty_state.setVisible(False)
        self.grid_container.setVisible(True)
        for i, acct in enumerate(accounts):
            tile = AccountTile(game=self._game, slot_index=i)
            tile.set_account(acct.get("label", ""), acct.get("username", ""), i)
            row, col = divmod(i, 2)
            self.grid.addWidget(tile, row, col)
            self.tiles.append(tile)
            self._wire_tile(tile, i)

        self.add_tile = _AddTile(self._game)
        self.add_tile.clicked.connect(self.add_account_clicked.emit)
        n = len(accounts)
        row, col = divmod(n, 2)
        self.grid.addWidget(self.add_tile, row, col)
        if len(accounts) >= self._max:
            self.add_tile.setVisible(False)

        self.subline.setText(f"{len(accounts)} account" + ("s" if len(accounts) != 1 else ""))
        # New tiles are born at AccountTile's default minHeight=130; if the
        # section is currently scaled (e.g. account refresh after a window
        # resize bumped scale above 1.0), bring the fresh tiles up to the
        # current scale so they don't render at the wrong height.
        self._apply_content_scale_to_tiles()
        # Newly-created tiles default to dark theme via their own __init__.
        # Re-apply the section's current theme so they match light mode etc.
        self.apply_theme(self._current_theme)

    def tile_at(self, section_index: int) -> AccountTile | None:
        if 0 <= section_index < len(self.tiles):
            return self.tiles[section_index]
        return None

    def _recompute_content_scale(self) -> None:
        """Compute scale factor from current width vs. the mode's reference width.
        Update tile min-heights and section-header font sizes in lockstep.
        """
        ref = _REF_WIDTH.get(self._layout_mode, 720)
        if ref <= 0:
            return
        raw = self.width() / ref
        scale = max(1.0, min(raw, _SCALE_CLAMP_MAX))
        if abs(scale - self._content_scale) < 0.01:
            return
        self._content_scale = scale
        self._apply_content_scale_to_tiles()
        # Tile min-heights just changed, so the section's sizeHint did
        # too. Notify any listener (LaunchTab) that may need to re-sync
        # sibling-section heights.
        self.content_size_changed.emit()
        # Title font size baked into apply_theme(...) via self._content_scale.
        self.apply_theme(self._current_theme)

    def _apply_content_scale_to_tiles(self) -> None:
        """Apply the current _content_scale to every tile and add_tile.
        Called from _recompute_content_scale and from set_accounts (after
        new tiles are constructed at their default 130 minHeight)."""
        scaled_h = int(130 * self._content_scale)
        for tile in self.tiles:
            tile.setMinimumHeight(scaled_h)
        if self.add_tile is not None:
            self.add_tile.setMinimumHeight(scaled_h)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._recompute_content_scale()

    def set_layout_mode(self, mode: str) -> None:
        """Apply per-section sizing for the app-wide layout mode.

        Compact: capped at 720px so the section fills-then-centers.
        Full: capped at 860px so two sections sit side-by-side comfortably
        on a 1280-1720 wide window without each tile growing absurdly.

        No-op if the mode is unknown or already current — same-mode calls
        avoid both a redundant reveal flash and a redundant content-scale
        recompute.
        """
        if mode not in _LAYOUT_MAX_WIDTH:
            return
        if mode == self._layout_mode:
            return
        self._max_width = _LAYOUT_MAX_WIDTH[mode]
        self.setMaximumWidth(self._max_width)
        # Full mode: both cards must match heights so a populated TTR
        # card and an empty CC card don't look uneven side-by-side. Let
        # the QHBoxLayout stretch each card vertically; the bottom
        # stretch inside card_lay keeps content anchored at the top.
        # Compact mode: cards stack vertically, each at its natural size.
        if mode == "full":
            self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        else:
            self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self._layout_mode = mode
        self._recompute_content_scale()
        self._run_reveal_animation()

    def _run_reveal_animation(self) -> None:
        """Stagger-fade each tile from 0.0 to 1.0 opacity. Honors
        motion.is_reduced(): under reduced motion, opacities snap to 1.0.
        Per-tile animation via QPropertyAnimation on tile_opacity — does NOT
        use QGraphicsOpacityEffect (see main.py:819-825 for why)."""
        tiles = list(self.tiles)
        if not tiles:
            return
        if motion.is_reduced():
            for t in tiles:
                t.tile_opacity = 1.0
            return
        # Stop any in-flight reveal animations from a prior set_layout_mode
        # call BEFORE replacing the list — QPropertyAnimation has no C++
        # parent here, so its only liveness anchor is _reveal_anims. Drop
        # the list without stopping and PySide6 will GC running animations
        # mid-flight, leaving tiles stuck at partial opacity.
        for old in getattr(self, "_reveal_anims", []):
            old.stop()
        raw = self.REVEAL_DURATION_MS * motion._TEST_DURATION_SCALE
        duration = 0 if raw == 0.0 else max(1, int(raw))
        stagger_raw = self.REVEAL_STAGGER_MS * motion._TEST_DURATION_SCALE
        stagger = 0 if stagger_raw == 0.0 else max(1, int(stagger_raw))
        self._reveal_anims: list[QPropertyAnimation] = []
        for i, tile in enumerate(tiles):
            tile.tile_opacity = 0.0
            anim = QPropertyAnimation(tile, b"tile_opacity")
            anim.setDuration(duration)
            anim.setEasingCurve(motion.EASE_STANDARD)
            anim.setStartValue(0.0)
            anim.setEndValue(1.0)
            # IMPORTANT: snap to exactly 1.0 in finished handler. Easing
            # curves can leave a tile at 0.9999 due to float drift, which
            # would permanently bypass AccountTile's painter fast path
            # (the fast path requires _paint_scale == 1.0 AND
            # _tile_opacity == 1.0).
            anim.finished.connect(lambda t=tile: setattr(t, "tile_opacity", 1.0))
            self._reveal_anims.append(anim)
            QTimer.singleShot(i * stagger, anim.start)

    def _wire_tile(self, tile: AccountTile, index: int) -> None:
        tile.launch_clicked.connect(lambda i=index: self.tile_launch.emit(i))
        tile.quit_clicked.connect(lambda i=index: self.tile_quit.emit(i))
        tile.cancel_clicked.connect(lambda i=index: self.tile_cancel.emit(i))
        tile.retry_clicked.connect(lambda i=index: self.tile_retry.emit(i))
        tile.enter_2fa_clicked.connect(lambda i=index: self.tile_enter_2fa.emit(i))
        tile.edit_clicked.connect(lambda i=index: self.tile_edit.emit(i))
        tile.delete_clicked.connect(lambda i=index: self.tile_delete.emit(i))
        tile.expand_error_clicked.connect(lambda i=index: self.tile_expand_error.emit(i))
