"""The Appearance editor's controls (handoff §4.2, §4.3, §4.6).

Small widgets, each with one job and no knowledge of a store or of the
draft: they show what they are told and emit what the user did. The sheet
body (`appearance_sheet.py`) composes them and owns the draft.

Every colour comes from `palette.py`; every signal receiver is a bound
method (a lambda outlives its widget on PySide6 6.11).
"""
from __future__ import annotations

import math
from typing import Optional

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap,
)
from PySide6.QtWidgets import (
    QAbstractButton, QFrame, QGraphicsDropShadowEffect, QGridLayout,
    QHBoxLayout, QLabel, QPushButton, QScrollArea, QSizePolicy, QSlider,
    QVBoxLayout, QWidget,
)

from utils import cc_race_assets
from utils.icon_factory import (
    make_check_icon, make_chevron_down_icon, make_swap_icon,
)
from utils.rendition_poses import POSE_NAMES
from utils.toon_customization_resolve import (
    resolve_accent, resolve_portrait_transform,
)
from utils.toon_renders import ToonRenders
from utils.toon_silhouette import paint_race_silhouette
from utils.widgets.grandstand import palette as gp
from utils.widgets.grandstand.appearance_draft import POSE_LABELS, look_entry
from utils.widgets.grandstand.look_paint import (
    ART_INSET, HEAD_SCALE, HEAD_SHIFT, paint_look_disc,
)
from utils.widgets.grandstand.model import (
    CARD_POSE, PORTRAIT_RENDER, portrait_mode,
)

# Measurements, handoff §4.2 / §4.3 / §4.6.
CANVAS_D = 240
CANVAS_RING = 4
CHIP_H = 30
WELL_W, WELL_H, WELL_RADIUS = 44, 30, 8
SWATCH_D = 24
SWATCH_GAP = 7
SWATCH_COLUMNS = 6
POPOVER_PAD = 9
POPOVER_RADIUS = 11
POPOVER_GAP = 7
CLEAR_H = 24
GRADBAR_H = 10
SWAP_SIZE = 26
LOOK_GAP = 7
LOOK_RING = 2
LOOK_RING_PAD = 3            # room around a disc for its selected ring
LOOK_MAX_D = 64
LOOK_LABEL_GAP = 5
LOOK_LABEL_H = 12
POSE_TILE = 68
POSE_RADIUS = 10
POSE_GAP = 8
POSE_LABEL_GAP = 5
POSE_LABEL_H = 13
POSE_SCROLL_PAD = 8
POSE_SCROLLBAR = 5
POSE_FADE_W = 32
PILL_H = 32
PILL_PORTRAIT = 24
SWITCHER_W = 300
SWITCHER_PAD = 8
SWITCHER_RADIUS = 10
SWITCHER_TOP = 38
ROW_PORTRAIT = 30
ROW_PAD = 6
ROW_GAP = 10
SLIDER_LABEL_W = 42          # handoff: 34; "ZOOM" at 10 px / 800 needs 42 in DejaVu
SLIDER_VALUE_W = 46
STANDIN_ICON = 46


def transparent(widget: QWidget, name: str) -> None:
    """Containers are styled-background widgets under the app's global
    `QWidget { background-color }` rule; each must opt out or it paints a
    square of page colour over the sheet surface."""
    widget.setObjectName(name)
    widget.setStyleSheet(f"#{name} {{ background: transparent; }}")


def species_label(species: Optional[str]) -> str:
    """`DOG` / `dog` -> `Dog`; nothing known -> `Species` (handoff §4.6)."""
    text = (species or "").replace("_", " ").strip()
    return text.capitalize() if text else "Species"


def _shadow(widget: QWidget, color: QColor, blur: float, dy: float) -> None:
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(blur)
    effect.setOffset(0, dy)
    effect.setColor(color)
    widget.setGraphicsEffect(effect)


def _focus_ring(painter: QPainter, widget: QWidget, shape: QRectF,
                radius: float, is_dark: bool) -> None:
    """Keyboard focus on a painted control (handoff §5): a 2 px outline.
    These controls take focus from Tab only, so the ring never follows a
    mouse click. `radius` < 0 draws an ellipse."""
    if not widget.hasFocus():
        return
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setBrush(Qt.NoBrush)
    painter.setPen(QPen(gp.focus_ring(is_dark), 2))
    if radius < 0:
        painter.drawEllipse(shape)
    else:
        painter.drawRoundedRect(shape, radius, radius)
    painter.restore()


def _place_popover(popover: QWidget, anchor: QWidget, gap: int) -> None:
    """Below the anchor's left edge, kept inside the popover's parent; above
    the anchor when there is no room below."""
    host = popover.parentWidget()
    origin = anchor.mapTo(host, QPoint(0, 0))
    x = max(0, min(origin.x(), host.width() - popover.width()))
    y = origin.y() + anchor.height() + gap
    if y + popover.height() > host.height():
        above = origin.y() - gap - popover.height()
        y = above if above >= 0 else max(0, host.height() - popover.height())
    popover.move(x, y)


# ── text ────────────────────────────────────────────────────────────────────

class ElidedLabel(QLabel):
    """One line that gives way instead of dictating its row's width.

    By default it takes whatever its row has left (a right-aligned note).
    With `natural`, it asks for its text's width and only shrinks, eliding,
    when the row runs short (a hex readout beside a well)."""

    def __init__(self, parent: QWidget | None = None, natural: bool = False) -> None:
        super().__init__(parent)
        self._full = ""
        self._natural = natural
        self.setSizePolicy(
            QSizePolicy.Preferred if natural else QSizePolicy.Ignored,
            QSizePolicy.Preferred)

    def set_full_text(self, text: str) -> None:
        self._full = text
        self.setToolTip("")
        self.updateGeometry()
        self._elide()

    def full_text(self) -> str:
        return self._full

    def sizeHint(self) -> QSize:
        hint = super().sizeHint()
        if self._natural:
            hint.setWidth(self.fontMetrics().horizontalAdvance(self._full) + 2)
        return hint

    def minimumSizeHint(self) -> QSize:
        hint = super().minimumSizeHint()
        if self._natural:
            hint.setWidth(0)
        return hint

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._elide()

    def _elide(self) -> None:
        width = self.contentsRect().width()
        shown = self.fontMetrics().elidedText(self._full, Qt.ElideRight, width)
        super().setText(shown)
        self.setToolTip(self._full if shown != self._full else "")


class MiniLink(QPushButton):
    """`.minilink`: a text button, underlined on hover."""

    def __init__(self, text: str, gold: bool, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self._gold = gold
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.TabFocus)
        self.setFlat(True)

    def apply_theme(self, is_dark: bool) -> None:
        rest = gp.mini_link(self._gold, False, is_dark)
        hover = gp.mini_link(self._gold, True, is_dark)
        off = gp.appearance_disabled(is_dark)["ink"]
        self.setStyleSheet(
            "QPushButton { background: transparent; border: none; padding: 0;"
            f" color: {rest.name()}; font-size: 11px; font-weight: 600; }}"
            f" QPushButton:hover, QPushButton:focus {{ color: {hover.name()};"
            " text-decoration: underline; }"
            f" QPushButton:disabled {{ color: {off.name()}; }}")


