"""
Shared custom widgets used across multiple tabs.

Switch              — Accent-blue pill toggle (Settings)
IOSSegmentedControl — iOS-style segmented control for small option sets
PulsingDot          — Animated status dot with optional breathing glow
Spinner             — Indeterminate rotating spinner, animates only while visible
SmoothProgressBar   — Sub-pixel precision progress bar with rounded pill shape
ElidingLabel        — QLabel that truncates long text with an ellipsis
"""
from __future__ import annotations

import math

from PySide6.QtWidgets import QWidget, QLabel, QSizePolicy, QStyledItemDelegate, QComboBox
from PySide6.QtCore import (
    Qt, Signal, QPropertyAnimation, QEasingCurve, QVariantAnimation,
    Property, QRectF, QSize, QTimer,
)
from PySide6.QtGui import QColor, QPainter, QPen, QFont, QRadialGradient, QFontMetrics


# ── Accent-blue Switch ───────────────────────────────────────────────────────

class Switch(QWidget):
    """Accent-blue pill toggle. Drop-in replacement for IOSToggle in Settings.

    Visually identical proportions to IOSToggle but uses the app's accent-blue
    palette for the on state (instead of iOS green) and exposes set_theme_colors
    so refresh_theme can re-tint both the track and the thumb for light/dark.
    """

    toggled = Signal(bool)

    TRACK_W = 38
    TRACK_H = 20
    THUMB_D = 16
    PADDING = 2

    def __init__(self, checked: bool = False, parent=None):
        super().__init__(parent)
        self._checked = bool(checked)
        self._thumb_x = float(
            self.PADDING if not self._checked
            else self.TRACK_W - self.THUMB_D - self.PADDING
        )
        self._track_on = "#0077ff"
        self._track_off = "#3a3a3a"
        self._thumb_color = "#ffffff"

        self.setFixedSize(self.TRACK_W, self.TRACK_H)
        self.setCursor(Qt.PointingHandCursor)

        self._anim = QPropertyAnimation(self, b"thumbX")
        self._anim.setDuration(180)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)

    # ── public API (mirrors IOSToggle) ──────────────────────────────────

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, value: bool) -> None:
        value = bool(value)
        if value == self._checked:
            return
        self._checked = value
        self._animate_to_state()
        self.toggled.emit(value)

    def set_theme_colors(self, *, track_on: str, track_off: str, thumb: str) -> None:
        self._track_on = track_on
        self._track_off = track_off
        self._thumb_color = thumb
        self.update()

    # ── animation property ──────────────────────────────────────────────

    def _get_thumb_x(self):
        return self._thumb_x

    def _set_thumb_x(self, val):
        self._thumb_x = float(val)
        self.update()

    thumbX = Property(float, _get_thumb_x, _set_thumb_x)

    def _animate_to_state(self) -> None:
        import utils.motion as motion
        target = (
            self.TRACK_W - self.THUMB_D - self.PADDING
            if self._checked else self.PADDING
        )
        if motion.is_reduced():
            self._thumb_x = float(target)
            self.update()
            return
        self._anim.stop()
        self._anim.setStartValue(self._thumb_x)
        self._anim.setEndValue(float(target))
        self._anim.start()

    # ── input ───────────────────────────────────────────────────────────

    def mousePressEvent(self, event):
        if not self.isEnabled():
            super().mousePressEvent(event)
            return
        if event.button() == Qt.LeftButton:
            self._checked = not self._checked
            self._animate_to_state()
            self.toggled.emit(self._checked)
            event.accept()
            return
        super().mousePressEvent(event)

    # ── paint ───────────────────────────────────────────────────────────

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        enabled = self.isEnabled()
        # Track
        track = QColor(self._track_on if self._checked else self._track_off)
        if not enabled:
            track.setAlphaF(0.4)
        p.setPen(Qt.NoPen)
        p.setBrush(track)
        radius = self.TRACK_H / 2
        p.drawRoundedRect(self.rect(), radius, radius)

        # Thumb
        thumb = QColor(self._thumb_color if enabled else "#cccccc")
        p.setBrush(thumb)
        p.drawEllipse(
            int(self._thumb_x), self.PADDING,
            self.THUMB_D, self.THUMB_D,
        )
        p.end()


