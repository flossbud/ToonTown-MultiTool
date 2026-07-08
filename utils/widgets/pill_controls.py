"""v2 pill controls: PillButton, SegmentedPill, DropdownPill, ChordPill,
GhostExpander. All 30px tall, radius = height/2 (the '999' pills in the
design). Colors from theme_manager.get_v2_tokens + V2_ACCENTS.

Known approximation (documented in the design doc): the danger button's
outer glow (`0 0 14px rgba(224,82,82,0.35)`) is omitted - pill buttons sit
inside 10px-padded inset rows with no halo margin budget; revisit in the
polish task if it reads flat live.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QPushButton, QSizePolicy, QWidget

from utils.hotkey_capture import ChordCaptureButton
from utils.shared_widgets import SettingsComboBox
from utils.theme_manager import V2_ACCENTS, get_v2_tokens

PILL_H = 30


class PillButton(QPushButton):
    """Neutral or danger pill button (height 30, radius 15, 12.5px/700)."""

    def __init__(self, text: str, tone: str = "neutral", parent=None):
        super().__init__(text, parent)
        assert tone in ("neutral", "danger")
        self._tone = tone
        self.setFixedHeight(PILL_H)
        self.setCursor(Qt.PointingHandCursor)

    def apply_theme(self, is_dark: bool) -> None:
        t = get_v2_tokens(is_dark)
        if self._tone == "danger":
            self.setStyleSheet(
                "QPushButton {"
                " background: #e05252; border: 1px solid #f28b8b; color: #ffffff;"
                f" border-radius: {PILL_H // 2}px; padding: 0 15px;"
                " font-size: 12.5px; font-weight: 700; }"
                "QPushButton:hover { background: #f06060; }")
        else:
            self.setStyleSheet(
                "QPushButton {"
                f" background: {t['btn_bg']}; border: 1px solid {t['btn_border']};"
                f" color: {t['ctrl_text']}; border-radius: {PILL_H // 2}px;"
                " padding: 0 15px; font-size: 12.5px; font-weight: 700; }"
                f"QPushButton:hover {{ background: {t['ctrl_hover']}; }}")


class SegmentedPill(QWidget):
    """Segmented pill (container padding 3, gap 2, radius = h/2). Selected
    segment fills with the accent c; setCurrentIndex is silent, clicks emit
    index_changed - the IOSSegmentedControl contract."""

    index_changed = Signal(int)
    PAD = 3
    GAP = 2
    SEG_PAD_X = 13

    def __init__(self, options: list[str], stretch: bool = False, parent=None):
        super().__init__(parent)
        self._options = list(options)
        self._index = 0
        self._stretch = bool(stretch)
        self._t = get_v2_tokens(True)
        self._fill = V2_ACCENTS["blue"]["c"]
        self.setFixedHeight(PILL_H)
        self.setCursor(Qt.PointingHandCursor)
        if stretch:
            self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        else:
            self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

    def currentIndex(self) -> int:
        return self._index

    def setCurrentIndex(self, idx: int) -> None:
        self._index = max(0, min(int(idx), len(self._options) - 1))
        self.update()

    def apply_theme(self, is_dark: bool, accent_key: str = "blue") -> None:
        self._t = get_v2_tokens(is_dark)
        a = V2_ACCENTS.get(accent_key, V2_ACCENTS["blue"])
        # Red cards flip to the bright variant so the fill stays readable
        # (same rule as the Switch on-color in the design).
        self._fill = a["b"] if accent_key == "red" else a["c"]
        self.update()

    def sizeHint(self):
        from PySide6.QtCore import QSize
        f = QFont()
        f.setPixelSize(12)
        f.setWeight(QFont.Bold)
        fm = QFontMetrics(f)
        w = 2 * self.PAD + self.GAP * (len(self._options) - 1) + sum(
            fm.horizontalAdvance(o) + 2 * self.SEG_PAD_X for o in self._options)
        return QSize(w, PILL_H)

    def _seg_rects(self):
        from PySide6.QtCore import QRectF
        inner_w = self.width() - 2 * self.PAD
        n = len(self._options)
        rects = []
        if self._stretch:
            seg_w = (inner_w - self.GAP * (n - 1)) / n
            x = float(self.PAD)
            for _ in self._options:
                rects.append(QRectF(x, self.PAD, seg_w, PILL_H - 2 * self.PAD))
                x += seg_w + self.GAP
        else:
            f = QFont()
            f.setPixelSize(12)
            f.setWeight(QFont.Bold)
            fm = QFontMetrics(f)
            x = float(self.PAD)
            for o in self._options:
                w = fm.horizontalAdvance(o) + 2 * self.SEG_PAD_X
                rects.append(QRectF(x, self.PAD, w, PILL_H - 2 * self.PAD))
                x += w + self.GAP
        return rects

    def mousePressEvent(self, e):
        if e.button() != Qt.LeftButton:
            return super().mousePressEvent(e)
        for i, r in enumerate(self._seg_rects()):
            if r.contains(e.position()):
                if i != self._index:
                    self._index = i
                    self.index_changed.emit(i)
                    self.update()
                e.accept()
                return
        e.accept()

    def paintEvent(self, e):
        from PySide6.QtCore import QRectF
        from utils.widgets.portrait_badge import _qcolor_from_rgba
        p = QPainter(self)
        if not self.isEnabled():
            # Disabled rows mute their controls (design: saturate+opacity);
            # painted colors don't follow setEnabled, so mute explicitly.
            p.setOpacity(0.45)
        p.setRenderHint(QPainter.Antialiasing, True)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        radius = r.height() / 2
        p.setPen(QPen(_qcolor_from_rgba(self._t["seg_border"]), 1))
        p.setBrush(_qcolor_from_rgba(self._t["seg_bg"]))
        p.drawRoundedRect(r, radius, radius)

        rects = self._seg_rects()
        for i, (opt, seg) in enumerate(zip(self._options, rects)):
            sel = i == self._index
            if sel:
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(self._fill))
                p.drawRoundedRect(seg, seg.height() / 2, seg.height() / 2)
            f = QFont()
            f.setPixelSize(12)
            f.setWeight(QFont.Bold if sel else QFont.Medium)
            p.setFont(f)
            p.setPen(QColor("#ffffff") if sel
                     else _qcolor_from_rgba(self._t["seg_idle"]))
            p.drawText(seg, Qt.AlignCenter, opt)
        p.end()


class DropdownPill(SettingsComboBox):
    """Pill-styled SettingsComboBox (keeps the current-value-dot delegate and
    painted chevron; the popup styling stays with the global QComboBox QSS)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(PILL_H)

    def apply_theme(self, is_dark: bool, accent: str = "#0077ff") -> None:
        t = get_v2_tokens(is_dark)
        self.set_theme_colors(accent=accent, is_dark=is_dark)
        self.setStyleSheet(
            "QComboBox {"
            f" background: {t['ctrl_bg']}; border: 1px solid {t['ctrl_border']};"
            f" color: {t['ctrl_text']}; border-radius: {PILL_H // 2}px;"
            " padding-left: 13px; font-size: 12.5px; font-weight: 600; }"
            "QComboBox::drop-down { width: 30px; border: none; background: transparent; }")