class GroupHeader(QWidget):
    """`.grpH`: an uppercase label and a right-aligned note that elides."""

    def __init__(self, name: str, label: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        transparent(self, name)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        self.label = QLabel(label.upper(), self)
        self.note = ElidedLabel(self)
        self.note.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        row.addWidget(self.label, 0)
        row.addWidget(self.note, 1)
        self._label = label

    def set_label(self, label: str) -> None:
        self._label = label
        self.label.setText(label.upper())

    def label_text(self) -> str:
        return self._label

    def set_note(self, text: str) -> None:
        self.note.set_full_text(text)

    def note_text(self) -> str:
        return self.note.full_text()

    def apply_theme(self, is_dark: bool) -> None:
        ink = gp.appearance_group_ink(is_dark)
        self.label.setStyleSheet(
            f"color: {ink['label'].name()}; font-size: 10px; font-weight: 600;"
            " letter-spacing: 0.5px; background: transparent;")
        self.note.setStyleSheet(
            f"color: {ink['note'].name()}; font-size: 10px;"
            " background: transparent;")


# ── chips ───────────────────────────────────────────────────────────────────

class Chip(QPushButton):
    def __init__(self, key, label: str, parent: QWidget | None = None) -> None:
        super().__init__(label, parent)
        self.key = key
        self.setCheckable(True)
        self.setFixedHeight(CHIP_H)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.TabFocus)

    def apply_theme(self, is_dark: bool) -> None:
        rest = gp.appearance_chip(False, False, is_dark)
        hover = gp.appearance_chip(False, True, is_dark)
        on = gp.appearance_chip(True, False, is_dark)
        off = gp.appearance_disabled(is_dark)
        self.setStyleSheet(
            "QPushButton {"
            f" background: {rest['bg'].name(QColor.HexArgb)};"
            f" border: 1px solid {rest['border'].name()};"
            f" border-radius: {CHIP_H // 2}px; padding: 0 13px;"
            f" color: {rest['ink'].name()}; font-size: 12px; font-weight: 500; }}"
            " QPushButton:hover {"
            f" border: 1px solid {hover['border'].name()};"
            f" color: {hover['ink'].name()}; }}"
            " QPushButton:checked {"
            f" background: {on['bg'].name(QColor.HexArgb)};"
            f" border: 1px solid {on['border'].name()};"
            f" color: {on['ink'].name()}; }}"
            " QPushButton:focus {"
            f" border: 2px solid {gp.focus_ring(is_dark).name()};"
            " padding: 0 12px; }"
            " QPushButton:disabled {"
            f" border: 1px solid {off['border'].name()};"
            f" color: {off['ink'].name()}; }}")


class ChipRow(QWidget):
    """One choice out of a few. Exactly one chip is lit; clicking the lit
    chip keeps it lit."""

    value_changed = Signal(object)

    def __init__(self, name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        transparent(self, name)
        self._is_dark = True
        self._chips: list[Chip] = []
        self._value = None
        self._row = QHBoxLayout(self)
        self._row.setContentsMargins(0, 0, 0, 0)
        self._row.setSpacing(7)

    def set_choices(self, choices: list) -> None:
        if [(c.key, c.text()) for c in self._chips] == list(choices):
            return
        for chip in self._chips:
            self._row.removeWidget(chip)
            chip.setParent(None)
            chip.deleteLater()
        self._chips = []
        for key, label in choices:
            chip = Chip(key, label, self)
            chip.clicked.connect(self._on_chip_clicked)
            chip.apply_theme(self._is_dark)
            self._row.addWidget(chip)
            self._chips.append(chip)
        self.set_value(self._value)

    def chips(self) -> list[Chip]:
        return list(self._chips)

    def chip(self, key) -> Optional[Chip]:
        return next((c for c in self._chips if c.key == key), None)

    def value(self):
        return self._value

    def set_value(self, key) -> None:
        self._value = key
        for chip in self._chips:
            chip.setChecked(chip.key == key)

    def _on_chip_clicked(self) -> None:
        chip = self.sender()
        if not isinstance(chip, Chip):
            return
        self.set_value(chip.key)
        self.value_changed.emit(chip.key)

    def apply_theme(self, is_dark: bool) -> None:
        self._is_dark = is_dark
        for chip in self._chips:
            chip.apply_theme(is_dark)


# ── colour wells ────────────────────────────────────────────────────────────

class ColorWell(QAbstractButton):
    """`.well`: one colour, opened on demand. An unset well shows the
    diagonal "automatic" hatch instead of a colour."""

    def __init__(self, key: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.key = key
        self._color: Optional[str] = None
        self._open = False
        self._is_dark = True
        self.setFixedSize(WELL_W, WELL_H)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.TabFocus)
        self.setAccessibleName("Choose colour")
        self.setAttribute(Qt.WA_Hover, True)

    def color(self) -> Optional[str]:
        return self._color

    def set_color(self, hex_: Optional[str], tooltip: str = "") -> None:
        self._color = hex_
        self.setToolTip(tooltip or hex_ or "Automatic")
        self.update()

    def is_open(self) -> bool:
        return self._open

    def set_open(self, value: bool) -> None:
        if value != self._open:
            self._open = value
            self.update()

    def apply_theme(self, is_dark: bool) -> None:
        self._is_dark = is_dark
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        state = "open" if self._open else (
            "hover" if self.underMouse() and self.isEnabled() else "rest")
        d = gp.color_well(state, self._is_dark)
        box = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(box, WELL_RADIUS, WELL_RADIUS)
        if self._color:
            p.fillPath(path, QColor(self._color))
        else:
            p.save()
            p.setClipPath(path)
            pen = QPen(d["hatch"], 3.5)
            p.setPen(pen)
            h = self.height()
            for k in range(-h, self.width() + h, 10):
                p.drawLine(QPointF(k, h), QPointF(k + h, 0))
            p.restore()
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(d["inset"], 1))
        p.drawRoundedRect(box.adjusted(1, 1, -1, -1), WELL_RADIUS - 1, WELL_RADIUS - 1)
        p.setPen(QPen(d["border"], 1))
        p.drawPath(path)
        _focus_ring(p, self, box.adjusted(0.5, 0.5, -0.5, -0.5),
                    WELL_RADIUS, self._is_dark)
        p.end()


