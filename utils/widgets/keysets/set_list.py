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

from utils.shared_widgets import ElidingLabel
from .game_meta import set_accent
from .palette import (
    add_set_qss, rail_chip_qss, rail_header_ink, rail_item, rail_item_ink,
    rail_panel_qss,
)

MAX_SETS = 8
_PREVIEW_KEYS = ("forward", "left", "reverse", "right")
_ITEM_RADIUS = 14


def _preview_label(value: str) -> str:
    return value[: -len(" Arrow")] if value.endswith(" Arrow") else value


class _Keycap(QLabel):
    """A tiny mono preview keycap in a SetListItem's key row. Flat fill/border
    - no gradient needed, so plain QSS suffices (no custom paint). Styling is
    applied by the owning SetListItem (theme + selection state), not here."""

    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setAlignment(Qt.AlignCenter)
        self.setFixedHeight(19)
        self.setMinimumWidth(19)


class SetListItem(QWidget):
    """One set card: numbered badge + name + a mono keycap preview row.
    Paints its own gradient body / border (dynamic per-set accent); the
    badge, name label, and keycaps are transparent-background children."""

    def __init__(self, panel: "SetListPanel", index: int, name: str,
                 keys: dict, selected: bool, parent=None, *, is_dark: bool = True):
        super().__init__(parent)
        self._panel = panel
        self._index = index
        self._c, self._b = set_accent(index)
        self._selected = selected
        self._is_dark = is_dark

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
        self._name_lbl = ElidingLabel(name)
        top.addWidget(self._name_lbl, 1)
        outer.addLayout(top)

        preview = QHBoxLayout()
        preview.setContentsMargins(0, 0, 0, 0)
        preview.setSpacing(4)
        self._chips: list[_Keycap] = []
        for key in _PREVIEW_KEYS:
            value = keys.get(key)
            if not value:
                continue
            chip = _Keycap(_preview_label(value))
            preview.addWidget(chip, 0)
            self._chips.append(chip)
        preview.addStretch(1)
        outer.addLayout(preview)

        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self._restyle_children()

    def _restyle_children(self) -> None:
        ink = rail_item_ink(self._selected, self._is_dark)
        self._name_lbl.setStyleSheet(
            "background: transparent; border: none; color: %s; "
            "font-size: 13px; font-weight: 700;" % ink)
        chip_qss = rail_chip_qss(self._selected, self._is_dark)
        for chip in self._chips:
            chip.setStyleSheet(chip_qss)

    def apply_theme(self, is_dark: bool) -> None:
        if is_dark != self._is_dark:
            self._is_dark = is_dark
            self._restyle_children()
            self.update()

    def set_selected(self, selected: bool) -> None:
        selected = bool(selected)
        if selected == self._selected:
            return
        self._selected = selected
        self._restyle_children()
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

        top, bot, border_col = rail_item(self._c, self._b, self._selected, self._is_dark)
        if self._selected:
            glow = QColor(self._b)
            glow.setAlphaF(0.35)
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(glow, 7))
            p.drawPath(path)

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
    WIDTH = 266
    MAX_SETS = MAX_SETS

    def __init__(self, is_dark: bool = True, parent=None):
        super().__init__(parent)
        self._is_dark = is_dark
        self._items: list[SetListItem] = []

        self.setFixedWidth(self.WIDTH)
        self.setStyleSheet(rail_panel_qss(is_dark))

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
            "background: transparent; border: none; color: %s; "
            "font-size: 10px; font-weight: 700; letter-spacing: 0.9px;"
            % rail_header_ink(is_dark)
        )
        header.addWidget(self._header_label, 1)
        outer.addLayout(header)

        self._list_layout = QVBoxLayout()
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(5)
        outer.addLayout(self._list_layout)

        self._add_btn = QPushButton("+  Add Set")
        self._add_btn.setCursor(Qt.PointingHandCursor)
        # 41 = 9px gap zone + 32px capsule; the QSS margin used to carve the
        # gap out of a 32px box and squish the capsule.
        self._add_btn.setFixedHeight(41)
        self._add_btn.setStyleSheet(self._add_set_stylesheet(is_dark))
        self._add_btn.clicked.connect(self.add_requested.emit)
        outer.addWidget(self._add_btn)

    @staticmethod
    def _add_set_stylesheet(is_dark: bool) -> str:
        # palette QSS stays margin-free; the gap-carving margin is applied
        # here, at the call site, now that the fixed height has room for it.
        return add_set_qss(is_dark).replace(
            "QPushButton {", "QPushButton { margin-top: 9px;", 1)

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
            item = SetListItem(self, i, name, keys, i == selected_index, self,
                                is_dark=self._is_dark)
            self._list_layout.addWidget(item)
            self._items.append(item)

        self._add_btn.setVisible(len(sets) < self.MAX_SETS)

    def apply_theme(self, is_dark: bool) -> None:
        self._is_dark = is_dark
        self.setStyleSheet(rail_panel_qss(is_dark))
        self._header_label.setStyleSheet(
            "background: transparent; border: none; color: %s; "
            "font-size: 10px; font-weight: 700; letter-spacing: 0.9px;"
            % rail_header_ink(is_dark)
        )
        self._add_btn.setStyleSheet(self._add_set_stylesheet(is_dark))
        for item in self._items:
            item.apply_theme(is_dark)
        self.update()
