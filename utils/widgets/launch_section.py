"""Section in the Launch tab: header strip (game icon + title + launcher
button) + 2-column tile grid + empty-state fallback. Owns the per-tile
widgets and re-emits their signals with the section_index attached."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget,
)

from utils.widgets.account_tile import AccountTile, _QuietChipButton
from utils.widgets.empty_state import EmptyState


_GAME_NAMES = {"ttr": "Toontown Rewritten", "cc": "Corporate Clash"}
_GAME_SHORT = {"ttr": "TTR", "cc": "CC"}


class _AddTile(_QuietChipButton):
    """Dashed-outline "+ Add Account" tile, matches grid cell size.
    Uses _QuietChipButton (no hover upscale, 0.96 press scale)."""
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

        self.launcher_btn = _QuietChipButton()
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

    def tile_at(self, section_index: int) -> AccountTile | None:
        if 0 <= section_index < len(self.tiles):
            return self.tiles[section_index]
        return None

    def _wire_tile(self, tile: AccountTile, index: int) -> None:
        tile.launch_clicked.connect(lambda i=index: self.tile_launch.emit(i))
        tile.quit_clicked.connect(lambda i=index: self.tile_quit.emit(i))
        tile.cancel_clicked.connect(lambda i=index: self.tile_cancel.emit(i))
        tile.retry_clicked.connect(lambda i=index: self.tile_retry.emit(i))
        tile.enter_2fa_clicked.connect(lambda i=index: self.tile_enter_2fa.emit(i))
        tile.edit_clicked.connect(lambda i=index: self.tile_edit.emit(i))
        tile.delete_clicked.connect(lambda i=index: self.tile_delete.emit(i))
        tile.expand_error_clicked.connect(lambda i=index: self.tile_expand_error.emit(i))