class _Swatch(QAbstractButton):
    def __init__(self, hex_: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.hex = hex_
        self._selected = False
        self._is_dark = True
        self.setFixedSize(SWATCH_D, SWATCH_D)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.TabFocus)
        self.setToolTip(hex_)
        self.setAccessibleName(hex_)
        self.setAttribute(Qt.WA_Hover, True)

    def is_selected(self) -> bool:
        return self._selected

    def set_selected(self, value: bool) -> None:
        self._selected = value
        self.update()

    def apply_theme(self, is_dark: bool) -> None:
        self._is_dark = is_dark
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        d = gp.well_popover(self._is_dark)
        box = QRectF(self.rect())
        inset = 2.0 if (self._selected or self.underMouse()) else 3.0
        disc = box.adjusted(inset, inset, -inset, -inset)
        p.setPen(QPen(d["swatch_inset"], 1))
        p.setBrush(QColor(self.hex))
        p.drawEllipse(disc)
        if self._selected:
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(d["swatch_ring"], 2))
            p.drawEllipse(box.adjusted(1, 1, -1, -1))
        _focus_ring(p, self, box.adjusted(1, 1, -1, -1), -1, self._is_dark)
        p.end()


class SwatchPopover(QFrame):
    """`.pop`: the twelve swatches, plus an optional clear button (the
    accent's "Use game accent"). A child of the editor, raised over it."""

    color_picked = Signal(object)          # hex str | None (cleared)

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("gs_well_pop")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._is_dark = True
        self._anchor: Optional[QWidget] = None
        col = QVBoxLayout(self)
        col.setContentsMargins(POPOVER_PAD, POPOVER_PAD, POPOVER_PAD, POPOVER_PAD)
        col.setSpacing(POPOVER_PAD)
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(SWATCH_GAP)
        self._swatches: list[_Swatch] = []
        for index, hex_ in enumerate(gp.SWATCHES):
            swatch = _Swatch(hex_, self)
            swatch.clicked.connect(self._on_swatch_clicked)
            grid.addWidget(swatch, index // SWATCH_COLUMNS, index % SWATCH_COLUMNS)
            self._swatches.append(swatch)
        col.addLayout(grid)
        self.clear_button = QPushButton(self)
        self.clear_button.setFixedHeight(CLEAR_H)
        self.clear_button.setCursor(Qt.PointingHandCursor)
        self.clear_button.setFocusPolicy(Qt.TabFocus)
        self.clear_button.clicked.connect(self._on_clear_clicked)
        col.addWidget(self.clear_button)
        self.hide()
        self.apply_theme(True)

    def swatches(self) -> list[_Swatch]:
        return list(self._swatches)

    def anchor(self) -> Optional[QWidget]:
        return self._anchor

    def open_for(self, anchor: QWidget, current: Optional[str],
                 clear_text: str = "") -> None:
        self._anchor = anchor
        current = (current or "").lower()
        for swatch in self._swatches:
            swatch.set_selected(swatch.hex == current)
        self.clear_button.setText(clear_text)
        self.clear_button.setVisible(bool(clear_text))
        self.adjustSize()
        _place_popover(self, anchor, POPOVER_GAP)
        self.show()
        self.raise_()

    def close_popover(self) -> None:
        self._anchor = None
        self.hide()

    def _on_swatch_clicked(self) -> None:
        swatch = self.sender()
        if isinstance(swatch, _Swatch):
            self.color_picked.emit(swatch.hex)

    def _on_clear_clicked(self) -> None:
        self.color_picked.emit(None)

    def apply_theme(self, is_dark: bool) -> None:
        self._is_dark = is_dark
        d = gp.well_popover(is_dark)
        self.setStyleSheet(
            f"QFrame#gs_well_pop {{ background: {d['bg'].name()};"
            f" border: 1px solid {d['border'].name()};"
            f" border-radius: {POPOVER_RADIUS}px; }}")
        self.clear_button.setStyleSheet(
            "QPushButton { background: transparent;"
            f" border: 1px dashed {d['clear_border'].name()};"
            f" border-radius: 8px; padding: 0 8px; color: {d['clear_ink'].name()};"
            " font-size: 10px; font-weight: 600; }"
            " QPushButton:hover {"
            f" border: 1px dashed {d['clear_hover'].name()};"
            f" color: {d['clear_hover'].name()}; }}")
        _shadow(self, d["shadow"], 34, 14)
        for swatch in self._swatches:
            swatch.apply_theme(is_dark)


class GradientBar(QWidget):
    """`.gradbar`: the gradient itself, between its two wells."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._start = self._end = None
        self._is_dark = True
        self.setFixedHeight(GRADBAR_H)
        self.setMinimumWidth(40)
        self.setMaximumWidth(96)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_stops(self, start: str, end: str) -> None:
        self._start, self._end = start, end
        self.update()

    def stops(self) -> tuple:
        return (self._start, self._end)

    def apply_theme(self, is_dark: bool) -> None:
        self._is_dark = is_dark
        self.update()

    def paintEvent(self, event) -> None:
        if not self._start or not self._end:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        box = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        grad = QLinearGradient(box.topLeft(), box.topRight())
        grad.setColorAt(0.0, QColor(self._start))
        grad.setColorAt(1.0, QColor(self._end))
        p.setBrush(grad)
        p.setPen(QPen(gp.gradient_bar_border(self._is_dark), 1))
        p.drawRoundedRect(box, box.height() / 2, box.height() / 2)
        p.end()


class SwapButton(QAbstractButton):
    """`.swapbtn`: swap the gradient's two ends."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._is_dark = True
        self.setFixedSize(SWAP_SIZE, SWAP_SIZE)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.TabFocus)
        self.setToolTip("Swap ends")
        self.setAccessibleName("Swap ends")
        self.setAttribute(Qt.WA_Hover, True)

    def apply_theme(self, is_dark: bool) -> None:
        self._is_dark = is_dark
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        d = gp.swap_button(self.underMouse(), self._is_dark)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(d["border"], 1))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)
        icon = make_swap_icon(13, d["ink"]).pixmap(13, 13)
        p.drawPixmap((self.width() - 13) // 2, (self.height() - 13) // 2, icon)
        _focus_ring(p, self, QRectF(self.rect()).adjusted(1, 1, -1, -1), 8,
                    self._is_dark)
        p.end()


# ── looks ───────────────────────────────────────────────────────────────────

class LookSwatch(QAbstractButton):
    """One curated Look, painted with the account's own toon so the choice
    is judged in context (handoff §4.2)."""

    def __init__(self, index: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.index = index
        self.name = gp.LOOKS[index][0]
        self._entry = look_entry(index)
        self._art: Optional[QPixmap] = None
        self._art_scale, self._art_shift = 1.0, 0.0
        self._accent_fallback = QColor()
        self._selected = False
        self._is_dark = True
        self._disc = 56
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.TabFocus)
        self.setToolTip(self.name)
        self.setAccessibleName(self.name)
        self.setAttribute(Qt.WA_Hover, True)

    def is_selected(self) -> bool:
        return self._selected

    def set_selected(self, value: bool) -> None:
        if value != self._selected:
            self._selected = value
            self.update()

    def art(self) -> Optional[QPixmap]:
        return self._art

    def set_art(self, art: Optional[QPixmap], scale: float, shift: float) -> None:
        self._art, self._art_scale, self._art_shift = art, scale, shift
        self.update()

    def set_accent_fallback(self, color: QColor) -> None:
        self._accent_fallback = QColor(color)
        self.update()

    def set_disc(self, diameter: int) -> None:
        self._disc = diameter
        self.update()

    def disc_rect(self) -> QRectF:
        x = (self.width() - self._disc) / 2.0
        return QRectF(x, LOOK_RING_PAD, self._disc, self._disc)

    def apply_theme(self, is_dark: bool) -> None:
        self._is_dark = is_dark
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        d = gp.look_swatch(self._selected, self._is_dark)
        disc = self.disc_rect()
        if self.underMouse() and self.isEnabled() and not self._selected:
            grow = min(LOOK_RING_PAD - 1.0, self._disc * 0.035)
            disc = disc.adjusted(-grow, -grow, grow, grow)
        paint_look_disc(
            p, disc, self._entry,
            fill_fallback=gp.portrait_fallback(self._is_dark),
            accent_fallback=self._accent_fallback, ring_width=LOOK_RING,
            art=self._art, art_scale=self._art_scale, art_shift=self._art_shift)
        if self._selected:
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(d["gap"], 1))
            p.drawEllipse(disc.adjusted(-0.5, -0.5, 0.5, 0.5))
            p.setPen(QPen(d["ring"], 2))
            p.drawEllipse(disc.adjusted(-2, -2, 2, 2))
        _focus_ring(p, self, disc.adjusted(-2, -2, 2, 2), -1, self._is_dark)
        font = self.font()
        font.setPixelSize(9)
        font.setBold(self._selected)
        p.setFont(font)
        p.setPen(d["ink"] if self.isEnabled()
                 else gp.appearance_disabled(self._is_dark)["ink"])
        label = QRect(0, LOOK_RING_PAD + self._disc + LOOK_LABEL_GAP,
                      self.width(), LOOK_LABEL_H)
        text = p.fontMetrics().elidedText(self.name, Qt.ElideRight, label.width())
        p.drawText(label, Qt.AlignHCenter | Qt.AlignVCenter, text)
        p.end()


