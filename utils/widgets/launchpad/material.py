"""Sheet material for the launchpad window (handoff section 2).

What is reused from the shipped Settings v2 kit, and how:

- InsetRow   -> SheetRow subclasses it. Same API (set_control, add_control,
                set_full_width_control, set_row_disabled), so rows built for
                the Settings page can be dropped into a sheet. Overrides the
                metrics (min-height 46, padding 7/12, radius 8) and the type
                (12.5/700 title, 10.5 description).
- Switch     -> SheetToggle subclasses it with the 34 x 20 track, 14 px knob
                and no on-glow.
- SegmentedPill -> SheetSegmented subclasses it (track padding 2, options
                h 22, 11/600, any fill colour) through the class attributes
                and hooks pill_controls now exposes.
- CardSurface is NOT reused: radius, border width, gradient direction, glow
                and header anatomy all differ, so GroupCard paints its own.

Dark values are the handoff's; light values come from the theme tokens
(theme_manager.get_theme_colors / get_v2_tokens) because the handoff only
mocks dark. Colour mixing goes through utils.strips.tokens.
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QSizePolicy, QToolButton, QVBoxLayout, QWidget,
)

from utils.color_math import alpha
from utils.shared_widgets import Switch
from utils.strips.tokens import mix, tr
from utils.theme_manager import get_theme_colors, get_v2_tokens
from utils.widgets.inset_row import InsetRow, _scale_alpha
from utils.widgets.pill_controls import SegmentedPill
from utils.widgets.portrait_badge import _qcolor_from_rgba

GROUP_RADIUS = 14
GROUP_PAD = 12
GROUP_GAP = 8
# Every block a sheet stacks (cards, notes, footers) carries GLOW_PAD on each
# side: the room a group card's painted glow needs. The sheet host pads its
# body by that much less, and stacks blocks STACK_SPACING apart, so visible
# edges land where the handoff puts them (16 px in, 12 px apart).
GLOW_PAD = 6
BLOCK_GAP = 12
STACK_SPACING = BLOCK_GAP - 2 * GLOW_PAD
HEAD_DISC = 30
HEAD_GLYPH = 15
ROW_RADIUS = 8
ROW_MIN_H = 46
ICON_BTN = 28
ICON_BTN_GLYPH = 14
BUTTON_RADIUS = 8       # --radius-button
DARK_CARD_BASE = "#141414"


def sheet_palette(is_dark: bool) -> dict:
    """Every colour the sheet material uses, for one theme. QSS strings."""
    c = get_theme_colors(is_dark)
    v = get_v2_tokens(is_dark)
    if is_dark:
        return {
            "bg_app": c["bg_app"], "bg_deep": c["sidebar_bg"],
            "bg_card": c["bg_card"], "border_card": c["border_card"],
            "border_muted": c["border_muted"], "border_light": c["border_light"],
            "text": c["text_primary"], "text_secondary": c["text_secondary"],
            "text_muted": c["text_muted"], "text_disabled": c["text_disabled"],
            "row_bg": alpha("#000000", 0.30), "row_border": alpha("#ffffff", 0.05),
            "row_title": "#ffffff", "row_desc": alpha("#ffffff", 0.58),
            "meta": alpha("#ffffff", 0.62),
            "toggle_off": alpha("#000000", 0.50),
            "toggle_off_border": alpha("#ffffff", 0.16),
            "seg_track": alpha("#000000", 0.50), "seg_border": alpha("#ffffff", 0.09),
            "seg_idle": alpha("#ffffff", 0.62),
            "icon_btn_border": alpha("#ffffff", 0.12),
            "icon_btn_hover": alpha("#ffffff", 0.08),
            "icon_btn_on": alpha("#ffffff", 0.14),
            "close_hover": alpha("#ffffff", 0.07),
            "scrim": alpha("#0a0a0a", 0.55),
            "shadow": alpha("#000000", 0.50),
        }
    return {
        "bg_app": c["bg_app"], "bg_deep": c["sidebar_bg"],
        "bg_card": c["bg_card"], "border_card": c["border_card"],
        "border_muted": c["border_muted"], "border_light": c["border_light"],
        "text": c["text_primary"], "text_secondary": c["text_secondary"],
        "text_muted": c["text_muted"], "text_disabled": c["text_disabled"],
        "row_bg": v["row_bg"], "row_border": v["row_border"],
        "row_title": v["label"], "row_desc": v["helper"],
        "meta": v["sub"],
        "toggle_off": v["sw_off"], "toggle_off_border": v["sw_off_border"],
        "seg_track": v["seg_bg"], "seg_border": v["seg_border"],
        "seg_idle": v["seg_idle"],
        "icon_btn_border": alpha("#0f172a", 0.14),
        "icon_btn_hover": alpha("#0f172a", 0.06),
        "icon_btn_on": alpha("#0f172a", 0.10),
        "close_hover": alpha("#0f172a", 0.06),
        "scrim": alpha("#0f172a", 0.30),
        "shadow": alpha("#0f172a", 0.22),
    }


def qcolor(qss: str) -> QColor:
    return _qcolor_from_rgba(qss)


def _paint_glow(p: QPainter, path: QPainterPath, color: QColor, spread: float) -> None:
    """Layered strokes fading outwards: a painted stand-in for a CSS
    `0 0 <2*spread>px` glow (QGraphicsEffects conflict with custom painting
    in this codebase)."""
    steps = 6
    p.setBrush(Qt.NoBrush)
    for i in range(steps, 0, -1):
        frac = i / steps
        col = QColor(color)
        col.setAlphaF(color.alphaF() * (1.0 - frac) ** 2)
        pen = QPen(col, spread * 2 * frac)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        p.drawPath(path)


def _label(size_px: float, weight: int, color: str, parent=None) -> QLabel:
    lbl = QLabel(parent)
    _style_label(lbl, size_px, weight, color)
    return lbl


def _style_label(lbl: QLabel, size_px: float, weight: int, color: str) -> None:
    # The size lives in the widget's own stylesheet: the app stylesheet's
    # `QWidget { font-size: 12pt }` beats setFont().
    lbl.setStyleSheet(
        f"QLabel {{ font-size: {size_px}px; font-weight: {weight}; color: {color};"
        " background: transparent; border: none; }")


# ── Group card ──────────────────────────────────────────────────────────────

class _HeadDisc(QWidget):
    """30 px disc filled with the card colour, carrying a 15 px white glyph;
    or, given a logo, the 30 px logo on no disc (the handoff's .gico.logo)."""

    def __init__(self, color: str, glyph: QIcon | None, parent=None, logo=None):
        super().__init__(parent)
        self._color = color
        self._glyph = glyph
        self._logo = logo
        self.setFixedSize(HEAD_DISC, HEAD_DISC)

    def set_color(self, color: str) -> None:
        self._color = color
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        if self._logo is not None and not self._logo.isNull():
            scaled = self._logo.scaled(HEAD_DISC, HEAD_DISC, Qt.KeepAspectRatio,
                                       Qt.SmoothTransformation)
            p.drawPixmap((HEAD_DISC - scaled.width()) // 2,
                         (HEAD_DISC - scaled.height()) // 2, scaled)
            p.end()
            return
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(self._color))
        p.drawEllipse(QRectF(0, 0, HEAD_DISC, HEAD_DISC))
        if self._glyph is not None and not self._glyph.isNull():
            off = (HEAD_DISC - HEAD_GLYPH) // 2
            self._glyph.paint(p, off, off, HEAD_GLYPH, HEAD_GLYPH)
        p.end()


class GroupCard(QFrame):
    """Identity-tinted group card: radius 14, padding 12, 8 px between
    children, 1 px border in the colour at 55 %, a 16 px glow at 16 %, and a
    header of disc + title + optional right-aligned meta (text or widget)."""

    def __init__(self, color: str, title: str, glyph: QIcon | None = None,
                 meta: str | None = None, is_dark: bool = True, parent=None,
                 logo=None):
        super().__init__(parent)
        self._color = color
        self._is_dark = is_dark
        self._pal = sheet_palette(is_dark)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet("GroupCard { background: transparent; border: none; }")
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)

        outer = QVBoxLayout(self)
        m = GLOW_PAD + GROUP_PAD
        outer.setContentsMargins(m, m, m, m)
        outer.setSpacing(GROUP_GAP)

        head = QWidget(self)
        head.setStyleSheet("background: transparent;")
        head.setMinimumHeight(HEAD_DISC)
        hl = QHBoxLayout(head)
        hl.setContentsMargins(2, 0, 2, 2)
        hl.setSpacing(10)
        self.disc = _HeadDisc(color, glyph, head, logo=logo)
        hl.addWidget(self.disc)
        self.title_label = _label(15, 700, self._pal["text"], head)
        self.title_label.setText(title)
        hl.addWidget(self.title_label)
        hl.addStretch(1)
        self.meta_label = _label(11, 400, self._pal["meta"], head)
        self.meta_label.setVisible(bool(meta))
        if meta:
            self.meta_label.setText(meta)
        hl.addWidget(self.meta_label)
        self._meta_slot = hl
        outer.addWidget(head)
        self._head = head

        self._body = QWidget(self)
        self._body.setStyleSheet("background: transparent;")
        self._body_layout = QVBoxLayout(self._body)
        self._body_layout.setContentsMargins(0, 0, 0, 0)
        self._body_layout.setSpacing(GROUP_GAP)
        outer.addWidget(self._body)

    # API shared with CardSurface so Settings rows move over unchanged.
    def add_row(self, widget: QWidget, stretch: int = 0) -> None:
        widget.setParent(self._body)
        self._body_layout.addWidget(widget, stretch)

    def insert_row(self, index: int, widget: QWidget) -> None:
        widget.setParent(self._body)
        self._body_layout.insertWidget(index, widget)

    def remove_row(self, widget: QWidget) -> None:
        self._body_layout.removeWidget(widget)

    def rows(self) -> list:
        out = []
        for i in range(self._body_layout.count()):
            w = self._body_layout.itemAt(i).widget()
            if w is not None:
                out.append(w)
        return out

    def set_title(self, text: str) -> None:
        self.title_label.setText(text)

    def set_meta(self, text: str | None) -> None:
        self.meta_label.setText(text or "")
        self.meta_label.setVisible(bool(text))

    def add_meta_widget(self, widget: QWidget) -> None:
        """A control in the header's right end (e.g. the TTR | CC pill)."""
        widget.setParent(self._head)
        self._meta_slot.addWidget(widget)

    def color(self) -> str:
        return self._color

    def set_color(self, color: str) -> None:
        self._color = color
        self.disc.set_color(color)
        self.update()

    def apply_theme(self, is_dark: bool) -> None:
        self._is_dark = is_dark
        self._pal = sheet_palette(is_dark)
        _style_label(self.title_label, 15, 700, self._pal["text"])
        _style_label(self.meta_label, 11, 400, self._pal["meta"])
        self.update()

    def _colors(self):
        c = self._color
        if self._is_dark:
            return (QColor(mix(c, 20, DARK_CARD_BASE)), QColor(mix(c, 9, DARK_CARD_BASE)),
                    tr(c, 55), tr(c, 16))
        return (QColor(mix(c, 14, "#ffffff")), QColor(mix(c, 6, "#ffffff")),
                tr(c, 50), tr(c, 10))

    def paintEvent(self, _e):
        if self.width() <= 2 * GLOW_PAD or self.height() <= 2 * GLOW_PAD:
            return
        top, bottom, border, glow = self._colors()
        r = QRectF(self.rect()).adjusted(GLOW_PAD, GLOW_PAD, -GLOW_PAD, -GLOW_PAD)
        path = QPainterPath()
        path.addRoundedRect(r, GROUP_RADIUS, GROUP_RADIUS)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        _paint_glow(p, path, glow, GLOW_PAD)
        grad = QLinearGradient(r.topLeft(), r.bottomLeft())
        grad.setColorAt(0.0, top)
        grad.setColorAt(1.0, bottom)
        p.fillPath(path, grad)
        inner = QPainterPath()
        inner.addRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5),
                             GROUP_RADIUS - 0.5, GROUP_RADIUS - 0.5)
        p.setPen(QPen(border, 1))
        p.setBrush(Qt.NoBrush)
        p.drawPath(inner)
        p.end()


