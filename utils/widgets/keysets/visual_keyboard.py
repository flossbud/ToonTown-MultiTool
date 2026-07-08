"""VisualKeyboard — a QWidget grid of styled keycaps that renders a movement
set as a lit-up keyboard.

This is a VIEW of the model: `set_state` classifies each keycap
(movement / aux / unassigned / conflict) plus an independent spotlight ring,
then retints. Clicking a keycap emits `key_clicked(code)`; the widget never
rebinds anything itself.

Kit law: paint everything in `paintEvent` (translucent rgba fills so the
detail card's saturated gradient shows through). NEVER attach a QGraphicsEffect
(it conflicts with a custom paintEvent — a known landmine in this codebase).
"""

from __future__ import annotations

from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, Signal, QRectF
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QBrush

from . import keyboard_data
from utils.color_math import with_alpha


def _mono_font(px: int) -> QFont:
    f = QFont()
    f.setFamilies(["Consolas", "Menlo", "DejaVu Sans Mono", "Liberation Mono", "monospace"])
    f.setStyleHint(QFont.Monospace)
    f.setPixelSize(px)
    f.setBold(True)
    return f


class _KeyCap(QWidget):
    """A single styled keycap. Holds its classification `state` + `spotlight`
    flag and paints its own translucent fill / border / label / ring."""

    def __init__(self, code: str, label: str, width_units: float,
                 unit: int, gap: int, parent: "VisualKeyboard"):
        super().__init__(parent)
        self._kb = parent
        self.code = code
        self.label = label
        self.width_units = width_units
        self._unit = unit
        self._gap = gap
        self.state = "unassigned"
        self.spotlight = False
        self._hover = False

        # Transparent background: let the card gradient show through. We paint
        # every pixel ourselves in paintEvent; no opaque widget background.
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setCursor(Qt.PointingHandCursor)

        w = round(width_units * unit + (width_units - 1) * gap)
        self.setFixedSize(w, unit)

    # ── state ──────────────────────────────────────────────────────────────
    def set_classification(self, state: str, spotlight: bool) -> None:
        if state == self.state and spotlight == self.spotlight:
            return
        self.state = state
        self.spotlight = spotlight
        self.update()

    # ── input ──────────────────────────────────────────────────────────────
    def _emit_click(self) -> None:
        self._kb.key_clicked.emit(self.code)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self.rect().contains(e.position().toPoint()):
            self._emit_click()
        e.accept()

    def enterEvent(self, e):
        if self._hover is not True:
            self._hover = True
            if self.state == "unassigned":
                self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        if self._hover is not False:
            self._hover = False
            if self.state == "unassigned":
                self.update()
        super().leaveEvent(e)

    # ── paint ──────────────────────────────────────────────────────────────
    def _colors(self):
        """(fill, border, text) QColors for the current state."""
        accent_b = self._kb._accent_b or "#3399ff"
        if self.state == "conflict":
            return QColor("#e05252"), QColor("#f28b8b"), QColor("#ffffff")
        if self.state == "movement":
            return (QColor(accent_b), with_alpha("#ffffff", 0.55),
                    QColor("#ffffff"))
        if self.state == "aux":
            return (with_alpha("#ffffff", 0.22), with_alpha("#ffffff", 0.40),
                    QColor("#ffffff"))
        # unassigned
        fill_a = 0.18 if self._hover else 0.28
        return (with_alpha("#000000", fill_a), with_alpha("#ffffff", 0.08),
                with_alpha("#ffffff", 0.40))

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        radius = max(5, round(self._unit * 0.2))
        fill, border, text = self._colors()

        # Inset by half the pen width so the 1px border sits fully inside.
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(border, 1))
        p.setBrush(QBrush(fill))
        p.drawRoundedRect(r, radius, radius)

        # Spotlight: 2px white-ish inner ring on top of the base state.
        if self.spotlight:
            ring = QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5)
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(with_alpha("#ffffff", 0.9), 2))
            p.drawRoundedRect(ring, max(3, radius - 1), max(3, radius - 1))

        # Centered mono label.
        p.setPen(QPen(text))
        p.setFont(_mono_font(max(8, round(self._unit * 0.32))))
        p.drawText(self.rect(), Qt.AlignCenter, self.label)
        p.end()