class LooksRow(QWidget):
    """`.looks`: eight equal columns. The discs take the column width (up to
    LOOK_MAX_D), so the row's height follows its width."""

    look_clicked = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.swatches: list[LookSwatch] = []
        for index in range(len(gp.LOOKS)):
            swatch = LookSwatch(index, self)
            swatch.clicked.connect(self._on_swatch_clicked)
            self.swatches.append(swatch)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._relayout()

    @staticmethod
    def height_for_disc(diameter: int) -> int:
        return LOOK_RING_PAD + diameter + LOOK_LABEL_GAP + LOOK_LABEL_H + 1

    def _relayout(self) -> None:
        count = len(self.swatches)
        # The row keeps the ring's reach clear at both ends, or the first
        # and last selected rings would be cut by the row's own edge.
        usable = max(self.width(), 1) - 2 * LOOK_RING_PAD
        slot = (usable - (count - 1) * LOOK_GAP) / count
        disc = int(max(16, min(LOOK_MAX_D, slot)))
        height = self.height_for_disc(disc)
        for index, swatch in enumerate(self.swatches):
            # A swatch overlaps the gaps either side by the ring's reach, so
            # the selected ring is not clipped by its own widget.
            left = round(index * (slot + LOOK_GAP))
            swatch.set_disc(disc)
            swatch.setGeometry(left, 0, round(slot) + 2 * LOOK_RING_PAD, height)
        if self.minimumHeight() != height or self.maximumHeight() != height:
            self.setFixedHeight(height)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._relayout()

    def sizeHint(self) -> QSize:
        return QSize(8 * 56 + 7 * LOOK_GAP, self.height_for_disc(56))

    def minimumSizeHint(self) -> QSize:
        return QSize(8 * 28 + 7 * LOOK_GAP, self.height_for_disc(28))

    def selected(self) -> Optional[int]:
        return next((s.index for s in self.swatches if s.is_selected()), None)

    def set_selected(self, index: Optional[int]) -> None:
        for swatch in self.swatches:
            swatch.set_selected(swatch.index == index)

    def set_art(self, art: Optional[QPixmap], scale: float, shift: float) -> None:
        for swatch in self.swatches:
            swatch.set_art(art, scale, shift)

    def set_accent_fallback(self, color: QColor) -> None:
        for swatch in self.swatches:
            swatch.set_accent_fallback(color)

    def _on_swatch_clicked(self) -> None:
        swatch = self.sender()
        if isinstance(swatch, LookSwatch):
            self.look_clicked.emit(swatch.index)

    def apply_theme(self, is_dark: bool) -> None:
        for swatch in self.swatches:
            swatch.apply_theme(is_dark)


# ── poses ───────────────────────────────────────────────────────────────────

class PoseTile(QAbstractButton):
    """One pose: its render in a 68 px tile, its human name beneath."""

    def __init__(self, pose: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.pose = pose
        self.label = POSE_LABELS[pose]
        self._pixmap: Optional[QPixmap] = None
        self._scaled: Optional[QPixmap] = None
        self._selected = False
        self._is_dark = True
        self.setFixedSize(POSE_TILE, POSE_TILE + POSE_LABEL_GAP + POSE_LABEL_H)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.TabFocus)
        self.setToolTip(self.label)
        self.setAccessibleName(self.label)
        self.setAttribute(Qt.WA_Hover, True)

    def is_selected(self) -> bool:
        return self._selected

    def set_selected(self, value: bool) -> None:
        if value != self._selected:
            self._selected = value
            self.update()

    def pixmap(self) -> Optional[QPixmap]:
        return self._pixmap

    def set_pixmap(self, pixmap: Optional[QPixmap]) -> None:
        self._pixmap = pixmap
        self._scaled = None
        if pixmap is not None and not pixmap.isNull():
            self._scaled = pixmap.scaled(
                POSE_TILE - 4, POSE_TILE - 4, Qt.KeepAspectRatio,
                Qt.SmoothTransformation)
        self.update()

    def apply_theme(self, is_dark: bool) -> None:
        self._is_dark = is_dark
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        hover = self.underMouse() and self.isEnabled()
        d = gp.pose_tile(self._selected, hover, self._is_dark)
        tile = QRectF(1.5, 1.5, POSE_TILE - 3, POSE_TILE - 3)
        if d["glow"] is not None:
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(d["glow"], 3))
            p.drawRoundedRect(tile, POSE_RADIUS, POSE_RADIUS)
        p.setPen(Qt.NoPen)
        p.setBrush(d["bg"])
        p.drawRoundedRect(tile, POSE_RADIUS, POSE_RADIUS)
        if self._scaled is not None:
            clip = QPainterPath()
            clip.addRoundedRect(tile, POSE_RADIUS, POSE_RADIUS)
            p.save()
            p.setClipPath(clip)
            p.drawPixmap(int((POSE_TILE - self._scaled.width()) / 2),
                         int((POSE_TILE - self._scaled.height()) / 2),
                         self._scaled)
            p.restore()
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(d["border"], 2 if self._selected else 1))
        p.drawRoundedRect(tile, POSE_RADIUS, POSE_RADIUS)
        _focus_ring(p, self, tile, POSE_RADIUS, self._is_dark)
        font = self.font()
        font.setPixelSize(9)
        font.setBold(self._selected)
        p.setFont(font)
        p.setPen(d["ink"])
        label = QRect(0, POSE_TILE + POSE_LABEL_GAP, self.width(), POSE_LABEL_H)
        text = p.fontMetrics().elidedText(self.label, Qt.ElideRight, label.width())
        p.drawText(label, Qt.AlignHCenter | Qt.AlignVCenter, text)
        p.end()