class PlainCard(QFrame):
    """Neutral card for plain actions: bg-card fill, border-card, no glow.
    Same padding and spacing as GroupCard, and the same GLOW_PAD margin so
    the two line up when stacked."""

    def __init__(self, is_dark: bool = True, parent=None):
        super().__init__(parent)
        self.setObjectName("plain_card")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(GLOW_PAD, GLOW_PAD, GLOW_PAD, GLOW_PAD)
        outer.setSpacing(0)
        self._inner = QFrame(self)
        self._inner.setObjectName("plain_card_inner")
        self._inner.setAttribute(Qt.WA_StyledBackground, True)
        self._body_layout = QVBoxLayout(self._inner)
        self._body_layout.setContentsMargins(GROUP_PAD, GROUP_PAD, GROUP_PAD, GROUP_PAD)
        self._body_layout.setSpacing(GROUP_GAP)
        outer.addWidget(self._inner)
        self.apply_theme(is_dark)

    def add_row(self, widget: QWidget, stretch: int = 0) -> None:
        widget.setParent(self._inner)
        self._body_layout.addWidget(widget, stretch)

    def apply_theme(self, is_dark: bool) -> None:
        pal = sheet_palette(is_dark)
        self.setStyleSheet(
            "QFrame#plain_card { background: transparent; border: none; }"
            f"QFrame#plain_card_inner {{ background: {pal['bg_card']};"
            f" border: 1px solid {pal['border_card']}; border-radius: {GROUP_RADIUS}px; }}")