class VisualKeyboard(QWidget):
    """Grid of `_KeyCap`s. `set_state` classifies + retints; rebuilds when the
    `mac` flag flips (the code set differs)."""

    key_clicked = Signal(str)  # canonical code of the clicked keycap
    UNIT = 24
    GAP = 4

    def __init__(self, is_dark: bool = True, parent=None):
        super().__init__(parent)
        self._is_dark = is_dark
        self._caps: dict[str, _KeyCap] = {}
        self._assign: dict = {}
        self._conflict_vals: set = set()
        self._accent_c = "#3399ff"
        self._accent_b = "#3399ff"
        self._active_code: str | None = None
        self._mac = False

        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self._build(mac=False)

    # ── build ────────────────────────────────────────────────────────────────
    def _clear(self) -> None:
        for cap in self._caps.values():
            cap.setParent(None)
            cap.deleteLater()
        self._caps.clear()
        # Drop any child spacer widgets from a prior build.
        for child in list(self.children()):
            if isinstance(child, QWidget):
                child.setParent(None)
                child.deleteLater()

    def _build(self, mac: bool) -> None:
        """Lay out the main QWERTY block + the bottom-justified nav cluster as
        absolutely-positioned children (manual geometry, no nested layouts)."""
        self._clear()
        self._mac = mac
        u, gap = self.UNIT, self.GAP
        block_gap = round(gap * 1.6)

        # ── main block: rows of keycaps stacked top-down ──
        rows = keyboard_data.rows_for(mac)
        main_w = 0
        y = 0
        for row in rows:
            x = 0
            for code, label, w in row:
                cap = _KeyCap(code, keyboard_data.key_label(code, label, mac),
                              w, u, gap, self)
                cap.move(x, y)
                cap.show()
                # Last write wins for duplicated codes (e.g. two Shift caps).
                self._caps[code] = cap
                x += cap.width() + gap
            main_w = max(main_w, x - gap)
            y += u + gap
        main_h = y - gap if rows else 0

        # ── nav cluster: bottom-justified to the right of the main block ──
        nav = keyboard_data.NAV_ROWS
        nav_h = len(nav) * (u + gap) - gap if nav else 0
        nav_x0 = main_w + block_gap
        nav_y0 = main_h - nav_h  # bottom-justify against the main block
        y = nav_y0
        nav_w = 0
        for row in nav:
            x = nav_x0
            for cell in row:
                if cell is None:
                    x += u + gap  # blank UNIT x UNIT spacer
                    continue
                code, label, w = cell
                cap = _KeyCap(code, keyboard_data.key_label(code, label, mac),
                              w, u, gap, self)
                cap.move(x, y)
                cap.show()
                self._caps[code] = cap
                x += cap.width() + gap
            nav_w = max(nav_w, x - nav_x0 - gap)
            y += u + gap

        total_w = nav_x0 + nav_w if nav else main_w
        self.setFixedSize(total_w, main_h)
        self._retint()

    # ── state ────────────────────────────────────────────────────────────────
    def set_state(self, *, assign: dict, conflict_vals: set, accent_c: str,
                  accent_b: str, active_code: str | None, mac: bool) -> None:
        if bool(mac) != self._mac:
            self._build(mac=bool(mac))
        self._assign = dict(assign)
        self._conflict_vals = set(conflict_vals)
        self._accent_c = accent_c
        self._accent_b = accent_b
        self._active_code = active_code
        self._mac = bool(mac)
        self._retint()

    def _classify(self, code: str) -> str:
        if code in self._conflict_vals:
            return "conflict"
        action = self._assign.get(code)
        if action is not None:
            return "movement" if keyboard_data.is_movement(action) else "aux"
        return "unassigned"

    def _retint(self) -> None:
        for code, cap in self._caps.items():
            cap.set_classification(self._classify(code),
                                   code == self._active_code)

    def apply_theme(self, is_dark: bool) -> None:
        self._is_dark = is_dark
        self._retint()
        self.update()