class _EdgeFade(QWidget):
    """The strip's right-edge fade: says there is more without an arrow."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self._is_dark = True
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)

    def apply_theme(self, is_dark: bool) -> None:
        self._is_dark = is_dark
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        solid, clear = gp.pose_fade(self._is_dark)
        grad = QLinearGradient(QPointF(0, 0), QPointF(self.width(), 0))
        grad.setColorAt(0.0, clear)
        grad.setColorAt(1.0, solid)
        p.fillRect(self.rect(), grad)
        p.end()


class _SidewaysScroll(QScrollArea):
    """A horizontal-only scroll area a plain mouse wheel can drive. Qt sends
    a vertical wheel to the vertical bar, which here has no range, so a
    strip wider than its row could only be dragged by its 5 px scrollbar."""

    def wheelEvent(self, event) -> None:
        delta = event.angleDelta()
        bar = self.horizontalScrollBar()
        if delta.x() == 0 and delta.y() != 0 and bar.maximum() > bar.minimum():
            target = max(bar.minimum(), min(bar.maximum(), bar.value() - delta.y()))
            if target != bar.value():
                bar.setValue(target)
                event.accept()
                return
            event.ignore()               # at the end: let the body scroll
            return
        super().wheelEvent(event)


class PoseStrip(QWidget):
    """The thirteen poses in a horizontal strip (handoff §4.6 `render`)."""

    pose_clicked = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        transparent(self, "gs_pose_strip")
        tile_h = POSE_TILE + POSE_LABEL_GAP + POSE_LABEL_H
        self.setFixedHeight(tile_h + POSE_SCROLL_PAD + POSE_SCROLLBAR)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.scroll = _SidewaysScroll(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._inner = QWidget()
        transparent(self._inner, "gs_pose_inner")
        row = QHBoxLayout(self._inner)
        row.setContentsMargins(0, 0, 0, POSE_SCROLL_PAD)
        row.setSpacing(POSE_GAP)
        self.tiles: list[PoseTile] = []
        for pose in POSE_NAMES:
            tile = PoseTile(pose, self._inner)
            tile.clicked.connect(self._on_tile_clicked)
            row.addWidget(tile)
            self.tiles.append(tile)
        row.addStretch(1)
        self.scroll.setWidget(self._inner)
        outer.addWidget(self.scroll)
        self.fade = _EdgeFade(self)
        bar = self.scroll.horizontalScrollBar()
        bar.valueChanged.connect(self._update_fade)
        bar.rangeChanged.connect(self._update_fade)
        self.apply_theme(True)

    def tile(self, pose: str) -> Optional[PoseTile]:
        return next((t for t in self.tiles if t.pose == pose), None)

    def selected(self) -> Optional[str]:
        return next((t.pose for t in self.tiles if t.is_selected()), None)

    def set_selected(self, pose: Optional[str]) -> None:
        for tile in self.tiles:
            tile.set_selected(tile.pose == pose)

    def reveal(self, pose: str) -> None:
        tile = self.tile(pose)
        if tile is not None:
            self.scroll.ensureWidgetVisible(tile, POSE_FADE_W, 0)

    def set_pixmap(self, pose: str, pixmap: Optional[QPixmap]) -> None:
        tile = self.tile(pose)
        if tile is not None:
            tile.set_pixmap(pixmap)

    def _on_tile_clicked(self) -> None:
        tile = self.sender()
        if isinstance(tile, PoseTile):
            self.pose_clicked.emit(tile.pose)

    def _update_fade(self, *_args) -> None:
        bar = self.scroll.horizontalScrollBar()
        self.fade.setVisible(bar.value() < bar.maximum() - 4)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        tile_h = POSE_TILE + POSE_LABEL_GAP + POSE_LABEL_H
        self.fade.setGeometry(self.width() - POSE_FADE_W, 0, POSE_FADE_W, tile_h)
        self.fade.raise_()
        self._update_fade()

    def apply_theme(self, is_dark: bool) -> None:
        thumb = gp.shelf_scroll(is_dark)["thumb"]
        self.scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            " QScrollArea > QWidget#qt_scrollarea_viewport {"
            " background: transparent; }"
            f" QScrollBar:horizontal {{ height: {POSE_SCROLLBAR}px;"
            " background: transparent; margin: 0; }"
            " QScrollBar::handle:horizontal { border-radius: 2px;"
            f" min-width: 24px; background: {thumb.name()}; }}"
            " QScrollBar::add-line:horizontal,"
            " QScrollBar::sub-line:horizontal { width: 0; }"
            " QScrollBar::add-page:horizontal,"
            " QScrollBar::sub-page:horizontal { background: transparent; }")
        self.fade.apply_theme(is_dark)
        for tile in self.tiles:
            tile.apply_theme(is_dark)


# ── the framing canvas ──────────────────────────────────────────────────────

class FramingCanvas(QWidget):
    """`.fcircle`: the 240 px portrait disc. It paints the look it is given
    and reports a drag as new offsets; it never holds the draft."""

    framing_dragged = Signal(float, float)        # off_x, off_y

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(CANVAS_D, CANVAS_D)
        self._entry: dict = {}
        self._accent_fallback = QColor()
        self._art: Optional[QPixmap] = None
        self._art_scale = 1.0
        self._framed = False
        self._draggable = False
        self._is_dark = True
        self._drag_from: Optional[QPointF] = None
        self._drag_initial = (1.0, 0.0, 0.0, 0.0)
        self.setAccessibleName("Portrait framing")

    # inbound
    def set_look(self, entry: dict, accent_fallback: QColor) -> None:
        self._entry = entry
        self._accent_fallback = QColor(accent_fallback)
        self.update()

    def look(self) -> dict:
        return self._entry

    def set_art(self, art: Optional[QPixmap], scale: float, framed: bool) -> None:
        self._art, self._art_scale, self._framed = art, scale, framed
        self.update()

    def art(self) -> Optional[QPixmap]:
        return self._art

    def set_draggable(self, value: bool) -> None:
        self._draggable = value
        self._drag_from = None
        self.setCursor(Qt.OpenHandCursor if value else Qt.ArrowCursor)
        self.setToolTip("Drag to reposition" if value else "")

    def is_draggable(self) -> bool:
        return self._draggable

    def apply_theme(self, is_dark: bool) -> None:
        self._is_dark = is_dark
        self.update()

    # drag
    def _transform(self) -> tuple[float, float, float, float]:
        try:
            return resolve_portrait_transform(self._entry)
        except (TypeError, ValueError):
            return (1.0, 0.0, 0.0, 0.0)

    def mousePressEvent(self, event) -> None:
        if self._draggable and event.button() == Qt.LeftButton:
            self._drag_from = event.position()
            self._drag_initial = self._transform()
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._drag_from is None:
            super().mouseMoveEvent(event)
            return
        zoom, off_x, off_y, rotate = self._drag_initial
        delta = event.position() - self._drag_from
        # Production paints rotate-then-offset, with the offset scaled by the
        # zoom. Undo both so the portrait stays under the pointer.
        angle = math.radians(-rotate)
        dx = delta.x() * math.cos(angle) - delta.y() * math.sin(angle)
        dy = delta.x() * math.sin(angle) + delta.y() * math.cos(angle)
        scale = CANVAS_D * max(zoom, 0.01)
        self.framing_dragged.emit(off_x + dx / scale, off_y + dy / scale)
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        if self._drag_from is not None and event.button() == Qt.LeftButton:
            self._drag_from = None
            self.setCursor(Qt.OpenHandCursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        paint_look_disc(
            p, QRectF(self.rect()), self._entry,
            fill_fallback=gp.portrait_fallback(self._is_dark),
            accent_fallback=self._accent_fallback, ring_width=CANVAS_RING,
            art=self._art, art_scale=self._art_scale, framed=self._framed)
        p.end()


class SliderRow(QWidget):
    """Label, slider, value: Zoom and Turn under the canvas."""

    value_changed = Signal(int)

    def __init__(self, name: str, label: str, minimum: int, maximum: int,
                 filled: bool, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        transparent(self, name)
        self._filled = filled
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(9)
        self.label = QLabel(label.upper(), self)
        self.label.setFixedWidth(SLIDER_LABEL_W)
        self.slider = QSlider(Qt.Horizontal, self)
        self.slider.setRange(minimum, maximum)
        self.slider.setFixedHeight(20)
        self.slider.setFocusPolicy(Qt.TabFocus)
        self.slider.setAccessibleName(label)
        self.slider.valueChanged.connect(self.value_changed.emit)
        self.value = QLabel(self)
        self.value.setFixedWidth(SLIDER_VALUE_W)
        self.value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        row.addWidget(self.label)
        row.addWidget(self.slider, 1)
        row.addWidget(self.value)

    def set_value(self, value: int, text: str) -> None:
        """Programmatic: shows a value without reporting it as an edit."""
        self.slider.blockSignals(True)
        self.slider.setValue(value)
        self.slider.blockSignals(False)
        self.value.setText(text)

    def set_text(self, text: str) -> None:
        self.value.setText(text)

    def apply_theme(self, is_dark: bool) -> None:
        d = gp.appearance_stage(is_dark)
        fill = d["fill"] if self._filled else d["groove"]
        self.label.setStyleSheet(
            f"color: {d['hint'].name()}; font-size: 10px; font-weight: 800;"
            " letter-spacing: 0.6px; background: transparent;")
        self.value.setStyleSheet(
            f"color: {d['value'].name()}; font-size: 11px; font-weight: 500;"
            " background: transparent;")
        self.slider.setStyleSheet(
            "QSlider { background: transparent; }"
            " QSlider::groove:horizontal { height: 4px; border-radius: 2px;"
            f" background: {d['groove'].name(QColor.HexArgb)}; }}"
            " QSlider::sub-page:horizontal { border-radius: 2px;"
            f" background: {fill.name(QColor.HexArgb)}; }}"
            " QSlider::handle:horizontal { width: 12px; height: 12px;"
            " margin: -5px 0; border-radius: 7px;"
            f" background: {d['handle'].name()};"
            f" border: 1px solid {d['handle_border'].name(QColor.HexArgb)}; }}")


# ── the subject row ─────────────────────────────────────────────────────────

class MiniPortrait(QWidget):
    """A small disc: the toon's `head` from the render cache, or its race
    silhouette, ringed in an accent. A cache consumer like the card: it
    reads when told to and never writes."""

    def __init__(self, size: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._game = "ttr"
        self._name: Optional[str] = None
        self._species: Optional[str] = None
        self._dna = ""
        self._ring = QColor()
        self._pixmap: Optional[QPixmap] = None
        self._is_dark = True

    def set_toon(self, game: str, name: Optional[str], species: Optional[str],
                 dna: str, ring: QColor) -> None:
        self._game, self._name = game, name
        self._species, self._dna = species, dna or ""
        self._ring = QColor(ring)
        self.refresh()

    def set_ring(self, ring: QColor) -> None:
        self._ring = QColor(ring)
        self.update()

    def toon_name(self) -> Optional[str]:
        return self._name

    def pixmap(self) -> Optional[QPixmap]:
        return self._pixmap

    def refresh(self) -> None:
        """Re-read the cache (open, a landing, a promotion)."""
        self._pixmap = None
        if (self._name and portrait_mode(self._game, bool(self._dna))
                == PORTRAIT_RENDER):
            hit = ToonRenders.instance().pixmap_for(self._game, self._name, CARD_POSE)
            self._pixmap = hit[0] if hit is not None else None
        self.update()

    def apply_theme(self, is_dark: bool) -> None:
        self._is_dark = is_dark
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        d = gp.subject_pill(False, self._is_dark)
        box = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        if not self._name:
            # No toon: the reference build's dashed empty disc.
            pen = QPen(d["empty_ring"], 2)
            pen.setStyle(Qt.DashLine)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(box)
            p.end()
            return
        p.setPen(Qt.NoPen)
        p.setBrush(d["portrait_bg"])
        p.drawEllipse(box)
        clip = QPainterPath()
        clip.addEllipse(box)
        p.save()
        p.setClipPath(clip)
        if self._pixmap is not None and not self._pixmap.isNull():
            side = box.width() * HEAD_SCALE
            target = QRectF(box.center().x() - side / 2,
                            box.center().y() - side / 2 + box.height() * HEAD_SHIFT,
                            side, side)
            p.drawPixmap(target, self._pixmap, QRectF(self._pixmap.rect()))
        else:
            # No render: the race icon itself, as the hero cameo and the
            # canvas draw it. A silhouette filled with the ring's own colour
            # would vanish into the ring.
            inset = box.width() * (1 - ART_INSET) / 2
            art_box = box.adjusted(inset, inset, -inset, -inset)
            stem = cc_race_assets.asset_stem_for_species(self._species)
            icon = cc_race_assets.load_race_pixmap(stem) if stem else None
            if icon is not None and not icon.isNull():
                scaled = icon.scaled(art_box.size().toSize(), Qt.KeepAspectRatio,
                                     Qt.SmoothTransformation)
                p.drawPixmap(
                    QPointF(art_box.center().x() - scaled.width() / 2,
                            art_box.center().y() - scaled.height() / 2), scaled)
        p.restore()
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(self._ring, 2))
        p.drawEllipse(box.adjusted(1, 1, -1, -1))
        p.end()


class SubjectPill(QPushButton):
    """`.subj`: the toon the editor is styling. The pill is the control that
    changes it (handoff §4.3)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("gs_subj")
        self.setFixedHeight(PILL_H)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.TabFocus)
        self.setToolTip("Change which toon this account shows")
        self._is_dark = True
        row = QHBoxLayout(self)
        row.setContentsMargins(4, 0, 11, 0)
        row.setSpacing(8)
        self.portrait = MiniPortrait(PILL_PORTRAIT, self)
        self.name = QLabel(self)
        self.name.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.chevron = QLabel(self)
        self.chevron.setFixedSize(12, 12)
        self.chevron.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        row.addWidget(self.portrait, 0, Qt.AlignVCenter)
        row.addWidget(self.name, 0, Qt.AlignVCenter)
        row.addWidget(self.chevron, 0, Qt.AlignVCenter)

    def set_name(self, text: str) -> None:
        self.name.setText(text)
        self.setAccessibleName(text)
        self.updateGeometry()

    def name_text(self) -> str:
        return self.name.text()

    def sizeHint(self) -> QSize:
        return QSize(self.layout().sizeHint().width(), PILL_H)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def apply_theme(self, is_dark: bool) -> None:
        self._is_dark = is_dark
        rest = gp.subject_pill(False, is_dark)
        hover = gp.subject_pill(True, is_dark)
        self.setStyleSheet(
            "QPushButton#gs_subj {"
            f" background: {rest['bg'].name(QColor.HexArgb)};"
            f" border: 1px solid {rest['border'].name()};"
            f" border-radius: {PILL_H // 2}px; padding: 0; }}"
            " QPushButton#gs_subj:hover {"
            f" background: {hover['bg'].name(QColor.HexArgb)};"
            f" border: 1px solid {hover['border'].name()}; }}"
            " QPushButton#gs_subj:focus {"
            f" border: 2px solid {gp.focus_ring(is_dark).name()}; }}")
        self.name.setStyleSheet(
            f"color: {rest['ink'].name()}; font-size: 12px; font-weight: 800;"
            " background: transparent;")
        self.chevron.setStyleSheet("background: transparent;")
        self.chevron.setPixmap(
            make_chevron_down_icon(12, rest["chevron"]).pixmap(12, 12))
        self.portrait.apply_theme(is_dark)


