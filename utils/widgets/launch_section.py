"""Section in the Launch tab: an identity-tinted CardSurface (game logo +
title + running-count sub + a launcher pill + a collapse chevron) over a
paged, centered grid of fixed 336x96 account tiles, an empty state, and a
footer pager. Owns the per-tile widgets and re-emits their signals with the
account_id attached."""
from __future__ import annotations

from PySide6.QtCore import QPropertyAnimation, QTimer, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QGridLayout, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget,
)

from utils.widgets.page_pager import PagePager

import utils.motion as motion
from utils.theme_manager import get_theme_colors
from utils.widgets.account_tile import AccountTile
from utils.widgets.card_surface import CardSurface
from utils.widgets.chip_button import QuietChipButton
from utils.widgets.empty_state import EmptyState


# Qt constant for unlimited size (QWidget default maximumHeight/Width).
QWIDGETSIZE_MAX = 16777215

_GAME_NAMES = {"ttr": "Toontown Rewritten", "cc": "Corporate Clash"}
_GAME_SHORT = {"ttr": "TTR", "cc": "CC"}
# Compact cap is 740, not 720: CardSurface reserves EDGE_PAD (10px/side) for its
# painted drop shadow, so a 740 widget yields a 720-wide VISIBLE card - matching
# the handoff's 720 content column that holds two fixed 336px tiles side by side.
_LAYOUT_MAX_WIDTH = {"compact": 740, "full": 860}

# Running-count accent for the sub line (green): brighter in dark mode.
_RUNNING_GREEN = {True: "#7de392", False: "#15803d"}

PAGE_SIZE = 4
MAX_PAGES = 4