# ── iOS Segmented Control ────────────────────────────────────────────────────

class IOSSegmentedControl(QWidget):
    """iOS-style segmented control for small option sets."""
    index_changed = Signal(int)

    def __init__(self, options: list, parent=None):
        super().__init__(parent)
        self._options = options
        self._index = 0
        self.setFixedHeight(32)
        self.setCursor(Qt.PointingHandCursor)

        self._anim_x_val = 0.0
        self._anim = QPropertyAnimation(self, b"_anim_x")
        self._anim.setDuration(150)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)

    @Property(float)
    def _anim_x(self):
        return self._anim_x_val

    @_anim_x.setter
    def _anim_x(self, val):
        self._anim_x_val = val
        self.update()

    def currentIndex(self):
        return self._index

    def setCurrentIndex(self, idx: int):
        self._index = max(0, min(idx, len(self._options) - 1))
        self.update()

    def mousePressEvent(self, e):
        w = self.width() / len(self._options)
        idx = int(e.position().x() / w)
        idx = max(0, min(idx, len(self._options) - 1))
        if idx != self._index:
            self._index = idx
            self.index_changed.emit(idx)
            self.update()

    def set_theme_colors(self, track_color: str, pill_color: str, active_text: str, inactive_text: str):
        """Set colors from theme."""
        self._track_color = track_color
        self._pill_color = pill_color
        self._active_text = active_text
        self._inactive_text = inactive_text
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        w = self.width()
        h = self.height()
        seg_w = w / len(self._options)
        r = 8.0

        # Track background
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(getattr(self, '_track_color', '#3a3a3a')))
        p.drawRoundedRect(QRectF(0, 0, w, h), r, r)

        # Selected pill
        sx = self._index * seg_w + 2
        p.setBrush(QColor(getattr(self, '_pill_color', '#636366')))
        p.drawRoundedRect(QRectF(sx, 2, seg_w - 4, h - 4), r - 2, r - 2)

        # Labels
        font = QFont()
        font.setPixelSize(12)
        font.setBold(False)
        p.setFont(font)

        for i, opt in enumerate(self._options):
            x = i * seg_w
            color = QColor(getattr(self, '_active_text', '#ffffff')) if i == self._index else QColor(getattr(self, '_inactive_text', '#888888'))
            p.setPen(color)
            p.drawText(QRectF(x, 0, seg_w, h), Qt.AlignCenter, opt)

        p.end()


# ── Pulsing Dot ──────────────────────────────────────────────────────────────