# ── Inset row ───────────────────────────────────────────────────────────────

class SheetRow(InsetRow):
    """InsetRow at the sheet's metrics: min-height 46, padding 7/12, radius 8,
    11 px gap, title 12.5/700, description 10.5 px."""

    def __init__(self, label: str, helper: str | None = None,
                 is_dark: bool = True, parent=None):
        super().__init__(label, helper, parent)
        self.setObjectName("sheet_row")
        self.layout().setContentsMargins(12, 7, 12, 7)
        self.layout().setSpacing(7)
        top = self.layout().itemAt(0).layout()
        if top is not None:
            top.setSpacing(11)
        self.setMinimumHeight(ROW_MIN_H)
        self._is_dark = is_dark
        self.apply_theme(is_dark)

    def apply_theme(self, is_dark: bool) -> None:
        self._is_dark = is_dark
        self._t = get_v2_tokens(is_dark)
        self._pal = sheet_palette(is_dark)
        self.setStyleSheet(
            "QFrame#sheet_row {"
            f" background: {self._pal['row_bg']};"
            f" border: 1px solid {self._pal['row_border']};"
            f" border-radius: {ROW_RADIUS}px; }}")
        self._style_text()

    def _style_text(self) -> None:
        pal = getattr(self, "_pal", None) or sheet_palette(True)
        factor = 1.0 - 0.5 * self._dim
        self.label_widget.setStyleSheet(
            f"font-size: 12.5px; font-weight: 700;"
            f" color: {_scale_alpha(pal['row_title'], factor)};"
            " background: transparent; border: none;")
        if self.helper_widget is not None:
            self.helper_widget.setStyleSheet(
                f"font-size: 10.5px; color: {_scale_alpha(pal['row_desc'], factor)};"
                " background: transparent; border: none;")


