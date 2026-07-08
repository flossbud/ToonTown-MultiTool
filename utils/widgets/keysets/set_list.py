"""SetListPanel — the left master column of the Split keyset editor: a
neutral panel listing a game's movement sets as `SetListItem` cards, plus a
dashed "+ Add Set" button.

This is a VIEW: it renders sets and emits selection/add signals; it never
mutates keymaps. Kit law: paint gradients/borders in paintEvent (mirrors
CardSurface's double-width-pen-clipped-to-path border technique); everything
that's a flat fill/border (badges, keycaps, chrome) uses QSS on a styled
widget instead. NEVER attach a QGraphicsEffect to a widget that also
custom-paints (paint the glow, don't effect it).
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

from utils.color_math import darken_rgb, with_alpha
from utils.shared_widgets import ElidingLabel
from .game_meta import set_accent

MAX_SETS = 8
_PREVIEW_KEYS = ("forward", "left", "reverse", "right")
_ITEM_RADIUS = 14


def _preview_label(value: str) -> str:
    return value[: -len(" Arrow")] if value.endswith(" Arrow") else value


class _Keycap(QLabel):
    """A tiny mono preview keycap in a SetListItem's key row. Flat fill/border
    - no gradient needed, so plain QSS suffices (no custom paint)."""

    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setAlignment(Qt.AlignCenter)
        self.setFixedHeight(19)
        self.setMinimumWidth(19)
        self.setStyleSheet(
            "background-color: rgba(0,0,0,0.28); "
            "border: 1px solid rgba(255,255,255,0.14); border-radius: 5px; "
            "color: rgba(255,255,255,0.9); font-weight: 700; font-size: 9px; "
            "font-family: 'JetBrains Mono', 'Cascadia Mono', monospace; "
            "padding: 0 4px;"
        )


class SetListItem(QWidget):
    """One set card: numbered badge + name + a mono keycap preview row.
    Paints its own gradient body / border (dynamic per-set accent); the
    badge, name label, and keycaps are transparent-background children."""

    def __init__(self, panel: "SetListPanel", index: int, name: str,
                 keys: dict, selected: bool, parent=None):
        super().__init__(parent)
        self._panel = panel
        self._index = index
        self._c, self._b = set_accent(index)
        self._selected = selected

        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_StyledBackground, False)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 10, 12, 10)
        outer.setSpacing(8)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(8)
        badge = QLabel(str(index + 1))
        badge.setFixedSize(20, 20)
        badge.setAlignment(Qt.AlignCenter)
        badge.setStyleSheet(
            f"background-color: {self._c}; border: 1px solid {self._b}; "
            "border-radius: 6px; color: #ffffff; font-weight: 800; font-size: 11px;"
        )
        top.addWidget(badge, 0)
        name_lbl = ElidingLabel(name)
        name_lbl.setStyleSheet(
            "background: transparent; border: none; color: #ffffff; "
            "font-size: 13px; font-weight: 700;"
        )
        top.addWidget(name_lbl, 1)
        outer.addLayout(top)

        preview = QHBoxLayout()
        preview.setContentsMargins(0, 0, 0, 0)
        preview.setSpacing(4)
        for key in _PREVIEW_KEYS:
            value = keys.get(key)
            if not value:
                continue
            preview.addWidget(_Keycap(_preview_label(value)), 0)
        preview.addStretch(1)
        outer.addLayout(preview)

        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

    def set_selected(self, selected: bool) -> None:
        selected = bool(selected)
        if selected == self._selected:
            return
        self._selected = selected
        self.update()

    # ── input ────────────────────────────────────────────────────────────
    def _emit_click(self) -> None:
        self._panel.set_selected.emit(self._index)

    def mouseReleaseEvent(self, e) -> None:
        if e.button() == Qt.LeftButton and self.rect().contains(e.position().toPoint()):
            self._emit_click()
        e.accept()

    # ── paint ────────────────────────────────────────────────────────────
    def paintEvent(self, _e) -> None:
        if self.width() <= 0 or self.height() <= 0:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(r, _ITEM_RADIUS, _ITEM_RADIUS)

        c, b = QColor(self._c), QColor(self._b)
        if self._selected:
            top, bot, border_col = darken_rgb(c, 0.95), darken_rgb(c, 0.72), QColor(b)
            glow = QColor(b)
            glow.setAlphaF(0.35)
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(glow, 7))
            p.drawPath(path)
        else:
            top, bot, border_col = darken_rgb(c, 0.30), darken_rgb(c, 0.15), with_alpha(b, 0.55)

        grad = QLinearGradient(r.topLeft().x(), r.topLeft().y(),
                               r.x() + r.width() * 0.38, r.y() + r.height())
        grad.setColorAt(0.0, top)
        grad.setColorAt(1.0, bot)
        p.fillPath(path, grad)

        p.save()
        p.setClipPath(path)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(border_col, 4))
        p.drawPath(path)
        p.restore()
        p.end()


class SetListPanel(QFrame):
    """Neutral master panel: header + a stack of `SetListItem`s + a dashed
    "+ Add Set" button (hidden at MAX_SETS)."""

    set_selected = Signal(int)
    add_requested = Signal()
    WIDTH = 214
    MAX_SETS = MAX_SETS

    def __init__(self, is_dark: bool = True, parent=None):
        super().__init__(parent)
        self._is_dark = is_dark
        self._items: list[SetListItem] = []

        self.setFixedWidth(self.WIDTH)
        self.setStyleSheet(
            "SetListPanel { background-color: rgba(0,0,0,0.24); "
            "border: 1px solid rgba(0,0,0,0.30); border-radius: 20px; }"
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setSpacing(0)

        header = QHBoxLayout()
        header.setContentsMargins(2, 2, 2, 10)
        header.setSpacing(7)
        self._dot = QLabel()
        self._dot.setFixedSize(7, 7)
        header.addWidget(self._dot, 0)
        self._header_label = QLabel()
        self._header_label.setStyleSheet(
            "background: transparent; border: none; color: rgba(255,255,255,0.5); "
            "font-size: 10px; font-weight: 700; letter-spacing: 0.9px;"
        )
        header.addWidget(self._header_label, 1)
        outer.addLayout(header)

        self._list_layout = QVBoxLayout()
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(5)
        outer.addLayout(self._list_layout)

        self._add_btn = QPushButton("+  Add Set")
        self._add_btn.setCursor(Qt.PointingHandCursor)
        self._add_btn.setFixedHeight(32)
        self._add_btn.setStyleSheet(
            "QPushButton { background: transparent; color: #aaaaaa; "
            "border: 1.5px dashed rgba(255,255,255,0.22); border-radius: 12px; "
            "font-size: 12.5px; font-weight: 600; margin-top: 9px; }"
            "QPushButton:hover { background: rgba(255,255,255,0.07); }"
        )
        self._add_btn.clicked.connect(self.add_requested.emit)
        outer.addWidget(self._add_btn)

    # ── public API ───────────────────────────────────────────────────────
    def set_data(self, *, game_short: str, game_accent: str, sets: list[dict],
                 set_names: list[str], selected_index: int) -> None:
        self._dot.setStyleSheet(f"background-color: {game_accent}; border-radius: 4px;")
        self._header_label.setText(f"{game_short} · MOVEMENT SETS".upper())

        while self._list_layout.count():
            item = self._list_layout.takeAt(0).widget()
            if item is not None:
                item.setParent(None)
                item.deleteLater()
        self._items = []

        for i, keys in enumerate(sets):
            name = set_names[i] if i < len(set_names) else f"Set {i + 1}"
            item = SetListItem(self, i, name, keys, i == selected_index, self)
            self._list_layout.addWidget(item)
            self._items.append(item)

        self._add_btn.setVisible(len(sets) < self.MAX_SETS)

    def apply_theme(self, is_dark: bool) -> None:
        self._is_dark = is_dark
        self.update()