def page_count(n: int) -> int:
    """Pages for n accounts, reserving one landing page for the next account
    until the 16 ceiling. min(4, ceil((n+1)/4))."""
    return min(MAX_PAGES, max(1, (n + 4) // PAGE_SIZE))


class LaunchSection(QWidget):
    REVEAL_STAGGER_MS = 30
    REVEAL_DURATION_MS = 150
    COLLAPSE_DURATION_MS = 180

    launcher_clicked       = Signal()
    add_account_clicked    = Signal()
    tile_launch            = Signal(str)
    tile_quit              = Signal(str)
    tile_cancel            = Signal(str)
    tile_retry             = Signal(str)
    tile_enter_2fa         = Signal(str)
    tile_edit              = Signal(str)
    tile_delete            = Signal(str)
    tile_expand_error      = Signal(str)
    tile_portrait_clicked  = Signal(str)
    # Fires when the section's natural sizeHint changes (account list change).
    # LaunchTab listens so it can re-equalize sibling section heights in
    # compact mode.
    content_size_changed   = Signal()
    # Emitted when the user toggles via a header click. Programmatic
    # set_collapsed(...) calls do NOT emit. Keeps the persistence write
    # loop in LaunchTab one-directional.
    collapsed_changed      = Signal(bool)
    page_changed           = Signal(int)
    reorder_clicked        = Signal()

    def __init__(self, game: str, icon_path: str, parent=None):
        super().__init__(parent)
        # Compact-mode horizontal cap. Mirrors tabs/multitoon/_compact_layout.py:38-44.
        # In full mode (set via set_layout_mode), the cap is lifted so the
        # two sections can sit side-by-side and each fill ~half the window.
        self._max_width = _LAYOUT_MAX_WIDTH["compact"]
        self.setMaximumWidth(self._max_width)
        # Floor min-height keeps a card from collapsing visually when
        # empty; the actual matched-height enforcement is done at the
        # LaunchTab level via _sync_compact_section_heights.
        self.setMinimumHeight(380)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self._layout_mode = "compact"
        assert game in ("ttr", "cc")
        self._game = game
        self._is_dark = True
        self.tiles: list[AccountTile] = []
        self.add_tile = None
        self.is_collapsed: bool = False
        self._collapse_anim: QPropertyAnimation | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Per-game card: the v2 kit's identity-tinted CardSurface. The game
        # accent drives its gradient body + border; the badge carries the
        # game logo. Collapse desaturates the whole surface.
        self.card = CardSurface(accent_key=game, title=_GAME_NAMES[game],
                                logo_path=icon_path)
        # Vertical Expanding so the card fills the section's allocated height
        # instead of shrinking to content (keeps a populated and an empty
        # sibling card visually the same height).
        self.card.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        self.card.header_clicked.connect(self._on_header_clicked)
        outer.addWidget(self.card)
        # Expose the card's title label under the legacy attribute name so
        # existing callers/tests keep reading sec.title_label.
        self.title_label = self.card.title_label

        # Launcher pill + collapse chevron ride the card header's button row.
        # A QToolButton absorbs its own click so the launcher never toggles
        # collapse; the QLabel chevron propagates its press up to the card,
        # so clicking it (or anywhere in the header band) toggles collapse.
        self.launcher_btn = QuietChipButton()
        self.launcher_btn.setText(f"↗ Launch {_GAME_SHORT[game]} Launcher")
        self.launcher_btn.setCursor(Qt.PointingHandCursor)
        self.launcher_btn.clicked.connect(self.launcher_clicked.emit)
        self.card.add_header_button(self.launcher_btn)

        # Chevron state indicator. Text is swapped between ▾ (expanded)
        # and ▸ (collapsed); no rotation animation - the height tween
        # carries the motion. Styled in apply_theme.
        self._chev = QLabel("▾")
        self._chev.setObjectName("section_chev")
        self._chev.setAlignment(Qt.AlignCenter)
        self._chev.setFixedWidth(22)
        self.card.add_header_button(self._chev)

        # _body_wrap holds everything that collapses (grid + empty state +
        # reserved-page hint + pager). Lives inside the card body. Transparent
        # so the card surface paints through.
        self._body_wrap = QWidget()
        self._body_wrap.setAttribute(Qt.WA_TranslucentBackground, True)
        body_lay = QVBoxLayout(self._body_wrap)
        body_lay.setContentsMargins(0, 0, 0, 0)
        body_lay.setSpacing(0)

        # grid_container centers a block of fixed 336x96 tiles. The tiles are
        # a fixed size, so the grid columns must NOT stretch (that would leave
        # the tiles marooned in over-wide cells); instead the whole 2-column
        # block is centered horizontally via outer stretches. A lone tile sits
        # at 336px (one quadrant), two tiles sit adjacent and centered.
        self.grid_container = QWidget()
        self.grid_container.setAttribute(Qt.WA_TranslucentBackground, True)
        gc_lay = QHBoxLayout(self.grid_container)
        # Zero horizontal margins: CardSurface already insets its body by 16px, and
        # two fixed 336px tiles + the 10px grid gap need the full inner width to fit
        # without clipping. Vertical padding kept.
        gc_lay.setContentsMargins(0, 14, 0, 14)
        gc_lay.setSpacing(0)
        gc_lay.addStretch(1)
        grid_host = QWidget()
        grid_host.setAttribute(Qt.WA_TranslucentBackground, True)
        self.grid = QGridLayout(grid_host)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(10)
        gc_lay.addWidget(grid_host)
        gc_lay.addStretch(1)
        # Reserve two tile rows + gap + footer headroom so a short page (one
        # tile) does not collapse the card height.
        self.grid_container.setMinimumHeight(2 * 130 + 10 + 28)
        body_lay.addWidget(self.grid_container)

        self.empty_state = EmptyState(game=game)
        self.empty_state.setAttribute(Qt.WA_TranslucentBackground, True)
        self.empty_state.add_clicked.connect(self.add_account_clicked.emit)
        body_lay.addWidget(self.empty_state)

        # Soft hint shown on a reserved (empty) landing page when the game
        # has accounts on other pages. Occupies the grid area.
        self.empty_page_hint = QLabel("No accounts on this page yet")
        self.empty_page_hint.setObjectName("empty_page_hint")
        self.empty_page_hint.setAlignment(Qt.AlignCenter)
        self.empty_page_hint.setVisible(False)
        # Reserve the SAME area grid_container reserves so flipping to a
        # reserved (empty) page keeps the section height stable.
        self.empty_page_hint.setMinimumHeight(2 * 130 + 10 + 28)
        body_lay.addWidget(self.empty_page_hint)

        # Footer pager.
        self.pager = PagePager(self._game)
        self.pager.page_selected.connect(self.page_changed.emit)
        self.pager.add_clicked.connect(self.add_account_clicked.emit)
        self.pager.reorder_clicked.connect(self.reorder_clicked.emit)
        body_lay.addWidget(self.pager)

        self.card.add_row(self._body_wrap)
        # A bottom stretch in the card body absorbs slack so the header +
        # content stay at the TOP and any extra vertical space (a taller
        # sibling card in full mode) becomes empty card area at the bottom
        # rather than vertically stretching the content.
        self.card._body_layout.addStretch(1)

        # Seed the sub line and expose it under the legacy `subline` attribute.
        self.card.set_sub("No accounts yet")
        self.subline = self.card.sub_label

        # Cache dark default before apply_theme so _current_theme exists even
        # if anything triggers a restyle before apply_theme runs.
        self._current_theme = get_theme_colors(True)
        # Initial styling: dark default. LaunchTab.apply_theme() overrides
        # immediately with the user's actual theme.
        self.apply_theme(self._current_theme)

        self.set_accounts([])

    def apply_theme(self, c: dict) -> None:
        """Rebuild every QSS string against the theme dict `c`.
        Called on construction (dark default) and on every theme switch.
        The card surface flips via its own is_dark path; the chevron, launcher
        pill and page hint restyle from the legacy theme tokens."""
        self._current_theme = c
        is_dark = QColor(c["text_primary"]).lightnessF() > 0.5
        self._is_dark = is_dark
        self.card.apply_theme(is_dark)
        self._chev.setStyleSheet(
            "QLabel#section_chev {"
            " background: transparent;"
            f" color: {c['text_secondary']};"
            " font-size: 14px;"
            " padding: 4px 6px;"
            "}"
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
        if hasattr(self.empty_state, "apply_theme"):
            self.empty_state.apply_theme(c)
        if hasattr(self, "empty_page_hint"):
            self.empty_page_hint.setStyleSheet(
                f"background: transparent; color: {c['text_muted']};"
                " font-size: 13px; font-style: italic;"
            )
        if hasattr(self, "pager"):
            self.pager.apply_theme(c)

    def _set_sub_count(self, count: int, running: int = 0) -> None:
        """Render the card sub line: "N accounts" (or "No accounts yet"),
        with an optional green " · N running" suffix. The running count is
        dormant until LaunchTab wires real running data through set_page."""
        if count <= 0:
            self.card.set_sub("No accounts yet")
        else:
            text = f"{count} account" + ("s" if count != 1 else "")
            if running > 0:
                green = _RUNNING_GREEN[self._is_dark]
                text = (f'{text} · '
                        f'<span style="color:{green}">{running} running</span>')
                self.card.set_sub(text, rich_text=True)
            else:
                self.card.set_sub(text)
        self.subline = self.card.sub_label

    def set_accounts(self, accounts: list[dict]) -> None:
        """Back-compat shim: render the given accounts as page 0 (no pagination).
        New code uses set_page(). Demo mode and a few legacy tests use this."""
        pc = max(1, page_count(len(accounts)))
        slice_ = []
        for i, a in enumerate(accounts[:PAGE_SIZE]):
            slice_.append({**a, "id": a.get("id", f"_legacy{i}"),
                           "state": a.get("state", "idle"),
                           "message": a.get("message", ""),
                           "raw_error": a.get("raw_error", "")})
        self.set_page(slice_, page=0, page_count=pc, base_index=0,
                      activity=[False] * pc, show_empty_state=(len(accounts) == 0),
                      at_ceiling=(len(accounts) >= 16))
        self._set_sub_count(len(accounts))

    def tile_at(self, section_index: int) -> AccountTile | None:
        if 0 <= section_index < len(self.tiles):
            return self.tiles[section_index]
        return None

    def set_layout_mode(self, mode: str) -> None:
        """Apply per-section sizing for the app-wide layout mode.

        Compact: capped at 720px so the section fills-then-centers.
        Full: capped at 860px so two sections sit side-by-side comfortably
        on a 1280-1720 wide window.

        No-op if the mode is unknown or already current - same-mode calls
        avoid a redundant reveal flash.
        """
        if mode not in _LAYOUT_MAX_WIDTH:
            return
        if mode == self._layout_mode:
            return
        self._max_width = _LAYOUT_MAX_WIDTH[mode]
        self.setMaximumWidth(self._max_width)
        self._layout_mode = mode
        self._refresh_vertical_size_policy()
        self._run_reveal_animation()

    def _run_reveal_animation(self) -> None:
        """Stagger-fade each tile from 0.0 to 1.0 opacity. Honors
        motion.is_reduced(): under reduced motion, opacities snap to 1.0.
        Per-tile animation via QPropertyAnimation on tile_opacity - does NOT
        use QGraphicsOpacityEffect (see main.py:819-825 for why)."""
        tiles = list(self.tiles)
        if not tiles:
            return
        if motion.is_reduced():
            for t in tiles:
                t.tile_opacity = 1.0
            return
        # Stop any in-flight reveal animations from a prior set_layout_mode
        # call BEFORE replacing the list - QPropertyAnimation has no C++
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

    def set_collapsed(self, value: bool, animate: bool = True) -> None:
        """Set the section's collapsed state.

        animate=False snaps instantly; used by LaunchTab on startup to
        restore persisted state without a flash. animate=True runs a
        height tween - unless reduce-motion is enabled, in which case
        the animated path also snaps. Either way the card surface is
        desaturated when collapsed.

        No-op when `value` already matches `is_collapsed`. Programmatic
        calls do NOT emit `collapsed_changed`; only user header clicks
        emit (see _on_header_clicked).
        """
        if value == self.is_collapsed:
            return
        self.is_collapsed = value
        self._chev.setText("▸" if value else "▾")
        # Collapsed/idle cards desaturate the whole painted surface.
        self.card.set_desaturated(value)
        self._refresh_vertical_size_policy()

        if not animate or motion.is_reduced():
            self._apply_collapsed_snap(value)
            return

        # Stop any in-flight animation. A mid-animation toggle reverses
        # from the current (partway) maximumHeight so the motion looks
        # continuous instead of jumping.
        if self._collapse_anim is not None:
            self._collapse_anim.stop()
        if value:
            start = self._body_wrap.height()
            end = 0
            self.setMinimumHeight(0)
        else:
            self._body_wrap.setVisible(True)
            self.setMinimumHeight(380)
            start = self._body_wrap.maximumHeight()
            if start == QWIDGETSIZE_MAX:
                start = 0
            end = self._body_wrap.sizeHint().height()

        raw = self.COLLAPSE_DURATION_MS * motion._TEST_DURATION_SCALE
        duration = 0 if raw == 0.0 else max(1, int(raw))

        anim = QPropertyAnimation(self._body_wrap, b"maximumHeight")
        anim.setDuration(duration)
        anim.setEasingCurve(motion.EASE_STANDARD)
        anim.setStartValue(start)
        anim.setEndValue(end)
        anim.finished.connect(
            lambda v=value, a=anim: self._on_collapse_anim_finished(v, a)
        )
        self._collapse_anim = anim
        anim.start()

    def _apply_collapsed_snap(self, value: bool) -> None:
        """Snap path used when animate=False or reduce-motion is on."""
        if value:
            self._body_wrap.setVisible(False)
            self._body_wrap.setMaximumHeight(0)
            self.setMinimumHeight(0)
        else:
            self._body_wrap.setVisible(True)
            self._body_wrap.setMaximumHeight(QWIDGETSIZE_MAX)
            self.setMinimumHeight(380)
        self._refresh_vertical_size_policy()

    def _refresh_vertical_size_policy(self) -> None:
        """In full layout mode, vertical policy depends on collapse state:
        Expanding when expanded (stretch to fill), Preferred when collapsed
        (anchor to top with empty space below). In compact mode, vertical
        policy is always Preferred - sections stack with natural heights."""
        if self._layout_mode == "full" and not self.is_collapsed:
            self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        else:
            self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

    def _on_collapse_anim_finished(
        self, collapsed_target: bool, anim: QPropertyAnimation
    ) -> None:
        """After-animation cleanup: hide _body_wrap when collapsed, reset
        maximumHeight to unlimited when expanded so future content
        (new tiles) isn't capped at the snapshot value.

        The `anim` argument is the specific animation object that fired.
        Compare against `self._collapse_anim` directly - `self.sender()`
        returns None when the slot is reached through a Python lambda,
        so we cannot use it for the stale-signal guard.
        """
        if anim is not self._collapse_anim:
            return
        if collapsed_target:
            self._body_wrap.setVisible(False)
        else:
            self._body_wrap.setMaximumHeight(QWIDGETSIZE_MAX)
        self._collapse_anim = None

    def _on_header_clicked(self) -> None:
        """Slot for the card's `header_clicked` signal. Toggles state
        and emits `collapsed_changed` so LaunchTab can persist."""
        self.set_collapsed(not self.is_collapsed, animate=True)
        self.collapsed_changed.emit(self.is_collapsed)

    def _wire_tile(self, tile: AccountTile, account_id: str) -> None:
        tile.launch_clicked.connect(lambda a=account_id: self.tile_launch.emit(a))
        tile.quit_clicked.connect(lambda a=account_id: self.tile_quit.emit(a))
        tile.cancel_clicked.connect(lambda a=account_id: self.tile_cancel.emit(a))
        tile.retry_clicked.connect(lambda a=account_id: self.tile_retry.emit(a))
        tile.enter_2fa_clicked.connect(lambda a=account_id: self.tile_enter_2fa.emit(a))
        tile.edit_clicked.connect(lambda a=account_id: self.tile_edit.emit(a))
        tile.delete_clicked.connect(lambda a=account_id: self.tile_delete.emit(a))
        tile.expand_error_clicked.connect(lambda a=account_id: self.tile_expand_error.emit(a))
        tile.portrait_clicked.connect(lambda a=account_id: self.tile_portrait_clicked.emit(a))

    def set_page(self, accounts: list[dict], *, page: int, page_count: int,
                 base_index: int, activity: list[bool], show_empty_state: bool,
                 at_ceiling: bool, show_reorder: bool = False) -> None:
        """Render one page. `accounts` is this page's slice; each dict has
        label/username/id/state/message/raw_error plus optional primary_*
        keys. base_index is the absolute index of the first tile (for slot
        numbers). Tile signals carry account_id."""
        # Paged-view contract: render at most one page. Defensive slice so a
        # caller passing more than a page slice can't overflow the 2-row grid.
        accounts = accounts[:PAGE_SIZE]
        # Remember the add-button and reorder-button intent so set_activity() can
        # refresh the dots without consulting isVisible() (which is False before show).
        self._show_add = not at_ceiling
        self._show_reorder = show_reorder
        while self.grid.count():
            item = self.grid.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        self.tiles = []
        self.add_tile = None  # legacy trailing add-tile no longer used

        if show_empty_state and not accounts:
            self.empty_state.setVisible(True)
            self.grid_container.setVisible(False)
            self.empty_page_hint.setVisible(False)
            self.pager.setVisible(False)
            self.card.set_sub("No accounts yet")
            return

        self.empty_state.setVisible(False)
        self.pager.setVisible(True)
        if not accounts:
            self.grid_container.setVisible(False)
            self.empty_page_hint.setVisible(True)
        else:
            self.empty_page_hint.setVisible(False)
            self.grid_container.setVisible(True)
            for local, acct in enumerate(accounts):
                abs_index = base_index + local
                tile = AccountTile(game=self._game, slot_index=abs_index)
                tile.set_account(acct.get("label", ""), acct.get("username", ""), abs_index)
                tile.set_state(acct.get("state", "idle"), acct.get("message", ""),
                               acct.get("raw_error", ""))
                # Primary-toon identity. Absent keys (today's callers) leave
                # is_set False, so the tile shows the dashed numbered slot +
                # "Set a primary toon" until the LaunchTab wiring task injects
                # real data.
                tile.set_primary_toon(
                    name=acct.get("primary_name"),
                    username=acct.get("username", ""),
                    species=acct.get("primary_species"),
                    accent=acct.get("primary_accent"),
                    laff=acct.get("primary_laff"),
                    max_laff=acct.get("primary_max_laff"),
                    slot_number=abs_index + 1,
                    is_set=bool(acct.get("primary_is_set")),
                )
                row, col = divmod(local, 2)
                self.grid.addWidget(tile, row, col)
                self.tiles.append(tile)
                self._wire_tile(tile, acct["id"])

        self.pager.set_state(page=page, page_count=page_count, activity=activity,
                             show_add=not at_ceiling, show_reorder=show_reorder)
        self.apply_theme(self._current_theme)

    def set_activity(self, activity: list[bool]) -> None:
        """Update only the pager dots' activity rings (no full re-render)."""
        self.pager.set_state(page=self.pager.page, page_count=self.pager.page_count,
                             activity=activity, show_add=getattr(self, "_show_add", True),
                             show_reorder=getattr(self, "_show_reorder", False))
