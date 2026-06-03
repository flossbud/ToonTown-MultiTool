"""Per-game account reorder modal. A scrollable list of rows over an explicit
order model; drag a row by its handle, or use the per-row up/down arrows. Both
funnel through _move(src, dst). The caller reads ordered_ids() on Accepted."""
from __future__ import annotations

from PySide6.QtCore import Qt, QMimeData, Signal
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QToolButton, QVBoxLayout, QWidget,
)

from utils.theme_manager import get_theme_colors

_ACCENT = {"ttr": "#4A8FE7", "cc": "#F26D21"}
_GAME_NAMES = {"ttr": "Toontown Rewritten", "cc": "Corporate Clash"}
_MIME = "application/x-ttmt-reorder-index"


class _ReorderRow(QFrame):
    """One reorder list row: drag handle (drag source), position badge,
    label-or-username text, and up/down buttons. Acts as both a drag source and
    a drop target; all reordering is delegated to the owning dialog's _move()."""
    def __init__(self, dialog: "AccountReorderDialog", index: int, account: dict,
                 is_first: bool, is_last: bool):
        super().__init__()
        self._dialog = dialog
        self._index = index
        self.setAcceptDrops(True)
        self.setObjectName("reorder_row")

        lay = QHBoxLayout(self)
        lay.setContentsMargins(11, 9, 11, 9)
        lay.setSpacing(11)

        self.handle = QLabel("⠇⠇")  # grip glyph
        self.handle.setObjectName("reorder_handle")
        self.handle.setCursor(Qt.OpenHandCursor)
        self.handle.setToolTip("Drag to reorder")
        self.handle.setAccessibleName("Drag to reorder")
        lay.addWidget(self.handle)

        self.badge = QLabel(str(index + 1))
        self.badge.setObjectName("reorder_badge")
        self.badge.setFixedSize(20, 20)
        self.badge.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.badge)

        label = (account.get("label") or "").strip()
        username = (account.get("username") or "").strip()
        text_col = QVBoxLayout()
        text_col.setSpacing(0)
        self.title = QLabel(label or username or "(unnamed)")
        self.title.setObjectName("reorder_title")
        text_col.addWidget(self.title)
        self.subtitle = QLabel(username if label else "")
        self.subtitle.setObjectName("reorder_subtitle")
        self.subtitle.setVisible(bool(label and username))
        text_col.addWidget(self.subtitle)
        lay.addLayout(text_col, 1)

        self.up_btn = QToolButton()
        self.up_btn.setText("▲")
        self.up_btn.setCursor(Qt.PointingHandCursor)
        self.up_btn.setToolTip("Move up")
        self.up_btn.setAccessibleName("Move up")
        self.up_btn.setEnabled(not is_first)
        self.up_btn.clicked.connect(lambda: self._dialog._move_up(self._index))
        lay.addWidget(self.up_btn)

        self.down_btn = QToolButton()
        self.down_btn.setText("▼")
        self.down_btn.setCursor(Qt.PointingHandCursor)
        self.down_btn.setToolTip("Move down")
        self.down_btn.setAccessibleName("Move down")
        self.down_btn.setEnabled(not is_last)
        self.down_btn.clicked.connect(lambda: self._dialog._move_down(self._index))
        lay.addWidget(self.down_btn)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._press = e.position().toPoint()
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if not (e.buttons() & Qt.LeftButton):
            return
        press = getattr(self, "_press", e.position().toPoint())
        if (e.position().toPoint() - press).manhattanLength() < 8:
            return
        drag = QDrag(self)
        mime = QMimeData()
        mime.setData(_MIME, str(self._index).encode())
        drag.setMimeData(mime)
        drag.exec(Qt.MoveAction)

    def dragEnterEvent(self, e):
        if e.mimeData().hasFormat(_MIME):
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        if e.mimeData().hasFormat(_MIME):
            e.acceptProposedAction()

    def dropEvent(self, e):
        if not e.mimeData().hasFormat(_MIME):
            return
        src = int(bytes(e.mimeData().data(_MIME)).decode())
        # Insert the dragged row at this row's position (the arrows are the
        # precise path; drag uses a simple drop-on-target-row target).
        self._dialog._move(src, self._index)
        e.acceptProposedAction()