class ScopeDot(QWidget):
    """The 6 px dot beside the scope line, in the look's current accent."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(6, 6)
        self._color = QColor()

    def set_color(self, color: QColor) -> None:
        self._color = QColor(color)
        self.update()

    def color(self) -> QColor:
        return QColor(self._color)

    def paintEvent(self, event) -> None:
        if not self._color.isValid():
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(self._color)
        p.drawEllipse(self.rect())
        p.end()


class ToonRow(QAbstractButton):
    """`.trow`: one toon the account has been seen playing."""

    def __init__(self, game: str, rec, current: bool, parent: QWidget) -> None:
        super().__init__(parent)
        self.toon = rec.toon_name
        self.meta = " · ".join(part for part in (
            species_label(rec.species) if rec.species else "",
            f"Laff {rec.laff}" if getattr(rec, "laff", None) is not None else "",
        ) if part)
        self._current = current
        self._is_dark = True
        self.setFixedHeight(ROW_PORTRAIT + 2 * ROW_PAD)
        self.setEnabled(not current)
        self.setCursor(Qt.ArrowCursor if current else Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus if current else Qt.TabFocus)
        self.setAttribute(Qt.WA_Hover, True)
        self.setAccessibleName(self.toon)
        self.setToolTip(f"{self.toon} is what this account shows" if current
                        else f"Show {self.toon} for this account")
        self.portrait = MiniPortrait(ROW_PORTRAIT, self)
        self.portrait.move(ROW_PAD, ROW_PAD)
        ring = resolve_accent({"accent": getattr(rec, "accent", None)},
                              QColor(gp.game_accent(game)))
        self.portrait.set_toon(game, rec.toon_name, rec.species, rec.dna, ring)

    def is_current(self) -> bool:
        return self._current

    def apply_theme(self, is_dark: bool) -> None:
        self._is_dark = is_dark
        self.portrait.apply_theme(is_dark)
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        d = gp.switcher_popover(self._is_dark)
        box = QRectF(self.rect())
        if self._current:
            p.setPen(Qt.NoPen)
            p.setBrush(d["row_current"])
            p.drawRoundedRect(box, 8, 8)
        elif self.underMouse():
            p.setPen(Qt.NoPen)
            p.setBrush(d["row_hover"])
            p.drawRoundedRect(box, 8, 8)
        left = ROW_PAD + ROW_PORTRAIT + ROW_GAP
        right = self.width() - ROW_PAD - (14 + ROW_GAP if self._current else 0)
        font = self.font()
        font.setPixelSize(12)
        font.setBold(True)
        p.setFont(font)
        p.setPen(d["name"])
        name_box = QRect(left, ROW_PAD, right - left, 16)
        p.drawText(name_box, Qt.AlignLeft | Qt.AlignVCenter,
                   p.fontMetrics().elidedText(self.toon, Qt.ElideRight, name_box.width()))
        font.setPixelSize(10)
        font.setBold(False)
        p.setFont(font)
        p.setPen(d["meta"])
        meta_box = QRect(left, ROW_PAD + 16, right - left, 14)
        p.drawText(meta_box, Qt.AlignLeft | Qt.AlignVCenter,
                   p.fontMetrics().elidedText(self.meta, Qt.ElideRight, meta_box.width()))
        if self._current:
            check = make_check_icon(14, d["check"]).pixmap(14, 14)
            p.drawPixmap(self.width() - ROW_PAD - 14, (self.height() - 14) // 2, check)
        _focus_ring(p, self, box.adjusted(1, 1, -1, -1), 8, self._is_dark)
        p.end()


# Copy, verbatim from handoff §4.3 (em-dashes replaced: no em-dash reaches
# the user in this app).
SWITCHER_NOTE = ("Whichever toon is shown here is what this account shows "
                 "everywhere in the launcher: stage, cards and Multitoon.")
SWITCHER_WARN = "Switching discards the unsaved changes to {toon}'s look."
SWITCHER_EMPTY = ("No toons discovered yet. Launch this account once and play "
                  "a toon. The launcher records who you played and this list "
                  "fills itself in.")


# With an Accounts sheet (launchpad handoff, section 5): the switcher only
# re-targets the editor, and says so.
SWITCHER_NOTE_RETARGET = ("Pick a toon to edit its look. The primary toon is "
                          "set with the star in Accounts.")
SWITCHER_SLOTS = 6


def switcher_heading(count: int, account_name: str, of_slots: bool = False) -> str:
    if count == 0:
        return f"Toons on {account_name}"
    if of_slots:
        return f"{min(count, SWITCHER_SLOTS)} of {SWITCHER_SLOTS} toons on {account_name}"
    return f"{count} toon{'' if count == 1 else 's'} on {account_name}"


class ToonSwitcher(QFrame):
    """`.subjpop`: every toon the account has been seen playing. Built when
    it opens, so the discard warning is current (handoff §4.3)."""

    toon_picked = Signal(str)

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("gs_subj_pop")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedWidth(SWITCHER_W)
        self._is_dark = True
        self._warning = False
        self._heading = ""
        self._anchor: Optional[QWidget] = None
        self._rows: list[ToonRow] = []
        col = QVBoxLayout(self)
        col.setContentsMargins(SWITCHER_PAD, SWITCHER_PAD, SWITCHER_PAD, SWITCHER_PAD)
        col.setSpacing(0)
        self.heading = QLabel(self)
        self.heading.setContentsMargins(5, 2, 5, 7)
        col.addWidget(self.heading)
        self._rows_box = QVBoxLayout()
        self._rows_box.setContentsMargins(0, 0, 0, 0)
        self._rows_box.setSpacing(0)
        col.addLayout(self._rows_box)
        self.note = QLabel(self)
        self.note.setWordWrap(True)
        self.note.setContentsMargins(5, 7, 5, 2)
        col.addWidget(self.note)
        self.hide()
        self.apply_theme(True)

    def rows(self) -> list[ToonRow]:
        return list(self._rows)

    def row_for(self, toon: str) -> Optional[ToonRow]:
        return next((r for r in self._rows if r.toon == toon), None)

    def anchor(self) -> Optional[QWidget]:
        return self._anchor

    def heading_text(self) -> str:
        return self._heading

    def note_text(self) -> str:
        return self.note.text()

    def is_warning(self) -> bool:
        return self._warning

    def set_retarget_only(self, retarget_only: bool) -> None:
        """Picking a toon edits that toon's look and changes nothing else."""
        self._retarget_only = bool(retarget_only)

    def open_for(self, anchor: QWidget, game: str, account_name: str,
                 toons: list, current: Optional[str], dirty: bool) -> None:
        self._anchor = anchor
        retarget = getattr(self, "_retarget_only", False)
        for row in self._rows:
            self._rows_box.removeWidget(row)
            row.setParent(None)
            row.deleteLater()
        self._rows = []
        for rec in toons:
            row = ToonRow(game, rec, rec.toon_name == current, self)
            if retarget:
                row.setToolTip(f"{rec.toon_name}'s look is open"
                               if rec.toon_name == current
                               else f"Edit {rec.toon_name}'s look")
            row.clicked.connect(self._on_row_clicked)
            row.apply_theme(self._is_dark)
            self._rows_box.addWidget(row)
            self._rows.append(row)
        self._heading = switcher_heading(len(toons), account_name, of_slots=retarget)
        self.heading.setText(self._heading.upper())
        self._warning = bool(toons) and dirty and bool(current)
        if not toons:
            self.note.setText(SWITCHER_EMPTY)
        elif self._warning:
            self.note.setText(SWITCHER_WARN.format(toon=current))
        else:
            self.note.setText(SWITCHER_NOTE_RETARGET if retarget else SWITCHER_NOTE)
        self._restyle_note()
        self.layout().activate()
        height = self.layout().totalHeightForWidth(SWITCHER_W)
        self.setFixedHeight(height if height > 0 else self.sizeHint().height())
        host = self.parentWidget()
        origin = anchor.mapTo(host, QPoint(0, 0))
        self.move(max(0, min(origin.x(), host.width() - self.width())),
                  max(0, min(origin.y() + SWITCHER_TOP,
                             host.height() - self.height())))
        self.show()
        self.raise_()

    def close_popover(self) -> None:
        self._anchor = None
        self.hide()

    def refresh_portraits(self) -> None:
        for row in self._rows:
            row.portrait.refresh()

    def _on_row_clicked(self) -> None:
        row = self.sender()
        if isinstance(row, ToonRow) and not row.is_current():
            self.toon_picked.emit(row.toon)

    def _restyle_note(self) -> None:
        d = gp.switcher_popover(self._is_dark)
        ink = d["warn"] if self._warning else d["note"]
        self.note.setStyleSheet(
            f"color: {ink.name()}; font-size: 10px; background: transparent;")

    def apply_theme(self, is_dark: bool) -> None:
        self._is_dark = is_dark
        d = gp.switcher_popover(is_dark)
        self.setStyleSheet(
            f"QFrame#gs_subj_pop {{ background: {d['bg'].name()};"
            f" border: 1px solid {d['border'].name()};"
            f" border-radius: {SWITCHER_RADIUS}px; }}")
        self.heading.setStyleSheet(
            f"color: {d['heading'].name()}; font-size: 10px; font-weight: 800;"
            " letter-spacing: 0.7px; background: transparent;")
        self._restyle_note()
        _shadow(self, d["shadow"], 34, 18)
        for row in self._rows:
            row.apply_theme(is_dark)