class PulsingDot(QWidget):
    """Animated status dot -- breathes with a soft glow when in 'active' state."""

    def __init__(self, size=10, parent=None):
        super().__init__(parent)
        self._dot_size = size
        # Extra space around the dot for the glow halo
        self.setFixedSize(size + 8, size + 8)
        from utils.theme_manager import is_dark_palette
        self._color = QColor("#555555" if is_dark_palette() else "#bbbbbb")
        self._pulse_val = 0.0
        self._pulsing = False

        # Optional "cut-out" ring painted just outside the core dot.
        # When set, gives the dot the look of being notched out of its
        # backdrop (used by the Multitoon compact portrait overlay).
        # None preserves the existing behaviour for other call sites.
        self._cutout_color: QColor | None = None
        self._cutout_width: float = 2.5

        self._anim = QVariantAnimation()
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setDuration(2800)
        self._anim.setLoopCount(-1)
        self._anim.setEasingCurve(QEasingCurve.Linear)
        self._anim.valueChanged.connect(self._on_pulse)

    def set_size(self, size: int) -> None:
        """Resize the core dot. The widget's fixed size is (size + 8) on
        each axis to keep an 8 px halo budget for the pulse glow. Used
        by the Multitoon mode switch to swap between compact (13) and
        full (24). Cancels nothing — any in-flight pulse animation
        keeps driving the new size."""
        if int(size) == self._dot_size:
            return
        self._dot_size = int(size)
        self.setFixedSize(self._dot_size + 8, self._dot_size + 8)
        self.update()

    def set_cutout_border(self, color: str | None, width: float = 2.5) -> None:
        """Paint a ring in `color` just outside the core dot. Use the
        backdrop colour (e.g. card background) to create a 'notched
        out' look when the dot overlays another widget. Pass None to
        disable the ring."""
        self._cutout_color = QColor(color) if color is not None else None
        self._cutout_width = float(width)
        self.update()

    def set_color(self, hex_color: str, pulse: bool = False):
        self._color = QColor(hex_color)
        if pulse:
            if not self._pulsing:
                self._pulsing = True
                self._anim.start()
        else:
            self._stop_pulse()
        self.update()

    def set_state(self, state: str, tooltip: str = ""):
        self.setToolTip(tooltip)
        if state == "active":
            self.set_color("#56c856", pulse=True)
        elif state == "keep_alive":
            self.set_color("#ff9900", pulse=True)
        elif state == "disabled":
            self.set_color("#e84141", pulse=False)
        elif state == "found":
            self.set_color("#888888", pulse=False)
        else:
            from utils.theme_manager import is_dark_palette
            self.set_color("#555555" if is_dark_palette() else "#bbbbbb", pulse=False)

    def _stop_pulse(self):
        if self._pulsing:
            self._pulsing = False
            self._anim.stop()
            self._pulse_val = 0.0

    def _on_pulse(self, val):
        # Map linear 0->1 through sin(pi*val) to get smooth 0->1->0 per cycle
        self._pulse_val = math.sin(val * math.pi)
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)

        cx = self.width() / 2.0
        cy = self.height() / 2.0
        r = self._dot_size / 2.0

        if self._pulsing:
            # Soft outer glow -- fades in/out with the pulse
            glow_alpha = int(60 * self._pulse_val)
            glow_r = r + 3 + 2 * self._pulse_val
            grad = QRadialGradient(cx, cy, glow_r)
            glow_color = QColor(self._color)
            glow_color.setAlpha(glow_alpha)
            grad.setColorAt(0.0, glow_color)
            glow_color.setAlpha(0)
            grad.setColorAt(1.0, glow_color)
            p.setBrush(grad)
            p.drawEllipse(QRectF(cx - glow_r, cy - glow_r, glow_r * 2, glow_r * 2))

            # Core dot -- gentle brightness shift (only ~18% lighter at peak)
            core = QColor(self._color).lighter(100 + int(18 * self._pulse_val))
        else:
            core = QColor(self._color)

        # Cut-out border: hard ring in backdrop colour. Drawn between
        # the glow and the core dot so the glow softly fades behind it.
        if self._cutout_color is not None:
            ring_r = r + self._cutout_width
            p.setBrush(self._cutout_color)
            p.drawEllipse(QRectF(cx - ring_r, cy - ring_r, ring_r * 2, ring_r * 2))

        p.setBrush(core)
        p.drawEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))
        p.end()