class AccountReorderDialog(QDialog):
    order_changed = Signal()

    def __init__(self, game: str, accounts: list[dict], parent=None):
        super().__init__(parent)
        assert game in ("ttr", "cc")
        self._game = game
        self._order: list[dict] = list(accounts)
        self._rows: list[_ReorderRow] = []
        self.setModal(True)
        self.setWindowTitle(f"Reorder {_GAME_NAMES[game]} accounts")
        self.setMinimumWidth(440)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.accent_bar = QFrame()
        self.accent_bar.setFixedHeight(3)
        self.accent_bar.setStyleSheet(f"background: {_ACCENT[game]};")
        outer.addWidget(self.accent_bar)

        head = QVBoxLayout()
        head.setContentsMargins(20, 16, 20, 4)
        self.title_label = QLabel(f"Reorder {_GAME_NAMES[game]} accounts")
        self.title_label.setObjectName("reorder_dialog_title")
        head.addWidget(self.title_label)
        self.help_label = QLabel("Drag a row or use the arrows. Numbers match the launcher order.")
        self.help_label.setObjectName("reorder_dialog_help")
        head.addWidget(self.help_label)
        outer.addLayout(head)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._rows_host = QWidget()
        self._rows_lay = QVBoxLayout(self._rows_host)
        self._rows_lay.setContentsMargins(14, 8, 14, 8)
        self._rows_lay.setSpacing(8)
        self._rows_lay.addStretch(1)
        self._scroll.setWidget(self._rows_host)
        outer.addWidget(self._scroll, 1)

        foot = QHBoxLayout()
        foot.setContentsMargins(20, 12, 20, 16)
        foot.addStretch(1)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.reject)
        foot.addWidget(self.cancel_btn)
        self.save_btn = QPushButton("Save order")
        self.save_btn.setDefault(True)
        self.save_btn.clicked.connect(self.accept)
        foot.addWidget(self.save_btn)
        outer.addLayout(foot)

        self._theme = get_theme_colors(True)
        self._rebuild()
        self.apply_theme(self._theme)

    def ordered_ids(self) -> list[str]:
        return [a["id"] for a in self._order]

    def _move(self, src: int, dst: int) -> None:
        n = len(self._order)
        if not (0 <= src < n) or not (0 <= dst < n) or src == dst:
            return
        item = self._order.pop(src)
        self._order.insert(dst, item)
        self._rebuild()
        self.order_changed.emit()

    def _move_up(self, i: int) -> None:
        self._move(i, i - 1)

    def _move_down(self, i: int) -> None:
        self._move(i, i + 1)

    def _rebuild(self) -> None:
        while self._rows_lay.count():
            it = self._rows_lay.takeAt(0)
            w = it.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        self._rows = []
        n = len(self._order)
        for i, acct in enumerate(self._order):
            row = _ReorderRow(self, i, acct, is_first=(i == 0), is_last=(i == n - 1))
            self._rows_lay.addWidget(row)
            self._rows.append(row)
        self._rows_lay.addStretch(1)
        self.apply_theme(getattr(self, "_theme", get_theme_colors(True)))

    def apply_theme(self, c: dict) -> None:
        self._theme = c
        self.setStyleSheet(f"QDialog {{ background: {c['bg_app']}; }}")
        self.title_label.setStyleSheet(
            f"color: {c['text_primary']}; font-size: 16px; font-weight: 700;")
        self.help_label.setStyleSheet(f"color: {c['text_muted']}; font-size: 12px;")
        for r in self._rows:
            r.setStyleSheet(
                "QFrame#reorder_row {"
                f" background: {c['bg_card_inner']}; border: 1px solid {c['border_card']};"
                " border-radius: 9px; }")
            r.handle.setStyleSheet(f"color: {c['text_muted']}; font-size: 14px; background: transparent;")
            r.badge.setStyleSheet(
                f"background: {_ACCENT[self._game]}; color: {c['text_on_accent']};"
                " border-radius: 10px; font-size: 11px; font-weight: 700;")
            r.title.setStyleSheet(f"color: {c['text_primary']}; font-size: 13px; font-weight: 600; background: transparent;")
            r.subtitle.setStyleSheet(f"color: {c['text_muted']}; font-size: 11px; background: transparent;")
            for b in (r.up_btn, r.down_btn):
                b.setStyleSheet(
                    "QToolButton {"
                    f" border: 1px solid {c['border_muted']}; border-radius: 6px;"
                    f" color: {c['text_secondary']}; font-size: 10px; padding: 4px 6px; }}"
                    f"QToolButton:disabled {{ color: {c['border_card']}; border-color: {c['border_muted']}; }}")
        for btn, primary in ((self.cancel_btn, False), (self.save_btn, True)):
            if primary:
                btn.setStyleSheet(
                    "QPushButton {"
                    f" background: {c['accent_blue_btn']}; color: {c['text_on_accent']};"
                    " border: none; border-radius: 8px; padding: 8px 18px; font-weight: 600; }"
                    f"QPushButton:hover {{ background: {c['accent_blue_btn_hover']}; }}")
            else:
                btn.setStyleSheet(
                    "QPushButton {"
                    f" background: transparent; border: 1px solid {c['border_muted']};"
                    f" color: {c['text_secondary']}; border-radius: 8px; padding: 8px 18px; }}")
