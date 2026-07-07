"""OptionTileGrid - the v2 kit's selectable tile grid (2 columns).

Selected tile: alpha(accent.c, tile_sel_alpha) fill, 2px bright border,
16px check circle top-right. Unselected: inset-row colors. API contract is
SettingsRadioList's: value(), silent set_value(), value_changed once per
user change.
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QFrame, QGridLayout, QLabel, QVBoxLayout, QWidget

from utils.color_math import with_alpha
from utils.theme_manager import V2_ACCENTS, get_v2_tokens
from utils.widgets.portrait_badge import _qcolor_from_rgba


class _OptionTile(QFrame):
    def __init__(self, value: str, label: str, desc: str, owner, parent=None):
        super().__init__(parent)
        self.value = value
        self._owner = owner
        self.selected = False
        self.setObjectName("option_tile")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setCursor(Qt.PointingHandCursor)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 24, 10)   # right pad clears the check
        lay.setSpacing(2)
        self.title = QLabel(label)
        self.title.setStyleSheet("background: transparent; border: none;")
        self.desc = QLabel(desc)
        self.desc.setWordWrap(True)
        self.desc.setStyleSheet("background: transparent; border: none;")
        lay.addWidget(self.title)
        lay.addWidget(self.desc)

    def _activate(self) -> None:
        self._owner._on_tile_clicked(self.value)

    def mouseReleaseEvent(self, e):
        if (e.button() == Qt.LeftButton
                and self.rect().contains(e.position().toPoint())):
            self._activate()
            e.accept()
            return
        super().mouseReleaseEvent(e)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            e.accept()
            return
        super().mousePressEvent(e)

    def paintEvent(self, e):
        super().paintEvent(e)                 # QSS bg/border first
        if not self.selected:
            return
        a = self._owner._accent
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        r = QRectF(self.width() - 9 - 16, 9, 16, 16)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(a["b"]))
        p.drawEllipse(r)
        pen = QPen(QColor("#ffffff"), 2.2)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        cx, cy = r.center().x(), r.center().y()
        p.drawLine(int(cx - 3.5), int(cy), int(cx - 1), int(cy + 3))
        p.drawLine(int(cx - 1), int(cy + 3), int(cx + 4), int(cy - 3))
        p.end()


class OptionTileGrid(QWidget):
    value_changed = Signal(str)

    def __init__(self, items, columns: int = 2, parent=None):
        super().__init__(parent)
        assert items, "OptionTileGrid requires at least one item"
        values = [v for v, _, _ in items]
        assert len(set(values)) == len(values), "values must be unique"
        self._accent = V2_ACCENTS["blue"]
        self._t = get_v2_tokens(True)
        self._is_dark = True
        self._tiles: list[_OptionTile] = []
        lay = QGridLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        for i, (value, label, desc) in enumerate(items):
            tile = _OptionTile(value, label, desc, self)
            self._tiles.append(tile)
            lay.addWidget(tile, i // columns, i % columns)
        for col in range(columns):
            lay.setColumnStretch(col, 1)
        self._tiles[0].selected = True
        self._restyle()

    def value(self) -> str:
        for t in self._tiles:
            if t.selected:
                return t.value
        return self._tiles[0].value

    def set_value(self, v) -> None:
        if v not in [t.value for t in self._tiles]:
            return
        for t in self._tiles:
            t.selected = t.value == v
        self._restyle()

    def apply_theme(self, is_dark: bool, accent_key: str = "blue") -> None:
        self._is_dark = is_dark
        self._t = get_v2_tokens(is_dark)
        self._accent = V2_ACCENTS.get(accent_key, V2_ACCENTS["blue"])
        self._restyle()

    def _on_tile_clicked(self, value: str) -> None:
        if value == self.value():
            return
        self.set_value(value)
        self.value_changed.emit(value)

    def _restyle(self) -> None:
        t = self._t
        sel_bg = with_alpha(self._accent["c"], t["tile_sel_alpha"])
        sel_bg_qss = (f"rgba({sel_bg.red()}, {sel_bg.green()}, "
                      f"{sel_bg.blue()}, {sel_bg.alpha()})")
        for tile in self._tiles:
            if tile.selected:
                tile.setStyleSheet(
                    "QFrame#option_tile {"
                    f" background: {sel_bg_qss};"
                    f" border: 2px solid {self._accent['b']};"
                    " border-radius: 13px; }")
                title_c, desc_c = t["tile_sel_text"], t["tile_sel_desc"]
            else:
                tile.setStyleSheet(
                    "QFrame#option_tile {"
                    f" background: {t['tile_idle_bg']};"
                    f" border: 2px solid {t['tile_idle_border']};"
                    " border-radius: 13px; }")
                title_c, desc_c = t["tile_idle_text"], t["tile_idle_desc"]
            tile.title.setStyleSheet(
                f"font-size: 12.5px; font-weight: 700; color: {title_c}; "
                "background: transparent; border: none;")
            tile.desc.setStyleSheet(
                f"font-size: 10.5px; color: {desc_c}; "
                "background: transparent; border: none;")
            tile.update()