class Spinner(QWidget):
    """Indeterminate rotating spinner. Animates only while visible.

    Plain QPainter(self) in paintEvent driven by an integer rotation that a
    QTimer advances. No QGraphicsEffect anywhere on this widget -- combining a
    QGraphicsEffect with a custom QPainter(self) paintEvent triggers
    'A paint device can only be painted by one painter at a time'.
    """

    def __init__(self, size: int = 14, parent=None):
        super().__init__(parent)
        self._size = int(size)
        self.setFixedSize(self._size, self._size)
        self._angle = 0
        self._color = QColor("#8a9bb8")
        self._timer = QTimer(self)
        self._timer.setInterval(70)
        self._timer.timeout.connect(self._advance)

    def set_color(self, hex_color: str) -> None:
        self._color = QColor(hex_color)
        self.update()

    def _advance(self) -> None:
        self._angle = (self._angle + 30) % 360
        self.update()

    def showEvent(self, event):
        super().showEvent(event)
        if not self._timer.isActive():
            self._timer.start()

    def hideEvent(self, event):
        super().hideEvent(event)
        self._timer.stop()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.translate(self.width() / 2.0, self.height() / 2.0)
        p.rotate(self._angle)
        spokes = 12
        r_out = self._size / 2.0 - 1.0
        r_in = r_out * 0.5
        pen_w = max(1.0, self._size / 12.0)
        for i in range(spokes):
            col = QColor(self._color)
            col.setAlphaF((i + 1) / spokes)
            p.setPen(QPen(col, pen_w, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(0, int(r_in), 0, int(r_out))
            p.rotate(360.0 / spokes)
        p.end()


# ── Smooth Progress Bar ────────────────────────────────────────────────────

class SmoothProgressBar(QWidget):
    """Progress bar painted with sub-pixel precision and rounded pill shape."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._progress = 0.0  # 0.0 to 1.0
        self._bg_color = QColor("#141414")
        self._fill_color = QColor("#e0943a")
        self.setFixedHeight(7)
        self.setMinimumWidth(40)

    def set_progress(self, value: float):
        clamped = max(0.0, min(1.0, value))
        if clamped == self._progress:
            return
        self._progress = clamped
        self.update()

    def set_fill_color(self, hex_color: str):
        self._fill_color = QColor(hex_color)
        self.update()

    def set_bg_color(self, hex_color: str):
        self._bg_color = QColor(hex_color)
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w = self.width()
        h = self.height()
        r = h / 2.0

        # Track background
        p.setPen(Qt.NoPen)
        p.setBrush(self._bg_color)
        p.drawRoundedRect(QRectF(0, 0, w, h), r, r)

        # Fill
        if self._progress > 0.001:
            fill_w = self._progress * w
            # Clamp minimum to pill shape diameter so it stays rounded
            fill_w = max(fill_w, h)
            p.setBrush(self._fill_color)
            p.drawRoundedRect(QRectF(0, 0, fill_w, h), r, r)

        p.end()


# ── Eliding Label ────────────────────────────────────────────────────────────

class ElidingLabel(QLabel):
    """QLabel that truncates overly long text with an ellipsis.

    Unlike a plain QLabel — whose natural sizeHint is the full text width,
    which pushes sibling widgets off the end of the row — this label reports
    a small minimumSizeHint so the surrounding QBoxLayout will shrink it
    preferentially over adjacent fixed/minimum-policy widgets like buttons.
    """

    def __init__(self, text: str = "", mode: Qt.TextElideMode = Qt.ElideRight,
                 min_visible_chars: int = 4, parent=None):
        super().__init__(parent)
        self._full_text = text
        self._elide_mode = mode
        self._min_visible_chars = max(1, min_visible_chars)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        self._apply_elision()

    def setText(self, text: str) -> None:
        self._full_text = text or ""
        self._apply_elision()

    def fullText(self) -> str:
        return self._full_text

    def sizeHint(self) -> QSize:
        fm = QFontMetrics(self.font())
        return QSize(fm.horizontalAdvance(self._full_text), fm.height())

    def minimumSizeHint(self) -> QSize:
        fm = QFontMetrics(self.font())
        return QSize(fm.averageCharWidth() * self._min_visible_chars + fm.horizontalAdvance("…"),
                     fm.height())

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._apply_elision()

    def _apply_elision(self) -> None:
        fm = QFontMetrics(self.font())
        # contentsRect() accounts for stylesheet padding; fall back to width().
        available = max(0, self.contentsRect().width()) or self.width()
        if available <= 0 or fm.horizontalAdvance(self._full_text) <= available:
            super().setText(self._full_text)
        else:
            super().setText(fm.elidedText(self._full_text, self._elide_mode, available))
        self.setToolTip(self._full_text if self.text() != self._full_text else "")


# ── Settings ComboBox ─────────────────────────────────────────────────────────

class SettingsComboBox(QComboBox):
    """QComboBox subclass for the Settings tab dropdowns.

    Wraps QComboBox with:
      * A _CurrentValueDelegate auto-installed so the open menu shows a
        blue dot on the currently-selected row.
      * A custom chevron painted in paintEvent (added in a later task) so
        the closed-state arrow follows hover/focus/disabled state without
        shipping image assets.

    All other styling (outer box, caret cell bg, menu container) comes
    from the global QComboBox QSS rule in utils/theme_manager.py.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        # Defaults: dark-theme palette. Overridden via set_theme_colors()
        # once SettingsTab applies theme to its children (Task 6 wiring).
        self._dot_color = QColor("#0077ff")
        self._is_dark = True
        self.setItemDelegate(_CurrentValueDelegate(self))

    def set_theme_colors(self, *, accent: str, is_dark: bool = True) -> None:
        """Set the accent color (used for the current-value dot in the
        dropdown menu AND for the chevron in :focus state) and theme
        polarity (used to pick idle/hover chevron gray). Called by
        SettingsTab during theme propagation (Task 6 wires this; until
        then the constructor defaults apply)."""
        self._dot_color = QColor(accent)
        self._is_dark = is_dark
        self.update()  # repaint in case the menu is open or the chevron color changed

    # Width of the drop-down (caret) sub-control. Matches Task 5's QSS
    # rule `QComboBox::drop-down { width: 30px; }`.
    _DROPAREA_WIDTH = 30

    def paintEvent(self, event):
        super().paintEvent(event)

        # Pick chevron color from current state. No theme-manager imports
        # here — colors come from set_theme_colors() (Task 6 wires propagation;
        # until then the constructor defaults apply).
        if not self.isEnabled():
            base = QColor("#aaaaaa") if self._is_dark else QColor("#64748b")
            base.setAlpha(128)
            color = base
        elif self.hasFocus():
            color = self._dot_color  # accent blue — ties closed and open states
        elif self.underMouse():
            color = QColor("#dddddd") if self._is_dark else QColor("#475569")
        else:
            color = QColor("#aaaaaa") if self._is_dark else QColor("#64748b")

        # Center of the caret cell (rightmost _DROPAREA_WIDTH pixels).
        w = self.width()
        h = self.height()
        cx = w - self._DROPAREA_WIDTH // 2
        cy = h // 2

        # Chevron: two strokes forming a downward "v", 8px wide x 4px tall.
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.Antialiasing, True)
            pen = QPen(color)
            pen.setWidthF(1.5)
            pen.setCapStyle(Qt.RoundCap)
            pen.setJoinStyle(Qt.RoundJoin)
            painter.setPen(pen)
            painter.drawLine(cx - 4, cy - 2, cx, cy + 2)
            painter.drawLine(cx, cy + 2, cx + 4, cy - 2)
        finally:
            painter.end()


# ── Current Value Delegate ───────────────────────────────────────────────────

# Optional per-item role: when set, the delegate paints this string in the
# menu instead of the item's DisplayRole. The closed-state display (which
# Qt reads from currentText() = DisplayRole) is unaffected. Lets a combo
# show a terser label when selected than the descriptive label it offers
# in the menu — see Reduce motion's "System" (closed) vs "System default"
# (menu) where the 150px fixed width truncates the long form.
MENU_TEXT_ROLE = Qt.UserRole + 1


class _CurrentValueDelegate(QStyledItemDelegate):
    """Paints a small accent-blue dot on the currently-selected row of a
    QComboBox's dropdown menu. Idle/hover backgrounds come from QSS; the
    dot is the 'you are here' indicator that QSS can't express.

    Also honors MENU_TEXT_ROLE: items that set this role get their
    long-form text rendered in the menu via an initStyleOption override.

    The combo is read from self.parent() at paint time so the delegate
    follows whichever combo it's installed on.
    """

    def __init__(self, combo):
        super().__init__(combo)

    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        long_text = index.data(MENU_TEXT_ROLE)
        if long_text:
            option.text = str(long_text)

    def paint(self, painter, option, index):
        super().paint(painter, option, index)

        combo = self.parent()
        if not isinstance(combo, QComboBox):
            return
        if index.row() != combo.currentIndex():
            return

        # Combo caches its accent color via set_theme_colors(); fall back
        # to brand blue if the combo wasn't constructed by SettingsComboBox
        # (defensive — _CurrentValueDelegate is private to SettingsComboBox).
        dot_color = getattr(combo, "_dot_color", QColor("#0077ff"))

        # Paint a 6px-diameter dot, right-aligned 12px from the right edge,
        # vertically centered in the row.
        rect = option.rect
        dot_d = 6
        dot_x = rect.right() - 12 - dot_d
        dot_y = rect.top() + (rect.height() - dot_d) // 2

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(Qt.NoPen)
        painter.setBrush(dot_color)
        painter.drawEllipse(dot_x, dot_y, dot_d, dot_d)
        painter.restore()