# ── portrait art (species mode) ─────────────────────────────────────────────

class _RaceIcon(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(STANDIN_ICON, STANDIN_ICON)
        self._species: Optional[str] = None
        self._is_dark = True

    def set_species(self, species: Optional[str]) -> None:
        self._species = species
        self.update()

    def apply_theme(self, is_dark: bool) -> None:
        self._is_dark = is_dark
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setOpacity(0.85)
        paint_race_silhouette(p, self.rect(), self._species,
                              gp.standin(self._is_dark)["icon"].name())
        p.end()


class StandIn(QFrame):
    """`.standin`: what the portrait *is* when a game has no render service
    (handoff §4.6 `species`)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("gs_standin")
        row = QHBoxLayout(self)
        row.setContentsMargins(12, 9, 12, 9)
        row.setSpacing(12)
        self.icon = _RaceIcon(self)
        row.addWidget(self.icon, 0, Qt.AlignVCenter)
        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(3)
        self.title = QLabel(self)
        self.body = QLabel(self)
        self.body.setWordWrap(True)
        col.addWidget(self.title)
        col.addWidget(self.body)
        row.addLayout(col, 1)

    def set_copy(self, species: Optional[str], title: str, body: str) -> None:
        self.icon.set_species(species)
        self.icon.setVisible(
            cc_race_assets.asset_stem_for_species(species) is not None)
        self.title.setText(title)
        self.body.setText(body)

    def apply_theme(self, is_dark: bool) -> None:
        d = gp.standin(is_dark)
        self.setStyleSheet(
            f"QFrame#gs_standin {{ background: {d['bg'].name()};"
            f" border: 1px solid {d['border'].name()}; border-radius: 9px; }}")
        self.title.setStyleSheet(
            f"color: {d['title'].name()}; font-size: 11px; font-weight: 800;"
            " background: transparent;")
        self.body.setStyleSheet(
            f"color: {d['body'].name()}; font-size: 11px; background: transparent;")
        self.icon.apply_theme(is_dark)