class ChordPill(ChordCaptureButton):
    """ChordCaptureButton in v2 pill clothes. Capture logic untouched; only
    the styling changes with bound/unbound state."""

    def __init__(self, chord_text, on_chord, parent=None, *, on_capture_end=None):
        super().__init__(chord_text, on_chord, parent, on_capture_end=on_capture_end)
        self._is_dark = True
        self.setFixedHeight(PILL_H)
        self.setMinimumWidth(92)
        self.setCursor(Qt.PointingHandCursor)
        self._restyle()

    def apply_theme(self, is_dark: bool) -> None:
        self._is_dark = is_dark
        self._restyle()

    def set_chord(self, chord_text) -> None:
        super().set_chord(chord_text)
        self._restyle()

    def _restyle(self) -> None:
        t = get_v2_tokens(self._is_dark)
        bound = self._chord_text is not None
        if bound:
            f = QFont()
            f.setFamilies(["Consolas", "Menlo", "DejaVu Sans Mono", "Liberation Mono", "monospace"])
            f.setStyleHint(QFont.Monospace)
            f.setPixelSize(11)
            self.setFont(f)
            border, color, size = t["chord_border"], t["ctrl_text"], "11.5px"
        else:
            self.setFont(QFont())
            border, color, size = t["chord_idle_border"], t["chord_idle"], "12px"
        self.setStyleSheet(
            "QPushButton {"
            f" background: {t['btn_bg']}; border: 1px solid {border};"
            f" color: {color}; border-radius: {PILL_H // 2}px;"
            f" padding: 0 13px; font-size: {size}; font-weight: 600; }}"
            f"QPushButton:hover {{ background: {t['ctrl_hover']}; }}")


class GhostExpander(QPushButton):
    """Self-centered dashed ghost pill ('Show N more...' / 'Show less')."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(28)
        self.setCursor(Qt.PointingHandCursor)

    def set_state(self, *, expanded: bool, more_count: int) -> None:
        self.setText("Show less" if expanded else f"Show {more_count} more...")

    def apply_theme(self, is_dark: bool) -> None:
        t = get_v2_tokens(is_dark)
        self.setStyleSheet(
            "QPushButton {"
            f" background: transparent; border: 1px dashed {t['more_border']};"
            f" color: {t['more_text']}; border-radius: 14px; padding: 0 16px;"
            " font-size: 12px; font-weight: 600; }"
            f"QPushButton:hover {{ background: {t['nav_hover']}; }}")