# ── Toggle ──────────────────────────────────────────────────────────────────

class SheetToggle(Switch):
    """34 x 20 track, 14 px white knob, no on-glow. On: the row's accent."""

    TRACK_W = 34
    TRACK_H = 20
    THUMB_D = 14
    PADDING = 3
    HALO = 0

    def __init__(self, checked: bool = False, accent: str = "#0077ff",
                 is_dark: bool = True, parent=None):
        super().__init__(checked, parent)
        self.set_accent(accent, accent)
        self.apply_theme(is_dark)

    def apply_theme(self, is_dark: bool) -> None:
        pal = sheet_palette(is_dark)
        self._track_off = qcolor(pal["toggle_off"]).name(QColor.HexArgb)
        self._border_off = qcolor(pal["toggle_off_border"]).name(QColor.HexArgb)
        self._thumb_color = "#ffffff"
        self.update()


# ── Segmented pill ─────────────────────────────────────────────────────────

class SheetSegmented(SegmentedPill):
    """Track padding 2, options h 22 with 12 px side padding, 11/600 text,
    selected option filled with any colour."""

    PAD = 2
    GAP = 0
    SEG_PAD_X = 12
    H = 22 + 2 * 2 + 2       # options + padding + 1 px border each side
    FONT_PX = 11

    def __init__(self, options: list[str], accent: str = "#0077ff",
                 is_dark: bool = True, parent=None, stretch: bool = False):
        super().__init__(options, stretch=stretch, parent=parent)
        self.set_fill(accent)
        self.apply_sheet_theme(is_dark)

    def apply_sheet_theme(self, is_dark: bool) -> None:
        self._pal = sheet_palette(is_dark)
        self._t = get_v2_tokens(is_dark)
        self.update()

    def _font(self, selected: bool):
        f = super()._font(selected)
        from PySide6.QtGui import QFont
        f.setWeight(QFont.DemiBold)
        return f

    def _track_colors(self):
        pal = getattr(self, "_pal", None) or sheet_palette(True)
        return qcolor(pal["seg_track"]), qcolor(pal["seg_border"])

    def _idle_text_color(self):
        pal = getattr(self, "_pal", None) or sheet_palette(True)
        return qcolor(pal["seg_idle"])

    def _seg_rects(self):
        # Shift past the 1 px border so options sit 2 px inside the track.
        return [QRectF(r.x() + 1, r.y() + 1, r.width(), r.height() - 2)
                for r in super()._seg_rects()]

    def sizeHint(self):
        hint = super().sizeHint()
        return QSize(hint.width() + 2, self.H)


