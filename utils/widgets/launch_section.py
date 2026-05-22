"""Section in the Launch tab: header strip (game icon + title + launcher
button) + 2-column tile grid + empty-state fallback. Owns the per-tile
widgets and re-emits their signals with the section_index attached."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget,
)

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
        self.setText(f"+ Add {_GAME_SHORT[game]} Account")
        self.setMinimumHeight(130)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet(
            "QToolButton { background: transparent; border: 2px dashed"
            " rgba(255,255,255,0.12); border-radius: 10px; color: #8a9bb8;"
            " font-size: 13px; }"
            "QToolButton:hover { border-color: rgba(255,255,255,0.25);"
            " color: #cfd6e6; background: rgba(255,255,255,0.02); }"
        )


class LaunchSection(QWidget):
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

    def __init__(self, game: str, icon_path: str, max_accounts: int = 8, parent=None):
        super().__init__(parent)
        # Compact-mode horizontal cap. Mirrors tabs/multitoon/_compact_layout.py:38-44.
        # In full mode (set via set_layout_mode), the cap is lifted so the
        # two sections can sit side-by-side and each fill ~half the window.
        self._max_width = 720
        self.setMaximumWidth(self._max_width)
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

        # Tinted accent band wrapping the header strip. The gradient fades
        # from a 10%-opacity game-accent tint at the top to transparent at
        # the bottom; the hairline below the band acts as the section-
        # boundary divider so the header reads as a labeled region rather
        # than floating text.
        accent_rgba = (
            "rgba(74,143,231,0.10)" if game == "ttr"
            else "rgba(242,109,33,0.10)"
        )
        header = QFrame()
        header.setObjectName("section_header")
        header.setStyleSheet(
            "QFrame#section_header {"
            " background: qlineargradient(x1:0, y1:0, x2:0, y2:1,"
            f" stop:0 {accent_rgba}, stop:1 transparent);"
            " border-bottom: 1px solid rgba(255,255,255,0.06);"
            "}"
        )
        head_lay = QHBoxLayout(header)
        head_lay.setContentsMargins(18, 14, 18, 14)
        head_lay.setSpacing(12)

        icon_box = QLabel()
        icon_box.setFixedSize(40, 40)
        icon_box.setStyleSheet("border-radius: 8px;")
        pm = QPixmap(icon_path)
        if not pm.isNull():
            icon_box.setPixmap(pm.scaled(40, 40, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        head_lay.addWidget(icon_box)

        title_col = QVBoxLayout()
        title_col.setSpacing(0)
        self.title_label = QLabel(_GAME_NAMES[game])
        self.title_label.setStyleSheet("color: #fff; font-weight: 700; font-size: 15px;")
        title_col.addWidget(self.title_label)
        self.subline = QLabel("No accounts yet")
        self.subline.setStyleSheet("color: #8a9bb8; font-size: 12px;")
        title_col.addWidget(self.subline)
        head_lay.addLayout(title_col)
        head_lay.addStretch()

        self.launcher_btn = QuietChipButton()
        self.launcher_btn.setText(f"↗ Launch {_GAME_SHORT[game]} Launcher")
        self.launcher_btn.setCursor(Qt.PointingHandCursor)
        self.launcher_btn.setStyleSheet(
            "QToolButton { background: transparent; border: 1px solid rgba(255,255,255,0.18);"
            " color: #cfd6e6; border-radius: 8px; padding: 8px 14px; font-size: 12px;"
            " font-weight: 600; }"
            "QToolButton:hover { background: rgba(255,255,255,0.06);"
            " border-color: rgba(255,255,255,0.3); }"
        )
        self.launcher_btn.clicked.connect(self.launcher_clicked.emit)
        head_lay.addWidget(self.launcher_btn)

        outer.addWidget(header)

        self.grid_container = QWidget()
        self.grid = QGridLayout(self.grid_container)
        self.grid.setContentsMargins(14, 14, 14, 14)
        self.grid.setSpacing(10)
        outer.addWidget(self.grid_container)

        self.empty_state = EmptyState(game=game)
        self.empty_state.add_clicked.connect(self.add_account_clicked.emit)
        outer.addWidget(self.empty_state)

        self.set_accounts([])

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
        # Header title font size scales too (15 base -> up to 21). NOTE:
        # this replaces the full stylesheet; if you add other QSS rules to
        # title_label, include them here or they'll be silently dropped on
        # the next resize.
        self.title_label.setStyleSheet(
            f"color: #fff; font-weight: 700;"
            f" font-size: {int(15 * self._content_scale)}px;"
        )

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
        """
        if mode not in _LAYOUT_MAX_WIDTH:
            return
        self._max_width = _LAYOUT_MAX_WIDTH[mode]
        self.setMaximumWidth(self._max_width)
        self._layout_mode = mode
        self._recompute_content_scale()

    def _wire_tile(self, tile: AccountTile, index: int) -> None:
        tile.launch_clicked.connect(lambda i=index: self.tile_launch.emit(i))
        tile.quit_clicked.connect(lambda i=index: self.tile_quit.emit(i))
        tile.cancel_clicked.connect(lambda i=index: self.tile_cancel.emit(i))
        tile.retry_clicked.connect(lambda i=index: self.tile_retry.emit(i))
        tile.enter_2fa_clicked.connect(lambda i=index: self.tile_enter_2fa.emit(i))
        tile.edit_clicked.connect(lambda i=index: self.tile_edit.emit(i))
        tile.delete_clicked.connect(lambda i=index: self.tile_delete.emit(i))
        tile.expand_error_clicked.connect(lambda i=index: self.tile_expand_error.emit(i))