# ── Buttons ─────────────────────────────────────────────────────────────────

class IconButton(QToolButton):
    """28 px square icon button: border 1px, radius 8, transparent fill.
    `danger` turns red on hover. `on` marks an active toggle (fill 14 %)."""

    def __init__(self, icon: QIcon, tooltip: str, danger: bool = False,
                 is_dark: bool = True, parent=None):
        super().__init__(parent)
        self._danger = danger
        self._on = False
        self.setIcon(with_disabled_state(icon, ICON_BTN_GLYPH))
        self.setIconSize(QSize(ICON_BTN_GLYPH, ICON_BTN_GLYPH))
        self.setFixedSize(ICON_BTN, ICON_BTN)
        self.setToolTip(tooltip)
        self.setAccessibleName(tooltip)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.TabFocus)
        self.apply_theme(is_dark)

    def set_on(self, on: bool) -> None:
        self._on = bool(on)
        self.apply_theme(self._is_dark)

    def apply_theme(self, is_dark: bool) -> None:
        self._is_dark = is_dark
        pal = sheet_palette(is_dark)
        base_bg = pal["icon_btn_on"] if self._on else "transparent"
        hover_bg = alpha("#e05252", 0.16) if self._danger else pal["icon_btn_hover"]
        hover_border = "#e05252" if self._danger else pal["border_light"]
        self.setStyleSheet(
            "QToolButton {"
            f" background: {base_bg}; border: 1px solid {pal['icon_btn_border']};"
            f" border-radius: {BUTTON_RADIUS}px; padding: 0; }}"
            f"QToolButton:hover {{ background: {hover_bg}; border-color: {hover_border}; }}"
            f"QToolButton:disabled {{ background: transparent;"
            f" border-color: {_scale_alpha(pal['icon_btn_border'], 0.35)}; }}")

    def setIcon(self, icon: QIcon) -> None:  # noqa: N802 (Qt name)
        super().setIcon(with_disabled_state(icon, ICON_BTN_GLYPH))


class AddRow(QToolButton):
    """Dashed 42 px row button ("+ New keyset", "+ Add account").
    Disabled at 45 % opacity."""

    def __init__(self, text: str, icon: QIcon | None = None, is_dark: bool = True,
                 parent=None):
        super().__init__(parent)
        self.setText(text)
        if icon is not None:
            self.setIcon(icon)
            self.setIconSize(QSize(14, 14))
        self.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.setFixedHeight(42)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setCursor(Qt.PointingHandCursor)
        self.apply_theme(is_dark)

    def apply_theme(self, is_dark: bool) -> None:
        pal = sheet_palette(is_dark)
        hover_text = "#ffffff" if is_dark else pal["text"]
        self.setStyleSheet(
            "QToolButton {"
            f" background: transparent; border: 1px dashed {pal['border_light']};"
            f" border-radius: {ROW_RADIUS}px; color: {pal['text_muted']};"
            " font-size: 12px; font-weight: 600; padding: 0 12px; }"
            f"QToolButton:hover {{ color: {hover_text}; border-color: #3399ff;"
            f" background: {alpha('#0077ff', 0.07)}; }}"
            f"QToolButton:disabled {{ color: {alpha(pal['text_muted'], 0.45)};"
            f" border-color: {alpha(pal['border_light'], 0.45)}; }}")


class SecondaryButton(QToolButton):
    """Small secondary text button: h 26, padding 0 11, radius 999,
    bg-card fill, border-card outline, 11/600 text-secondary."""

    def __init__(self, text: str, is_dark: bool = True, parent=None):
        super().__init__(parent)
        self.setText(text)
        self.setFixedHeight(26)
        self.setCursor(Qt.PointingHandCursor)
        self.apply_theme(is_dark)

    def apply_theme(self, is_dark: bool) -> None:
        pal = sheet_palette(is_dark)
        hover_text = "#ffffff" if is_dark else pal["text"]
        self.setStyleSheet(
            "QToolButton {"
            f" background: {pal['bg_card']}; border: 1px solid {pal['border_card']};"
            f" border-radius: 13px; color: {pal['text_secondary']};"
            " font-size: 11px; font-weight: 600; padding: 0 11px; }"
            f"QToolButton:hover {{ color: {hover_text}; border-color: {pal['border_light']}; }}")


def with_disabled_state(icon: QIcon, size: int) -> QIcon:
    """The icon plus an explicit Disabled pixmap at 35 % opacity (the
    handoff's disabled icon button), instead of the style's grey-out."""
    from PySide6.QtGui import QPixmap
    if icon is None or icon.isNull():
        return icon
    src = icon.pixmap(size, size)
    dim = QPixmap(src.size())
    dim.setDevicePixelRatio(src.devicePixelRatio())
    dim.fill(Qt.transparent)
    p = QPainter(dim)
    p.setOpacity(0.35)
    p.drawPixmap(0, 0, src)
    p.end()
    out = QIcon(src)
    out.addPixmap(dim, QIcon.Disabled)
    return out


def sheet_stack(widget: QWidget) -> QVBoxLayout:
    """The layout a sheet's content uses to stack its blocks."""
    lay = QVBoxLayout(widget)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(STACK_SPACING)
    return lay


def note_label(text: str, is_dark: bool = True, parent=None) -> QLabel:
    """A group card's note line (11 px, white at 62 % / theme sub colour).
    Goes inside a card, so it carries no GLOW_PAD."""
    lbl = _label(11, 400, sheet_palette(is_dark)["meta"], parent)
    lbl.setText(text)
    lbl.setWordWrap(True)
    lbl.setContentsMargins(2, 0, 2, 0)
    return lbl


def footer_label(text: str, is_dark: bool = True, parent=None) -> QLabel:
    """Centred footer hint under a sheet's cards (11 px, text-disabled)."""
    lbl = _label(11, 400, sheet_palette(is_dark)["text_disabled"], parent)
    lbl.setText(text)
    lbl.setWordWrap(True)
    lbl.setAlignment(Qt.AlignHCenter)
    lbl.setContentsMargins(GLOW_PAD, GLOW_PAD, GLOW_PAD, GLOW_PAD)
    return lbl
