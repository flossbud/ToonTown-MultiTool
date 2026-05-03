import math
import queue
import threading
import time

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QFrame, QGraphicsDropShadowEffect, QStackedWidget
)
from PySide6.QtCore import Qt, Signal, Slot, QTimer, QVariantAnimation, QEasingCurve, QRectF, QPointF, QSize
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen, QPainterPath, QPixmap
from services.input_service import InputService
from utils.theme_manager import (
    resolve_theme, get_theme_colors, apply_card_shadow,
    make_chat_icon, make_refresh_icon, make_mouse_icon,
    make_heart_icon, make_jellybean_icon,
    get_set_color, SmoothProgressBar, make_section_label,
)
from utils.shared_widgets import PulsingDot, ElidingLabel
from utils.symbols import S
from utils.ttr_api import get_toon_names_by_slot, invalidate_port_to_wid_cache, clear_stale_names
from utils import cc_api
from utils.game_registry import GameRegistry


# ── Custom Widgets ─────────────────────────────────────────────────────────





# ── Toon Portrait Widget ────────────────────────────────────────────────────

def _lighten_hex(hex_color: str, amount: float = 0.25) -> str:
    """Lighten a hex color by `amount` in HSL lightness (0.0–1.0)."""
    hex_color = hex_color.lstrip("#")
    if len(hex_color) != 6:
        return f"#{hex_color}"
    r, g, b = [int(hex_color[i:i+2], 16) / 255.0 for i in (0, 2, 4)]
    mx, mn = max(r, g, b), min(r, g, b)
    l = (mx + mn) / 2
    if mx == mn:
        h = s = 0.0
    else:
        d = mx - mn
        s = d / (2 - mx - mn) if l > 0.5 else d / (mx + mn)
        if mx == r:   h = (g - b) / d + (6 if g < b else 0)
        elif mx == g: h = (b - r) / d + 2
        else:         h = (r - g) / d + 4
        h /= 6
    l = min(1.0, l + amount)
    if s == 0:
        r = g = b = l
    else:
        def _hue2rgb(p, q, t):
            if t < 0: t += 1
            if t > 1: t -= 1
            if t < 1/6: return p + (q - p) * 6 * t
            if t < 1/2: return q
            if t < 2/3: return p + (q - p) * (2/3 - t) * 6
            return p
        q = l * (1 + s) if l < 0.5 else l + s - l * s
        p = 2 * l - q
        r = _hue2rgb(p, q, h + 1/3)
        g = _hue2rgb(p, q, h)
        b = _hue2rgb(p, q, h - 1/3)
    return "#{:02x}{:02x}{:02x}".format(int(r * 255), int(g * 255), int(b * 255))


class ToonPortraitWidget(QWidget):
    """Slot badge: shows a rendered toon portrait when available, otherwise
    falls back to a colored circle with the slot number."""

    RENDITION_URL = "https://rendition.toontownrewritten.com/render/{dna}/portrait/128x128.png"

    # Emitted from a worker thread with (dna, QImage_or_None). QImage decoding is
    # safe off the GUI thread; QPixmap creation stays on the GUI thread.
    _image_ready = Signal(str, object)
    clicked = Signal()

    def __init__(self, slot: int, parent=None):
        super().__init__(parent)
        self._slot    = slot
        self._bg      = QColor("#4a4a4a")
        self._text    = QColor("#ffffff")
        self._border_color = None
        self._pixmap  = None
        self._loading = False
        self._dna     = None
        self._fetch_token = 0
        self._cancelled = False
        self.setMinimumSize(38, 38)
        self.setMaximumSize(64, 64)
        self.setCursor(Qt.PointingHandCursor)
        self._image_ready.connect(self._on_image_ready)

    def mousePressEvent(self, event):
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def set_colors(self, bg: str, text: str):
        self._bg   = QColor(bg)
        self._text = QColor(text)
        self.update()

    def set_border_color(self, color: str):
        if color:
            self._border_color = QColor(color)
        else:
            self._border_color = None
        self.update()

    def set_dna(self, dna):
        """Load portrait from Rendition. Pass None to revert to fallback circle."""
        if dna == self._dna and not self._cancelled:
            if not dna or self._loading or self._pixmap is not None:
                return
        self._fetch_token += 1
        self._cancelled = False
        self._dna = dna
        if not dna:
            self._pixmap  = None
            self._loading = False
            self.update()
            return
        self._loading = True
        self.update()
        token = self._fetch_token
        threading.Thread(target=self._fetch, args=(dna, token), daemon=True).start()

    def cancel(self):
        self._cancelled = True
        self._fetch_token += 1
        self._loading = False

    def _fetch(self, dna: str, token: int):
        """Background thread — fetch and decode the portrait off the GUI thread."""
        try:
            import urllib.request
            url = self.RENDITION_URL.format(dna=dna)
            req = urllib.request.Request(url, headers={"User-Agent": "ToonTown MultiTool"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = resp.read()
            if not self._cancelled:
                image = QImage()
                self._image_ready.emit(
                    f"{dna}|{token}",
                    image if image.loadFromData(data) else None,
                )
        except Exception as e:
            print(f"[Portrait] Slot {self._slot}: fetch error — {e}")
            if not self._cancelled:
                self._image_ready.emit(f"{dna}|{token}", None)

    @Slot(str, object)
    def _on_image_ready(self, payload: str, image):
        """Main thread — QPixmap must be constructed on the GUI thread."""
        if "|" not in payload:
            return
        dna, token_str = payload.rsplit("|", 1)
        try:
            token = int(token_str)
        except ValueError:
            return
        if self._cancelled or token != self._fetch_token:
            return
        if dna != self._dna:
            return
        self._loading = False
        if isinstance(image, QImage) and not image.isNull():
            pm = QPixmap.fromImage(image)
            if not pm.isNull():
                self._pixmap = pm
                print(f"[Portrait] Slot {self._slot}: loaded OK")
            else:
                self._pixmap = None
        else:
            self._pixmap = None
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        cx = self.width() / 2.0
        cy = self.height() / 2.0
        r  = min(cx, cy) - 2.0  # leave room for a 2px border

        # Always draw colored circle background first
        if self._border_color:
            p.setPen(QPen(self._border_color, 2.0))
        else:
            p.setPen(Qt.NoPen)
        p.setBrush(self._bg)
        p.drawEllipse(QPointF(cx, cy), r, r)

        if self._pixmap and not self._pixmap.isNull():
            path = QPainterPath()
            path.addEllipse(QPointF(cx, cy), r, r)
            p.setClipPath(path)
            target = max(1, int(r * 2))
            pm = self._pixmap.scaled(
                target, target, Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
            ph, pw = pm.height(), pm.width()
            p.drawPixmap(int(cx - pw / 2), int(cy - ph / 2), pm)
            p.setClipping(False)
        else:
            font = QFont()
            font.setPixelSize(14)
            font.setBold(True)
            if self._loading:
                p.setPen(QColor(180, 180, 180))
                font.setPixelSize(12)
                p.setFont(font)
                p.drawText(self.rect(), Qt.AlignCenter, "…")
            else:
                p.setFont(font)
                p.setPen(self._text)
                p.drawText(self.rect(), Qt.AlignCenter, str(self._slot))
        p.end()

class StatusDots(QWidget):
    """Compact 4-dot row: 0=off, 1=found, 2=active."""

    def __init__(self, parent=None):
        super().__init__(parent)
        # Height matches the StatusBar layout cell (34px bar - 2px borders -
        # 16px top/bottom margins = 16px). Anything taller overflows and Qt
        # clamps the widget to the cell top, pushing dots below the text.
        self.setFixedSize(66, 16)
        self._states = [0, 0, 0, 0]
        self._colors = {0: QColor("#333"), 1: QColor("#555"), 2: QColor("#56c856")}

    def set_states(self, states: list):
        self._states = (states or [0, 0, 0, 0])[:4]
        while len(self._states) < 4:
            self._states.append(0)
        self.update()

    def set_colors(self, off: str, found: str, active: str):
        self._colors = {0: QColor(off), 1: QColor(found), 2: QColor(active)}
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        diameter = 11
        gap = 6
        total_w = diameter * 4 + gap * 3
        x0 = (self.width() - total_w) / 2.0
        y = (self.height() - diameter) / 2.0
        for i in range(4):
            x = x0 + i * (diameter + gap)
            p.setBrush(self._colors.get(self._states[i], self._colors[0]))
            p.drawEllipse(QRectF(x, y, diameter, diameter))
        p.end()


class StatusBar(QFrame):
    """Service status bar with slot dots and status text."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ServiceStatusBar")
        self.setFixedHeight(34)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(8)
        self.dots = StatusDots(self)
        lay.addWidget(self.dots)
        self.label = QLabel("Service idle")
        self.label.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        lay.addWidget(self.label, 1)

    def set_dot_states(self, states: list):
        self.dots.set_states(states)

    def set_dot_colors(self, off: str, found: str, active: str):
        self.dots.set_colors(off, found, active)

    def set_status_text(self, text: str):
        self.label.setText(text)

    def set_text_color(self, color: str):
        self.label.setStyleSheet(
            f"font-size: 13px; font-weight: 500; color: {color}; background: transparent; border: none;"
        )


class KeepAliveBtn(QPushButton):
    """Keep-alive toggle button with a progress ring.

    Short click   → toggle keep-alive on/off.
    Hold 5 s      → toggle rapid-fire for this toon only (independent of the
                    global delay setting). The first 2 s is a silent pre-hold
                    where the button looks like a normal press; the final 3 s
                    shows a red arc growing clockwise around the button.
                    Releasing during the silent pre-hold acts as a click;
                    releasing during the visible countdown cancels.
    """
    rapid_fire_toggled = Signal(bool)

    _PRE_HOLD_MS = 2000   # silent pre-hold before the visible countdown begins
    _COUNTDOWN_MS = 3000  # visible red-arc countdown duration
    _CHARGE_MS = _PRE_HOLD_MS + _COUNTDOWN_MS  # total hold to fire rapid-fire

    def __init__(self, parent=None):
        super().__init__(parent)
        self.is_rapid_fire = False
        self._progress = 0.0        # cycle ring progress (0–1), set by _tick_glow
        self._charge_progress = 0.0  # hold-charge arc progress (0–1)
        self._charging = False
        self._long_press_fired = False
        self._charge_start = 0.0

        self._press_timer = QTimer(self)
        self._press_timer.setSingleShot(True)
        self._press_timer.setInterval(self._CHARGE_MS)
        self._press_timer.timeout.connect(self._on_long_press)

        self._charge_tick = QTimer(self)
        self._charge_tick.setInterval(16)  # ~60 fps
        self._charge_tick.timeout.connect(self._tick_charge)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._long_press_fired = False
            self._charge_start = time.monotonic()
            self._charging = True
            self._charge_progress = 0.0
            self._press_timer.start()
            self._charge_tick.start()
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            was_long = self._long_press_fired
            self._long_press_fired = False
            self._press_timer.stop()
            elapsed_ms = (
                (time.monotonic() - self._charge_start) * 1000
                if self._charging else 0
            )
            countdown_visible = self._charging and elapsed_ms >= self._PRE_HOLD_MS
            if self._charging:
                self._charging = False
                self._charge_tick.stop()
                self._charge_progress = 0.0
                self.update()
            # Block the click signal in two cases:
            #   - long press fired (rapid-fire already toggled)
            #   - released after the visible countdown started (explicit cancel)
            if was_long or countdown_visible:
                self.blockSignals(True)
                super().mouseReleaseEvent(e)
                self.blockSignals(False)
                return
        super().mouseReleaseEvent(e)

    def _tick_charge(self):
        elapsed_ms = (time.monotonic() - self._charge_start) * 1000
        if elapsed_ms < self._PRE_HOLD_MS:
            return  # silent pre-hold: keep _charge_progress at 0, skip repaint
        countdown_elapsed = elapsed_ms - self._PRE_HOLD_MS
        self._charge_progress = min(1.0, countdown_elapsed / self._COUNTDOWN_MS)
        self.update()

    def _on_long_press(self):
        if not self.isEnabled():
            # Master flag flipped off mid-hold; suppress the rapid-fire toggle.
            self._charging = False
            self._charge_tick.stop()
            self._charge_progress = 0.0
            self._long_press_fired = False
            return
        self._charging = False
        self._charge_tick.stop()
        self._charge_progress = 0.0
        self._long_press_fired = True
        self.is_rapid_fire = not self.is_rapid_fire
        self.rapid_fire_toggled.emit(self.is_rapid_fire)
        self.update()

    def set_progress(self, val: float):
        clamped = max(0.0, min(1.0, val))
        if clamped == self._progress:
            return
        self._progress = clamped
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)

        # Only draw during an active hold-charge; the horizontal bar handles cycle progress
        if not (self._charging and self._charge_progress > 0.001):
            return

        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        margin = 3
        rect = QRectF(margin, margin,
                      self.width() - 2 * margin,
                      self.height() - 2 * margin)

        pen = QPen(QColor("#E05252"), 3, Qt.SolidLine, Qt.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawArc(rect, 90 * 16, int(-self._charge_progress * 360 * 16))
        p.end()


class SetSelectorWidget(QWidget):
    """Horizontal movement-set selector — custom-painted rounded rect with edge arrows."""
    index_changed = Signal(int)

    ARROW_ZONE = 24  # px width of each clickable arrow zone

    def __init__(self, keymap_manager, parent=None):
        super().__init__(parent)
        self.keymap_manager = keymap_manager
        self._index = 0
        self._enabled = True
        self._bg = "#4A8FE7"
        self._text_color = "#ffffff"
        self._border_color = "#6AAFFF"
        self._display_text = "Default"
        self._hover_zone = None  # "left", "right", or None
        self._paint_scale = 1.0

        self.setFixedHeight(32)
        self.setMinimumWidth(130)
        self.setCursor(Qt.ArrowCursor)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WA_StyledBackground, False)

        self._refresh_display()

    def set_paint_scale(self, scale: float):
        self._paint_scale = max(0.5, float(scale))
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        from PySide6.QtGui import QFont

        rect = QRectF(1, 1, self.width() - 2, self.height() - 2)
        show_arrows = self._enabled and self._count() > 1
        s = self._paint_scale
        az = max(16, int(self.ARROW_ZONE * s))
        radius = max(4, int(6 * s))

        # Fill
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(self._bg))
        p.drawRoundedRect(rect, radius, radius)

        # Arrow zone hover highlights
        if show_arrows and self._hover_zone:
            highlight = QColor(255, 255, 255, 35)
            p.setBrush(highlight)
            p.setPen(Qt.NoPen)
            if self._hover_zone == "left":
                clip = QPainterPath()
                clip.addRoundedRect(rect, radius, radius)
                p.setClipPath(clip)
                p.drawRect(QRectF(1, 1, az, self.height() - 2))
                p.setClipping(False)
            elif self._hover_zone == "right":
                clip = QPainterPath()
                clip.addRoundedRect(rect, radius, radius)
                p.setClipPath(clip)
                p.drawRect(QRectF(self.width() - az - 1, 1, az, self.height() - 2))
                p.setClipping(False)

        # Border
        pen = QPen(QColor(self._border_color), max(1, int(2 * s)))
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(rect, radius, radius)

        # Center text (name only, no arrows in string)
        font = QFont()
        font.setPixelSize(max(10, int(12 * s)))
        font.setBold(True)
        p.setFont(font)
        p.setPen(QColor(self._text_color))
        text_rect = QRectF(az, 0, self.width() - az * 2, self.height())
        p.drawText(text_rect, Qt.AlignCenter, self._display_text)

        # Draw arrows pinned to edges
        if show_arrows:
            arrow_font = QFont()
            arrow_font.setPixelSize(max(12, int(16 * s)))
            arrow_font.setBold(True)
            p.setFont(arrow_font)

            # Arrow opacity: brighter on hover
            left_alpha = 220 if self._hover_zone == "left" else 100
            right_alpha = 220 if self._hover_zone == "right" else 100

            if self._text_color == "#ffffff":
                left_color = QColor(255, 255, 255, left_alpha)
                right_color = QColor(255, 255, 255, right_alpha)
            else:
                left_color = QColor(0, 0, 0, left_alpha)
                right_color = QColor(0, 0, 0, right_alpha)

            pad = max(4, int(4 * s))
            left_rect = QRectF(pad, 0, az - pad, self.height())
            p.setPen(left_color)
            p.drawText(left_rect, Qt.AlignCenter, S("‹", "<"))

            right_rect = QRectF(self.width() - az, 0, az - pad, self.height())
            p.setPen(right_color)
            p.drawText(right_rect, Qt.AlignCenter, S("›", ">"))

        p.end()

    def mousePressEvent(self, event):
        if not self._enabled or self._count() <= 1:
            return
        x = event.position().x() if hasattr(event, 'position') else event.x()
        arrow_zone = max(16, int(self.ARROW_ZONE * self._paint_scale))
        if x < arrow_zone:
            self._prev()
        elif x > self.width() - arrow_zone:
            self._next()
        # Clicking the middle does nothing

    def mouseMoveEvent(self, event):
        if not self._enabled or self._count() <= 1:
            old = self._hover_zone
            self._hover_zone = None
            if old != self._hover_zone:
                self.update()
            self.setCursor(Qt.ArrowCursor)
            self.setToolTip("Movement set for this toon")
            return

        x = event.position().x() if hasattr(event, 'position') else event.x()
        old = self._hover_zone
        arrow_zone = max(16, int(self.ARROW_ZONE * self._paint_scale))
        if x < arrow_zone:
            self._hover_zone = "left"
            self.setCursor(Qt.PointingHandCursor)
            self.setToolTip("Previous movement set")
        elif x > self.width() - arrow_zone:
            self._hover_zone = "right"
            self.setCursor(Qt.PointingHandCursor)
            self.setToolTip("Next movement set")
        else:
            self._hover_zone = None
            self.setCursor(Qt.ArrowCursor)
            self.setToolTip("Movement set for this toon")

        if old != self._hover_zone:
            self.update()

    def leaveEvent(self, event):
        if self._hover_zone:
            self._hover_zone = None
            self.update()

    def _count(self):
        if self.keymap_manager:
            return len(self.keymap_manager.get_set_names())
        return 1

    def _prev(self):
        if not self._enabled or self._count() <= 1:
            return
        self._index = (self._index - 1) % self._count()
        self._refresh_display()
        self.index_changed.emit(self._index)

    def _next(self):
        if not self._enabled or self._count() <= 1:
            return
        self._index = (self._index + 1) % self._count()
        self._refresh_display()
        self.index_changed.emit(self._index)

    def currentIndex(self) -> int:
        return self._index

    def setCurrentIndex(self, idx: int):
        count = self._count()
        if 0 <= idx < count:
            self._index = idx
        elif idx >= count:
            self._index = 0
        self._refresh_display()

    def currentText(self) -> str:
        if self.keymap_manager:
            names = self.keymap_manager.get_set_names()
            if self._index < len(names):
                return names[self._index]
        return ""

    def count(self) -> int:
        return self._count()

    def findText(self, text: str) -> int:
        if self.keymap_manager:
            names = self.keymap_manager.get_set_names()
            for i, name in enumerate(names):
                if name == text:
                    return i
        return -1

    def setEnabled(self, enabled: bool):
        self._enabled = enabled
        self._refresh_display()

    def rebuild(self):
        count = self._count()
        if self._index >= count:
            self._index = 0
        self._refresh_display()

    def _refresh_display(self):
        names = self.keymap_manager.get_set_names() if self.keymap_manager else ["Default"]
        name = names[self._index] if self._index < len(names) else "Default"
        self._display_text = name
        self.apply_colors()

    def apply_colors(self, theme_colors=None):
        bg, text = get_set_color(self._index)

        if not self._enabled:
            from utils.theme_manager import is_dark_palette, get_theme_colors
            c = theme_colors or get_theme_colors(is_dark_palette())
            bg = c["btn_bg"]
            text = c["text_disabled"]
            border_color = c["btn_border"]
        else:
            base = QColor(bg)
            border_color = base.lighter(135).name()

        self._bg = bg
        self._text_color = text
        self._border_color = border_color
        self.update()


# ── Main Tab ───────────────────────────────────────────────────────────────


class MultitoonTab(QWidget):
    _toon_names_ready  = Signal(list)
    _toon_styles_ready = Signal(list)
    _toon_colors_ready = Signal(list)
    _toon_laffs_ready  = Signal(list)
    _toon_max_laffs_ready = Signal(list)
    _toon_beans_ready  = Signal(list)
    _toon_data_merge_ready = Signal(list, list, list, list, list, list, list)
    keep_alive_updated = Signal()
    dot_state_changed = Signal(int, str)

    def __init__(self, logger=None, settings_manager=None, keymap_manager=None, profile_manager=None, window_manager=None):
        super().__init__()
        self.logger = logger
        self.settings_manager = settings_manager
        self.keymap_manager = keymap_manager
        self.profile_manager = profile_manager
        self.window_manager = window_manager
        self.service_running = False
        self.toon_labels = []       # list of (name_label, status_dot)
        self.laff_labels = []       # list of QLabels showing laff
        self.bean_labels = []       # list of QLabels showing beans
        self.slot_badges = []       # list of QLabel badges
        self.game_badges = []       # list of QLabel game badges
        self.toon_buttons = []
        self.chat_buttons = []
        self.keep_alive_buttons = []
        self.ka_progress_bars = []
        self.ka_groups = []
        self.set_selectors = []     # replaces movement_dropdowns
        self.toon_cards = []
        self.profile_pills = []     # list of QPushButton pills
        self.enabled_toons = [False] * 4
        self.chat_enabled  = [True]  * 4
        self.keep_alive_enabled = [False] * 4
        self.rapid_fire_enabled = [False] * 4
        self.toon_names       = [None] * 4
        self.toon_styles      = [None] * 4
        self.toon_colors      = [None] * 4
        self.toon_laffs       = [None] * 4
        self.toon_max_laffs   = [None] * 4
        self.toon_beans       = [None] * 4
        self._refresh_gen     = 0
        self._toon_fetch_inflight_keys = set()
        self._active_profile  = -1  # no profile active initially
        self._last_window_ids = []

        self._keep_alive_running = False
        self._keep_alive_thread = None
        self._ka_cycle_start = 0.0
        self._ka_cycle_event = threading.Event()
        self._inhibitor_fd = None

        self.key_event_queue = queue.Queue(maxsize=200)

        self.build_ui()

        self.input_service = InputService(
            window_manager=self.window_manager,
            get_enabled_toons=self.get_enabled_toons,
            get_movement_modes=self.get_movement_modes,
            get_event_queue_func=self.get_key_event_queue,
            get_chat_enabled=self.get_chat_enabled,
            settings_manager=settings_manager,
            get_keymap_assignments=self.get_keymap_assignments,
            keymap_manager=self.keymap_manager,
        )
        self.input_service.chat_state_changed.connect(self._on_chat_state_changed)
        self.input_service.input_log.connect(self._on_input_log)
        self._chat_glow_active = False
        self.window_manager.window_ids_updated.connect(self.update_toon_controls)
        self._toon_names_ready.connect(self._apply_toon_names)
        self._toon_styles_ready.connect(self._apply_toon_styles)
        self._toon_colors_ready.connect(self._apply_toon_colors)
        self._toon_laffs_ready.connect(self._apply_toon_laffs)
        self._toon_max_laffs_ready.connect(self._apply_toon_max_laffs)
        self._toon_beans_ready.connect(self._apply_toon_beans)
        self._toon_data_merge_ready.connect(self._apply_merged_toon_data)

        self.refresh_timer = QTimer(self)
        self.refresh_timer.setInterval(5000)
        self.refresh_timer.timeout.connect(self._auto_refresh)

        self._toon_fetch_timer = QTimer(self)
        self._toon_fetch_timer.setSingleShot(True)
        self._toon_fetch_timer.timeout.connect(self._run_scheduled_toon_fetch)

        # Glow animation timer (shared by keep-alive buttons + service button)
        self._glow_phase = 0.0
        self._glow_timer = QTimer(self)
        self._glow_timer.setInterval(50)
        self._glow_timer.timeout.connect(self._tick_glow)

        # Smooth progress bar timer (60fps, independent of glow)
        self._bar_timer = QTimer(self)
        self._bar_timer.setInterval(16)
        self._bar_timer.timeout.connect(self._tick_progress_bars)

        # Listen for keymap changes to refresh dropdowns
        if self.keymap_manager:
            self.keymap_manager.on_change(self._rebuild_set_selectors)

        # Listen for settings changes to reset keep-alive cycle
        if self.settings_manager:
            self.settings_manager.on_change(self._on_setting_changed)

        self.refresh_theme()
        self.apply_all_visual_states()

    # ── UI Construction ────────────────────────────────────────────────────

    def _build_shared_widgets(self):
        """Construct every per-slot widget once. Both Compact and Full layouts
        consume the resulting dict-of-lists so widget state survives a layout swap."""
        # Service controls
        self.toggle_service_button = QPushButton(f"{S(chr(9654), chr(9654))} Start Service")
        self.toggle_service_button.setCheckable(True)
        self.toggle_service_button.clicked.connect(self.toggle_service)
        self.toggle_service_button.setFixedHeight(48)

        self.status_bar = StatusBar()

        self._section_divider = QFrame()
        self._section_divider.setFixedHeight(2)
        self._section_divider.setMaximumWidth(320)
        self._section_divider.setObjectName("section_divider")

        # Toon config row widgets
        self.config_label = QLabel("TOON CONFIGURATION")
        for i in range(5):
            pill = QPushButton(str(i + 1))
            pill.setFixedSize(28, 28)
            pill.setToolTip(f"Load Profile {i+1} (Ctrl+{i+1})")
            pill.clicked.connect(lambda checked, idx=i: self.load_profile(idx))
            self.profile_pills.append(pill)

        self.refresh_button = QPushButton()
        self.refresh_button.setIcon(make_refresh_icon(14))
        self.refresh_button.setFixedSize(26, 26)
        self.refresh_button.setToolTip("Refresh toon windows and configuration")
        self.refresh_button.clicked.connect(self.manual_refresh)

        # Per-slot widgets
        for i in range(4):
            badge = ToonPortraitWidget(i + 1)
            badge.clicked.connect(lambda idx=i: self._on_portrait_clicked(idx))
            self.slot_badges.append(badge)

            name_label = ElidingLabel(f"Toon {i + 1}")
            status_dot = PulsingDot(10)
            status_dot.setToolTip("Not Found")
            self.toon_labels.append((name_label, status_dot))

            game_badge = QLabel()
            game_badge.setObjectName("game_badge")
            game_badge.setAlignment(Qt.AlignCenter)
            game_badge.hide()
            self.game_badges.append(game_badge)

            laff_lbl = QPushButton(" ---")
            laff_lbl.setIcon(make_heart_icon(16))
            laff_lbl.setObjectName("laff_lbl")
            laff_lbl.setAttribute(Qt.WA_TransparentForMouseEvents)
            laff_lbl.setToolTip("Laff")
            laff_lbl.hide()
            self.laff_labels.append(laff_lbl)

            bean_lbl = QPushButton(" ---")
            bean_lbl.setIcon(make_jellybean_icon(16))
            bean_lbl.setObjectName("bean_lbl")
            bean_lbl.setAttribute(Qt.WA_TransparentForMouseEvents)
            bean_lbl.setToolTip("Bank Jellybeans")
            bean_lbl.hide()
            self.bean_labels.append(bean_lbl)

            btn = QPushButton("Enable")
            btn.setCheckable(True)
            btn.setFixedHeight(32)
            btn.setFixedWidth(88)
            btn.setToolTip("Enable input broadcasting for this toon")
            btn.clicked.connect(lambda checked, idx=i: self.toggle_toon(idx))
            self.toon_buttons.append(btn)

            ka_btn = KeepAliveBtn()
            ka_btn.setCheckable(True)
            ka_btn.setChecked(False)
            ka_btn.setFixedHeight(32)
            ka_btn.setFixedWidth(32)
            ka_btn.setIcon(make_mouse_icon(14))
            ka_btn.setToolTip("Toggle keep-alive for this toon")
            ka_btn.clicked.connect(lambda checked, idx=i: self.toggle_keep_alive(idx))
            ka_btn.rapid_fire_toggled.connect(lambda state, idx=i: self.toggle_rapid_fire(idx, state))
            self.keep_alive_buttons.append(ka_btn)

            chat_btn = QPushButton()
            chat_btn.setCheckable(True)
            chat_btn.setChecked(True)
            chat_btn.setFixedHeight(32)
            chat_btn.setFixedWidth(32)
            chat_btn.setIcon(make_chat_icon(14))
            chat_btn.setToolTip("Toggle chat broadcasting for this toon")
            chat_btn.clicked.connect(lambda checked, idx=i: self.toggle_chat(idx))
            self.chat_buttons.append(chat_btn)

            ka_bar = SmoothProgressBar()
            self.ka_progress_bars.append(ka_bar)

            selector = SetSelectorWidget(self.keymap_manager)
            selector.setFixedHeight(28)
            selector.setToolTip("Movement set for this toon")
            selector.index_changed.connect(lambda _, idx=i: self._autosave_active_profile())
            self.set_selectors.append(selector)

    def build_ui(self):
        from tabs.multitoon._compact_layout import _CompactLayout
        from tabs.multitoon._full_layout import _FullLayout

        self._build_shared_widgets()

        # Build both layouts. Each runs populate() in its __init__, so whichever
        # is built second steals widget ownership. We then call _compact.populate()
        # one more time so Compact wins for the initial view.
        self._stack = QStackedWidget(self)
        self._compact = _CompactLayout(self)
        self._full = _FullLayout(self)
        self._compact.populate()  # re-claim ownership for the default view
        self._stack.addWidget(self._compact)
        self._stack.addWidget(self._full)
        self._stack.setCurrentWidget(self._compact)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._stack)

        self._mode = "compact"
        self.update_service_button_style()
        self.update_status_label()

    def set_layout_mode(self, mode: str) -> None:
        if mode == self._mode:
            return
        # Leaving Full — stop card-level animations BEFORE flipping the mode flag.
        if self._mode == "full" and hasattr(self, "_full") and self._full is not None:
            self._full.deactivate()
        target = self._full if mode == "full" else self._compact
        self._mode = mode
        target.populate()
        self._stack.setCurrentWidget(target)
        # Compact widgets are kept in sync by apply_visual_state calls on
        # service/window events, so a layout swap doesn't need a full
        # apply_all_visual_states. Only the Full UI cards need syncing —
        # while in Compact mode, set_active and set_status_state on the Full
        # cards were gated out, so they're stale until we sync. apply_theme
        # is the entry point for layout-specific theme styling on Full cards.
        if mode == "full" and self._full is not None:
            self._full.apply_theme(self._c())
            self._sync_full_cards_to_state()
        else:
            # Compact and Full share the same name_label/laff_label/bean_label
            # widgets. Full's apply_theme set Full-scaled stylesheets on them
            # (28px name, 16px stat); Compact's populate only resets layout/
            # QFonts, not stylesheets. Re-issue Compact's stylesheets so the
            # shared widgets render at Compact sizes again.
            self.refresh_theme()

    def prewarm_full_layout(self, size=None, include_active: bool = False) -> None:
        """Pay Full UI's first polish/paint cost while Compact remains visible."""
        wids = self.window_manager.ttr_window_ids if hasattr(self, "window_manager") else []
        warm_key = "active" if wids else "inactive"
        if warm_key == "active" and not include_active:
            return
        warmed = getattr(self, "_full_layout_prewarmed_states", set())
        if warm_key in warmed:
            return
        if not hasattr(self, "_full") or self._full is None:
            return
        if self._mode != "compact":
            return

        self._full_layout_prewarmed_states = warmed | {warm_key}
        current = None
        try:
            from PySide6.QtGui import QPixmap

            current = self._stack.currentWidget()
            c = self._c()
            self._mode = "full"
            warm_size = size if size is not None else self.size()
            if warm_size.width() <= 0 or warm_size.height() <= 0:
                warm_size = QSize(1280, 812)
            else:
                warm_size = QSize(max(warm_size.width(), 1280), max(warm_size.height(), 812))
            self._full.resize(warm_size)
            self._full.populate()
            self._full.apply_theme(c)
            self._sync_full_cards_to_state()
            self._full.ensurePolished()
            self._full._position_cards()

            render_size = self._full.size()
            if render_size.width() > 0 and render_size.height() > 0:
                pixmap = QPixmap(render_size)
                pixmap.fill(Qt.transparent)
                self._full.render(pixmap)
        finally:
            self._full.deactivate()
            self._compact.populate()
            self._stack.setCurrentWidget(current or self._compact)
            self._mode = "compact"
            # Full's apply_theme set name_label/laff/bean stylesheets at Full's
            # scaled font sizes (28px name, 16px stat). Compact's populate only
            # resets layout/sizing — not stylesheets — so without this the
            # polluted styles linger until something else triggers a refresh.
            self.refresh_theme()

    def _sync_full_cards_to_state(self) -> None:
        """Cheap sync of Full UI cards' active view + status state, without
        the per-toon stylesheet cascade that apply_visual_state runs for
        Compact widgets. Used right after switching into Full mode, since
        while Compact was visible the Full cards' set_active/set_status_state
        calls were gated out and are now stale."""
        if not self._full:
            return
        wids = self.window_manager.ttr_window_ids if hasattr(self, 'input_service') else []
        for index in range(min(4, len(self._full._cards))):
            window_available = index < len(wids)
            active = window_available and self.enabled_toons[index] and self.service_running
            if active:
                state_str = "active"
            elif window_available:
                state_str = "keep_alive" if self.keep_alive_enabled[index] else "disabled"
            else:
                state_str = "off"
            card = self._full._cards[index]
            card.set_active(window_available)
            if window_available:
                card.set_status_state(state_str)
                card._apply_game_pill_style()

    # ── Set selector rebuild ───────────────────────────────────────────────

    # ── Profile methods ────────────────────────────────────────────────────

    def load_profile(self, index: int):
        """Load a profile by index and mark it active."""
        if not self.profile_manager:
            return
        # Save current profile state before switching away
        self._autosave_active_profile()
        profile = self.profile_manager.get_profile(index)
        self._active_profile = index

        enabled = profile.enabled_toons
        modes = profile.movement_modes

        for i in range(4):
            state = enabled[i] if i < len(enabled) else False
            self.enabled_toons[i] = state
            self.toon_buttons[i].setChecked(state)
            self.chat_enabled[i] = state
            self.chat_buttons[i].setChecked(state)

        for i, selector in enumerate(self.set_selectors):
            mode = modes[i] if i < len(modes) else "Default"
            idx = selector.findText(mode)
            if idx >= 0:
                selector.setCurrentIndex(idx)

        ka_states = profile.keep_alive or [False] * 4
        rf_states = profile.rapid_fire or [False] * 4
        for i in range(4):
            self.keep_alive_enabled[i] = ka_states[i] if i < len(ka_states) else False
            self.rapid_fire_enabled[i] = rf_states[i] if i < len(rf_states) else False
            self.keep_alive_buttons[i].setChecked(self.keep_alive_enabled[i])
            self.keep_alive_buttons[i].is_rapid_fire = self.rapid_fire_enabled[i]
            self._apply_keep_alive_btn_style(i, self._c())

        if any(self.keep_alive_enabled) and self._keep_alive_globally_enabled():
            self._start_keep_alive()
        else:
            self._stop_keep_alive()

        self.apply_all_visual_states()
        self.update_status_label()
        self._update_pill_styles()
        self.log(f"[Profile] Loaded '{self.profile_manager.get_name(index)}'")

    def _autosave_active_profile(self):
        """Persist current state to the active profile if one is selected."""
        if self._active_profile < 0 or not self.profile_manager:
            return
        self.profile_manager.save_profile(
            self._active_profile,
            list(self.enabled_toons),
            self.get_movement_modes(),
            keep_alive=list(self.keep_alive_enabled),
            rapid_fire=list(self.rapid_fire_enabled),
        )

    def refresh_profile_pills(self):
        """Re-read profile names from manager and update pill labels."""
        if not self.profile_manager:
            return
        names = self.profile_manager.get_all_names()
        for i, pill in enumerate(self.profile_pills):
            pill.setText(names[i] if i < len(names) else f"Profile {i+1}")
            pill.setToolTip(f"Load {pill.text()} (Ctrl+{i+1})")
        self._update_pill_styles()

    def _update_pill_styles(self):
        if not hasattr(self, 'profile_pills'):
            return
        c = self._c()
        pill_colors = ["#4A8FE7", "#E05252", "#E8A838", "#56c856", "#C87EE8"]
        for i, pill in enumerate(self.profile_pills):
            active = i == self._active_profile
            color = pill_colors[i] if i < len(pill_colors) else c['accent_blue_btn']
            
            if active:
                base_color = QColor(color)
                border_color = base_color.lighter(120).name()
                hover_color = base_color.lighter(110).name()
                pill.setStyleSheet(f"""
                    QPushButton {{
                        background-color: {color};
                        color: white;
                        border: 2px solid {border_color};
                        border-radius: 14px;
                        font-size: 11px;
                        font-weight: bold;
                        padding: 0px;
                        margin: 0px;
                        text-align: center;
                    }}
                    QPushButton:hover {{
                        background-color: {hover_color};
                    }}
                """)
            else:
                pill.setStyleSheet(f"""
                    QPushButton {{
                        background-color: {c['btn_bg']};
                        color: {c['text_secondary']};
                        border: 1px solid {c['border_muted']};
                        border-radius: 14px;
                        font-size: 11px;
                        padding: 0px;
                        margin: 0px;
                        text-align: center;
                    }}
                    QPushButton:hover {{
                        background-color: {c['toon_btn_inactive_hover']};
                        color: {c['text_primary']};
                        border: 1px solid {color};
                    }}
                """)

    def _rebuild_set_selectors(self):
        """Refresh selectors when keymap sets change."""
        if not self.keymap_manager:
            return
        for selector in self.set_selectors:
            selector.rebuild()

    # ── Theme helpers ──────────────────────────────────────────────────────

    def _c(self):
        return get_theme_colors(resolve_theme(self.settings_manager) == "dark")

    def _slot_colors(self, c):
        return [c['slot_1'], c['slot_2'], c['slot_3'], c['slot_4']]

    def refresh_theme(self):
        c = self._c()
        is_dark = resolve_theme(self.settings_manager) == "dark"

        self.outer_card.setStyleSheet("QFrame { background: transparent; border: none; }")
        if is_dark:
            # Etched look: darker groove on top, lighter highlight below
            self._section_divider.setStyleSheet(
                "border: none; border-radius: 2px; "
                "background: qlineargradient(x1:0,y1:0,x2:0,y2:1, "
                "stop:0 #333333, stop:0.49 #333333, stop:0.51 #555555, stop:1 #555555);"
            )
        else:
            self._section_divider.setStyleSheet(
                "border: none; border-radius: 2px; "
                "background: qlineargradient(x1:0,y1:0,x2:0,y2:1, "
                "stop:0 #c0c0c0, stop:0.49 #c0c0c0, stop:0.51 #ffffff, stop:1 #ffffff);"
            )

        self.config_label.setStyleSheet(
            f"font-size: 10px; font-weight: 600; color: {c['text_muted']}; "
            f"background: transparent; border: none; letter-spacing: 0.8px; margin-top: 4px;"
        )
        self._update_pill_styles()
        self.refresh_button.setStyleSheet(f"""
            QPushButton {{
                background-color: {c['btn_bg']};
                color: {c['text_secondary']};
                border: 1px solid {c['btn_border']};
                border-radius: 6px;
                font-size: 14px;
            }}
            QPushButton:hover {{
                background-color: {c['toon_btn_inactive_hover']};
                border: 1px solid {c['accent_blue']};
            }}
        """)

        self.status_bar.set_dot_colors(c['segment_off'], c['segment_found'], c['segment_active'])
        self.status_bar.setStyleSheet(f"""
            QFrame#ServiceStatusBar {{
                background-color: {c['bg_card_inner']};
                border-radius: 8px;
                border: 1px solid {c['border_muted']};
            }}
        """)
        self.update_service_button_style()

        if is_dark:
            toon_card_bg = c['bg_card_inner']
            toon_card_border = c['border_muted']
        else:
            # In light mode, Full UI card surfaces are the source of truth.
            toon_card_bg = c['bg_card']
            toon_card_border = c['border_card']

        # Toon cards
        for i, card in enumerate(self.toon_cards):
            card.setStyleSheet(f"""
                QFrame {{
                    background-color: {toon_card_bg};
                    border-radius: 8px;
                    border: 1px solid {toon_card_border};
                }}
            """)
            name_label, status_dot = self.toon_labels[i]
            name_label.setStyleSheet(
                f"font-size: 14px; font-weight: bold; color: {c['text_primary']}; background: none; border: none;"
            )
            stat_style = (
                f"border: none; background: transparent; font-weight: bold; "
                f"font-size: 13px; color: {c['text_primary']};"
            )
            self.laff_labels[i].setStyleSheet(stat_style)
            self.bean_labels[i].setStyleSheet(stat_style)

        # Keep-alive inset groups + progress bar track color
        for ka_group in self.ka_groups:
            ka_group.setStyleSheet(f"""
                QFrame#ka_group {{
                    background: {c['bg_input']};
                    border: 1px solid {c['border_muted']};
                    border-radius: 8px;
                }}
            """)
        for ka_bar in self.ka_progress_bars:
            ka_bar.set_bg_color(c['border_muted'])

        self.apply_all_visual_states()

        # Apply theme to the *active* layout only. Compact's per-card colors
        # ran above (the toon_cards loop). Full has its own apply_theme entry
        # point that re-applies card frames, status indicators, game pills,
        # and Full-specific name-label styling. We skip _full.apply_theme()
        # while Compact is showing so its styling doesn't bleed into hidden
        # widgets that Compact expects to look different.
        if self._mode == "full" and hasattr(self, "_full") and self._full is not None:
            self._full.apply_theme(c)

        self.update_status_label()

    # ── Visual state per toon ──────────────────────────────────────────────

    def apply_visual_state(self, index):
        c = self._c()
        name_label, status_dot = self.toon_labels[index]
        badge    = self.slot_badges[index]
        btn      = self.toon_buttons[index]
        chat_btn = self.chat_buttons[index]
        selector = self.set_selectors[index]
        wids = self.window_manager.ttr_window_ids if hasattr(self, 'input_service') else []
        window_available = index < len(wids)

        # Mirror window availability into the Full UI card's active/inactive view.
        # Only do this while Full owns the shared widgets; otherwise the hidden
        # Full card can resize Compact's controls during service/window updates.
        if self._mode == "full" and hasattr(self, "_full") and index < len(self._full._cards):
            self._full._cards[index].set_active(window_available)

        slot_colors = self._slot_colors(c)
        active = window_available and self.enabled_toons[index] and self.service_running
        state_str = "off"
        tooltip_str = "Not Found"

        if active:
            state_str = "active"
            tooltip_str = "Connected"
        elif window_available:
            if self.keep_alive_enabled[index]:
                state_str = "keep_alive"
                tooltip_str = "Keep-Alive Active (Input Disabled)"
            else:
                state_str = "disabled"
                tooltip_str = "Input Disabled"

        status_dot.set_state(state_str, tooltip_str)
        self.dot_state_changed.emit(index, state_str)
        if self._mode == "full" and hasattr(self, "_full") and index < len(self._full._cards):
            self._full._cards[index].set_status_state(state_str)

        if window_available:
            game_tag = GameRegistry.instance().get_game_for_window(str(wids[index]))
            if game_tag == "cc":
                self.game_badges[index].setText("CC")
                self.game_badges[index].setStyleSheet(f"background-color: #F26D21; color: white; border-radius: 4px; padding: 2px 6px; font-weight: bold; font-size: 10px; border: 1px solid {c['border_muted']};")
                self.game_badges[index].show()
            elif game_tag == "ttr":
                self.game_badges[index].setText("TTR")
                self.game_badges[index].setStyleSheet(f"background-color: #4A8FE7; color: white; border-radius: 4px; padding: 2px 6px; font-weight: bold; font-size: 10px; border: 1px solid {c['border_muted']};")
                self.game_badges[index].show()
            else:
                self.game_badges[index].hide()
            if self._mode == "full" and hasattr(self, "_full") and index < len(self._full._cards):
                self._full._cards[index]._apply_game_pill_style()
        else:
            self.game_badges[index].hide()

        # -- Slot badge --
        if window_available and self.service_running:
            badge.set_colors(slot_colors[index], "white")
        else:
            badge.set_colors(c['slot_dim'], c['text_muted'])

        service_and_window = self.service_running and window_available

        if not service_and_window:
            # All controls disabled
            btn.setEnabled(False)
            btn.setText("Enable")
            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {c['btn_disabled']};
                    color: {c['text_disabled']};
                    border: none; border-radius: 6px; font-size: 12px;
                }}
            """)
            chat_btn.setEnabled(False)
            chat_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {c['btn_disabled']};
                    color: {c['text_disabled']};
                    border: none; border-radius: 6px;
                }}
            """)
            ka_btn = self.keep_alive_buttons[index]
            ka_btn.setEnabled(False)
            ka_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {c['btn_disabled']};
                    color: {c['text_disabled']};
                    border: none; border-radius: 6px;
                }}
            """)
            selector.setEnabled(False)

        elif self.enabled_toons[index]:
            # Toon enabled — full controls
            btn.setEnabled(True)
            btn.setText("Enabled")
            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {c['accent_green']};
                    color: {c['text_on_accent']}; font-size: 12px; font-weight: bold;
                    border: 2px solid {c['accent_green_border']};
                    border-radius: 6px;
                }}
                QPushButton:hover {{
                    background-color: {c['accent_green_hover']};
                    border: 2px solid {c['accent_green_hover_border']};
                }}
            """)
            self._apply_keep_alive_btn_style(index, c)
            self._apply_chat_btn_style(index, c)
            selector.setEnabled(True)

        else:
            # Toon available but not enabled
            btn.setEnabled(True)
            btn.setText("Enable")
            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {c['toon_btn_inactive_bg']};
                    color: {c['text_primary']}; font-size: 12px;
                    border: 1px solid {c['toon_btn_inactive_border']};
                    border-radius: 6px;
                }}
                QPushButton:hover {{
                    background-color: {c['toon_btn_inactive_hover']};
                    border: 1px solid {c['toon_btn_inactive_hover_border']};
                }}
            """)
            self._apply_keep_alive_btn_style(index, c)
            chat_btn.setEnabled(False)
            chat_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {c['btn_disabled']};
                    color: {c['text_disabled']};
                    border: none; border-radius: 6px;
                }}
            """)
            selector.setEnabled(False)

    def _apply_chat_btn_style(self, index, c):
        chat_btn = self.chat_buttons[index]
        chat_btn.setEnabled(True)
        if self.chat_enabled[index]:
            chat_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {c['accent_blue_btn']};
                    color: {c['text_on_accent']};
                    border: 2px solid {c['accent_blue_btn_border']};
                    border-radius: 6px;
                }}
                QPushButton:hover {{
                    background-color: {c['accent_blue_btn_hover']};
                    border: 2px solid {c['accent_blue_btn_border']};
                }}
            """)
        else:
            chat_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {c['toon_btn_inactive_bg']};
                    color: {c['text_muted']};
                    border: 1px solid {c['toon_btn_inactive_border']};
                    border-radius: 6px;
                }}
                QPushButton:hover {{
                    background-color: {c['toon_btn_inactive_hover']};
                    border: 1px solid {c['toon_btn_inactive_hover_border']};
                }}
            """)

    @Slot(bool)
    def _on_chat_state_changed(self, active):
        """Called from InputService when global chat state changes."""
        self._chat_glow_active = active
        if not active:
            # Remove glow effects and restore proper visual state
            for i in range(4):
                if i < len(self.chat_buttons):
                    self.chat_buttons[i].setGraphicsEffect(None)
            for i in range(4):
                self.apply_visual_state(i)
        self._update_glow_timer()

    @Slot(str)
    def _on_input_log(self, msg):
        self.log(msg)

    def _apply_keep_alive_btn_style(self, index, c):
        ka_btn = self.keep_alive_buttons[index]
        if not self._keep_alive_globally_enabled():
            ka_btn.setEnabled(False)
            ka_btn.setToolTip(
                "Keep-Alive is disabled. Enable it in Settings → Keep-Alive."
            )
            ka_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {c['btn_disabled']};
                    color: {c['text_disabled']};
                    border: none; border-radius: 6px;
                }}
            """)
            bar = self.ka_progress_bars[index] if index < len(self.ka_progress_bars) else None
            if bar:
                bar.set_fill_color(c.get('text_muted', '#888888'))
            return
        ka_btn.setEnabled(True)
        ka_btn.setToolTip("Toggle keep-alive for this toon")
        is_rf = getattr(self, 'rapid_fire_enabled', [False]*4)[index]
        bar = self.ka_progress_bars[index] if index < len(self.ka_progress_bars) else None
        if self.keep_alive_enabled[index]:
            if is_rf:
                ka_btn.setStyleSheet(f"""
                    QPushButton {{
                        background-color: {c['accent_red']};
                        color: {c['text_on_accent']};
                        border: 2px solid {c['accent_red_border']};
                        border-radius: 6px;
                    }}
                    QPushButton:hover {{
                        background-color: {c['accent_red_hover']};
                        border: 2px solid {c['accent_red_border']};
                    }}
                """)
                if bar:
                    bar.set_fill_color("#E05252")  # red for rapid fire
            else:
                ka_btn.setStyleSheet(f"""
                    QPushButton {{
                        background-color: {c['accent_orange']};
                        color: {c['text_on_accent']};
                        border: 2px solid {c['accent_orange_border']};
                        border-radius: 6px;
                    }}
                    QPushButton:hover {{
                        background-color: {c['accent_orange_hover']};
                        border: 2px solid {c['accent_orange_border']};
                    }}
                """)
                if bar:
                    bar.set_fill_color("#e0943a")  # orange to match keep-alive button
        else:
            ka_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {c['toon_btn_inactive_bg']};
                    color: {c['text_muted']};
                    border: 1px solid {c['toon_btn_inactive_border']};
                    border-radius: 6px;
                }}
                QPushButton:hover {{
                    background-color: {c['toon_btn_inactive_hover']};
                    border: 1px solid {c['toon_btn_inactive_hover_border']};
                }}
            """)

    # ── Glow animations ────────────────────────────────────────────────────

    def _tick_glow(self):
        self._glow_phase += 0.05

        delay = self._get_keep_alive_delay()
        elapsed = time.monotonic() - self._ka_cycle_start if self._ka_cycle_start else 0
        normal_progress = min(1.0, elapsed / delay) if delay > 0 else 0.0
        # Rapid-fire ring cycles once per second using modulo
        rf_progress = (elapsed % 1.0) if elapsed > 0 else 0.0

        # Only touch buttons whose state is actually being animated. Hitting
        # disabled ones every tick re-fires update()/paintEvent for no visual
        # change — which used to make ~80 redundant paint requests/sec while
        # the service was on and stutter window drags. Disabled buttons are
        # cleared once at toggle-off time and again when the timer stops.
        for i in range(4):
            if self.keep_alive_enabled[i]:
                is_rf = getattr(self, 'rapid_fire_enabled', [False] * 4)[i]
                self.keep_alive_buttons[i].set_progress(rf_progress if is_rf else normal_progress)

        # Chat button glow pulse when chat broadcast is active
        if self._chat_glow_active:
            pulse = (math.sin(self._glow_phase * 2.0) + 1.0) / 2.0  # 0..1
            blur = 8 + pulse * 14  # 8..22
            alpha = int(140 + pulse * 115)  # 140..255
            c = self._c()
            # Diagonal gradient: base #0077ff ↔ bright #0384fc
            # Shift the gradient stop position to animate the bright spot
            stop = 0.3 + pulse * 0.4  # bright spot travels 30%..70%
            wids = self.window_manager.ttr_window_ids
            for i in range(4):
                has_window = i < len(wids)
                if i < len(self.chat_buttons) and self.chat_enabled[i] and has_window:
                    btn = self.chat_buttons[i]
                    btn.setStyleSheet(f"""
                        QPushButton {{
                            background: qlineargradient(
                                x1:0, y1:0, x2:1, y2:1,
                                stop:0 #0077ff,
                                stop:{stop:.2f} #0384fc,
                                stop:1 #0077ff
                            );
                            color: white;
                            border: 2px solid {c['accent_blue_btn_border']};
                            border-radius: 6px;
                        }}
                    """)
                    glow = QGraphicsDropShadowEffect(btn)
                    glow.setOffset(0, 0)
                    glow.setBlurRadius(blur)
                    glow.setColor(QColor(0, 119, 255, alpha))
                    btn.setGraphicsEffect(glow)


    def _update_glow_timer(self):
        # service_running alone does NOT need the glow timer — it has no
        # animated visual tied to it. Including it here had the timer firing
        # 20 Hz the entire time the service was on, scheduling paintEvents on
        # all 4 keep-alive buttons even though nothing visual was changing.
        needs_glow = any(self.keep_alive_enabled) or self._chat_glow_active
        needs_bars = any(self.keep_alive_enabled)

        if needs_glow and not self._glow_timer.isActive():
            self._glow_phase = 0.0
            self._glow_timer.start()
        elif not needs_glow and self._glow_timer.isActive():
            self._glow_timer.stop()
            for i in range(4):
                self.keep_alive_buttons[i].setGraphicsEffect(None)
                self.keep_alive_buttons[i].set_progress(0.0)

        if needs_bars and not self._bar_timer.isActive():
            self._bar_timer.start()
        elif not needs_bars and self._bar_timer.isActive():
            self._bar_timer.stop()
            for i in range(4):
                if i < len(self.ka_progress_bars):
                    self.ka_progress_bars[i].set_progress(0.0)

    def _tick_progress_bars(self):
        delay = self._get_keep_alive_delay()
        elapsed = time.monotonic() - self._ka_cycle_start if self._ka_cycle_start else 0
        normal_progress = min(1.0, elapsed / delay) if delay > 0 else 0.0
        rf_progress = (elapsed % 1.0) if elapsed > 0 else 0.0

        for i in range(4):
            if i < len(self.ka_progress_bars):
                bar = self.ka_progress_bars[i]
                if self.keep_alive_enabled[i]:
                    is_rf = getattr(self, 'rapid_fire_enabled', [False] * 4)[i]
                    bar.set_progress(rf_progress if is_rf else normal_progress)
                else:
                    bar.set_progress(0.0)

    # ── Service button style ───────────────────────────────────────────────

    def update_service_button_style(self):
        if self.service_running:
            self.toggle_service_button.setText(f"{S(chr(9632), chr(9632))} Stop Service")
            self.toggle_service_button.setToolTip("Stop the multitoon input service")
            self.toggle_service_button.setStyleSheet("""
                QPushButton {
                    background-color: #b34848;
                    color: white;
                    font-size: 14px;
                    font-weight: bold;
                    border: 2px solid #d95757;
                    border-radius: 8px;
                }
                QPushButton:hover {
                    background-color: #cc5e5e;
                    border-color: #e06a6a;
                }
                QPushButton:pressed {
                    background-color: #993d3d;
                    border-color: #c04e4e;
                }
            """)
        else:
            self.toggle_service_button.setText(f"{S(chr(9654), chr(9654))} Start Service")
            self.toggle_service_button.setToolTip("Start the multitoon input service")
            self.toggle_service_button.setStyleSheet("""
                QPushButton {
                    background-color: #0077ff;
                    color: white;
                    font-size: 14px;
                    font-weight: bold;
                    border: 2px solid #3399ff;
                    border-radius: 8px;
                }
                QPushButton:hover {
                    background-color: #1a88ff;
                    border-color: #55aaff;
                }
                QPushButton:pressed {
                    background-color: #0066dd;
                    border-color: #2288ee;
                }
            """)
        self.toggle_service_button.setGraphicsEffect(None)
        self.toggle_service_button.update()

    def apply_all_visual_states(self):
        for i in range(4):
            self.apply_visual_state(i)

    # ── Status label + segment bar ─────────────────────────────────────────

    def update_status_label(self):
        c = self._c()
        count = sum(self.enabled_toons)

        segments = []
        wids = self.window_manager.ttr_window_ids if hasattr(self, 'input_service') else []
        for i in range(4):
            window_available = i < len(wids)
            if window_available and self.enabled_toons[i] and self.service_running:
                segments.append(2)
            elif window_available:
                segments.append(1)
            else:
                segments.append(0)
        self.status_bar.set_dot_states(segments)

        if self.service_running and count > 0:
            text = f"Sending input to {count} toon{'s' if count != 1 else ''}"
            self.status_bar.set_status_text(text)
            self.status_bar.set_text_color(c['text_primary'])
        elif self.service_running:
            ka_count = sum(self.keep_alive_enabled)
            if ka_count > 0:
                text = f"Keep-alive sending to {ka_count} toon{'s' if ka_count != 1 else ''}"
            else:
                text = "No toons enabled"
            self.status_bar.set_status_text(text)
            self.status_bar.set_text_color(c['status_warning_text'])
        else:
            self.status_bar.set_status_text("Service idle")
            self.status_bar.set_text_color(c['text_muted'])

    # ── Name fetching ──────────────────────────────────────────────────────

    def schedule_toon_data_fetch(self, delay_ms: int = 1200):
        if not self.window_manager.ttr_window_ids:
            return
        self._toon_fetch_timer.start(max(0, delay_ms))

    def _run_scheduled_toon_fetch(self):
        self._fetch_names_if_enabled(len(self.window_manager.ttr_window_ids))

    def _fetch_names_if_enabled(self, num_slots: int):
        wids = list(self.window_manager.ttr_window_ids) if hasattr(self, 'window_manager') and self.window_manager else []
        ttr_enabled = bool(self.settings_manager and self.settings_manager.get("enable_companion_app", True))
        cc_enabled = bool(self.settings_manager and self.settings_manager.get("enable_cc_companion_app", True))
        if not wids or not (ttr_enabled or cc_enabled):
            return

        request_key = (tuple(wids), ttr_enabled, cc_enabled)
        if request_key in self._toon_fetch_inflight_keys:
            return

        self._toon_fetch_inflight_keys.add(request_key)
        self._refresh_gen += 1
        gen = self._refresh_gen

        def _run_fetch():
            try:
                registry = GameRegistry.instance()
                ttr_wids = [wid for wid in wids if registry.get_game_for_window(wid) == "ttr"]
                cc_wids = [wid for wid in wids if registry.get_game_for_window(wid) == "cc"]

                if ttr_wids and ttr_enabled:
                    names, styles, colors, laffs, max_laffs, beans = get_toon_names_by_slot(len(ttr_wids), ttr_wids)
                    if gen == self._refresh_gen:
                        self._toon_data_merge_ready.emit(list(ttr_wids), list(names), list(styles), list(colors), list(laffs), list(max_laffs), list(beans))

                if cc_wids and cc_enabled:
                    def _cc_callback(names, styles, colors, laffs, max_laffs, beans):
                        if gen == self._refresh_gen:
                            self._toon_data_merge_ready.emit(list(cc_wids), list(names), list(styles), list(colors), list(laffs), list(max_laffs), list(beans))
                    cc_api.get_toon_names_threaded(len(cc_wids), _cc_callback, cc_wids)
            finally:
                self._toon_fetch_inflight_keys.discard(request_key)

        threading.Thread(target=_run_fetch, daemon=True).start()

    def manual_refresh(self):
        self.log("[Service] Manual refresh triggered.")
        invalidate_port_to_wid_cache()
        clear_stale_names([])
        self.toon_names = [None] * 4
        self.toon_styles = [None] * 4
        self.toon_colors = [None] * 4
        self.toon_laffs = [None] * 4
        self.toon_max_laffs = [None] * 4
        self.toon_beans = [None] * 4
        for i in range(4):
            if i < len(self.slot_badges):
                self.slot_badges[i].set_dna(None)
        self._last_window_ids = []
        self._refresh_toon_name_labels()
        self._refresh_toon_stats_labels()
        
        while not self.key_event_queue.empty():
            try:
                self.key_event_queue.get_nowait()
            except Exception:
                pass
                
        if self.service_running:
            self.input_service.stop()
            self.window_manager.clear_window_ids()
            # No main-thread assign_windows(); poll loop reassigns within ~2s.
            self.input_service.start()
            self.schedule_toon_data_fetch(1200)
        else:
            self.window_manager.disable_detection()
            self.update_toon_controls([])

    def _auto_refresh(self):
        # Don't call assign_windows() here — it runs xdotool subprocesses
        # synchronously on the main thread, which blocks the UI for up to a
        # few seconds on Wayland under load. The window_manager's poll thread
        # already runs assign_windows() every 2s in its own thread, so the
        # window list stays fresh without blocking compact↔full swaps.
        self._fetch_names_if_enabled(len(self.window_manager.ttr_window_ids))

    # ── Service lifecycle ──────────────────────────────────────────────────

    def toggle_service(self):
        self.service_running = not self.service_running
        if self.service_running:
            # No assign_windows() here — it's a no-op (detection_enabled is
            # still False), and even when it isn't, the call must not run on
            # the main thread. Poll loop handles assignment within ~2s.
            self.input_service.window_manager.enable_detection()
            self._start_service_internal()
        else:
            self.input_service.stop()
            self.refresh_timer.stop()
            self._toon_fetch_timer.stop()
            self._refresh_gen += 1
            self.input_service.window_manager.disable_detection()
            self.disable_all_toon_controls()
            self.log("[Service] Multitoon service stopped.")
        self.update_service_button_style()
        self._update_glow_timer()

    def _start_service_internal(self):
        self.input_service.start()
        self.log("[Service] Multitoon service started.")
        wids = self.window_manager.ttr_window_ids
        for i in range(4):
            if i < len(wids):
                self.enabled_toons[i] = True
                self.chat_enabled[i]  = True
                self.toon_buttons[i].setChecked(True)
                self.chat_buttons[i].setChecked(True)
                self.apply_visual_state(i)
        count = len(wids)
        if count:
            self.log(f"[Input] {count} toon window{'s' if count != 1 else ''} detected — input + chat enabled")
        self.update_status_label()
        self.refresh_timer.start()
        self.schedule_toon_data_fetch(1200)

    def start_service(self):
        if not self.service_running:
            self.toggle_service()

    def stop_service(self):
        if self.service_running:
            self.toggle_service()

    def set_service_active(self, active: bool):
        if self.service_running != active:
            self.toggle_service()

    def disable_all_toon_controls(self):
        self._stop_keep_alive()
        for i in range(4):
            self.toon_buttons[i].setChecked(False)
            self.chat_buttons[i].setChecked(True)
            self.keep_alive_buttons[i].setChecked(False)
            self.keep_alive_buttons[i].is_rapid_fire = False
            self.enabled_toons[i] = False
            self.chat_enabled[i]  = True
            self.keep_alive_enabled[i] = False
            self.rapid_fire_enabled[i] = False
            self.toon_names[i]    = None
            self.toon_styles[i]   = None
            self.toon_colors[i]   = None
            if i < len(self.slot_badges):
                self.slot_badges[i].set_dna(None)
            self.apply_visual_state(i)
        self._update_glow_timer()
        self._refresh_toon_name_labels()
        self.update_status_label()

    def _on_portrait_clicked(self, index: int):
        if index < len(self.window_manager.ttr_window_ids):
            wid = self.window_manager.ttr_window_ids[index]
            if wid:
                self.input_service.send_keep_alive_to_window(wid, "f1", modifiers=["shift"])
                self.log(f"[EasterEgg] Sent shift+f1 to Toon {index + 1} (WID {wid})")

    # ── Toon toggles ───────────────────────────────────────────────────────

    def toggle_toon(self, index):
        self.enabled_toons[index] = not self.enabled_toons[index]
        self.toon_buttons[index].setChecked(self.enabled_toons[index])
        if self.enabled_toons[index]:
            self.chat_enabled[index] = True
            self.chat_buttons[index].setChecked(True)
        else:
            self.chat_enabled[index] = False
            self.chat_buttons[index].setChecked(False)
        state = "enabled" if self.enabled_toons[index] else "disabled"
        name = self.toon_names[index] or f"Toon {index + 1}"
        self.log(f"[Input] {name} (slot {index + 1}): input {state}")
        self.apply_visual_state(index)
        self.update_status_label()
        self._autosave_active_profile()

    def toggle_chat(self, index):
        self.chat_enabled[index] = not self.chat_enabled[index]
        self.chat_buttons[index].setChecked(self.chat_enabled[index])
        state = "enabled" if self.chat_enabled[index] else "disabled"
        name = self.toon_names[index] or f"Toon {index + 1}"
        self.log(f"[Input] {name} (slot {index + 1}): chat {state}")
        self.apply_visual_state(index)

    def toggle_rapid_fire(self, index, state):
        self.rapid_fire_enabled[index] = state
        self._apply_keep_alive_btn_style(index, self._c())
        if state and not self.keep_alive_enabled[index]:
            self.toggle_keep_alive(index)
        if self._keep_alive_running:
            self._ka_cycle_event.set()

    def toggle_keep_alive(self, index):
        if not self._keep_alive_globally_enabled():
            # Master flag is off — suppress toggle. The button should already
            # be visually disabled; this guards against programmatic callers
            # like load_profile or hotkey-driven paths.
            return
        self.keep_alive_enabled[index] = not self.keep_alive_enabled[index]
        self.keep_alive_buttons[index].setChecked(self.keep_alive_enabled[index])

        # Turning off: always clear rapid fire so the next click-on starts fresh
        if not self.keep_alive_enabled[index]:
            self.rapid_fire_enabled[index] = False
            self.keep_alive_buttons[index].is_rapid_fire = False
            # _tick_glow no longer touches disabled buttons each frame; clear
            # the just-disabled button's progress ring + glow effect here so
            # it doesn't stay frozen at the last value.
            self.keep_alive_buttons[index].setGraphicsEffect(None)
            self.keep_alive_buttons[index].set_progress(0.0)
        else:
            self._reset_ka_cycle()

        self._apply_keep_alive_btn_style(index, self._c())
        self.update_service_button_style()

        if any(self.keep_alive_enabled):
            # Ensure the keep-alive loop is running
            self._start_keep_alive()
        else:
            self._stop_keep_alive()
        self._update_glow_timer()
        self.apply_visual_state(index)

    def set_toon_enabled(self, index, enabled: bool):
        self.enabled_toons[index] = enabled
        self.toon_buttons[index].setChecked(enabled)
        self.apply_visual_state(index)
        self.update_status_label()

    # ── Window update handler ──────────────────────────────────────────────

    def update_toon_controls(self, window_ids):
        ids_changed = window_ids != self._last_window_ids

        if ids_changed:
            if self._last_window_ids:
                old_enabled = list(self.enabled_toons)
                old_chat    = list(self.chat_enabled)
                old_ka      = list(self.keep_alive_enabled)
                old_rf      = list(self.rapid_fire_enabled)
                old_sels    = [s.currentIndex() for s in self.set_selectors]
                
                old_names   = list(self.toon_names)
                old_styles  = list(self.toon_styles)
                old_colors  = list(self.toon_colors)
                old_laffs   = list(self.toon_laffs)
                old_maxlaffs= list(self.toon_max_laffs)
                old_beans   = list(self.toon_beans)

                for new_idx, wid in enumerate(window_ids):
                    if new_idx >= 4: break
                    if wid in self._last_window_ids:
                        old_idx = self._last_window_ids.index(wid)
                        self.enabled_toons[new_idx]      = old_enabled[old_idx]
                        self.chat_enabled[new_idx]        = old_chat[old_idx]
                        self.keep_alive_enabled[new_idx]  = old_ka[old_idx]
                        self.rapid_fire_enabled[new_idx]  = old_rf[old_idx]
                        self.keep_alive_buttons[new_idx].is_rapid_fire = old_rf[old_idx]
                        self.set_selectors[new_idx].setCurrentIndex(old_sels[old_idx])
                        
                        self.toon_names[new_idx] = old_names[old_idx]
                        self.toon_styles[new_idx] = old_styles[old_idx]
                        self.toon_colors[new_idx] = old_colors[old_idx]
                        self.toon_laffs[new_idx] = old_laffs[old_idx]
                        self.toon_max_laffs[new_idx] = old_maxlaffs[old_idx]
                        self.toon_beans[new_idx] = old_beans[old_idx]
                        
                        if new_idx < len(self.slot_badges):
                            self.slot_badges[new_idx].set_dna(old_styles[old_idx])

                for i in range(4):
                    self.toon_buttons[i].setChecked(self.enabled_toons[i])
                    self.chat_buttons[i].setChecked(self.chat_enabled[i])
                    self.keep_alive_buttons[i].setChecked(self.keep_alive_enabled[i])

            self._last_window_ids = list(window_ids)
            invalidate_port_to_wid_cache()
            clear_stale_names(window_ids)
            # Do not completely blow away toon_names, they are now correctly shifted above.
            self._refresh_toon_name_labels()

        for i in range(4):
            if i >= len(window_ids):
                self.enabled_toons[i] = False
                self.chat_enabled[i]  = True
                self.toon_buttons[i].setChecked(False)
                self.chat_buttons[i].setChecked(True)
                
                # Clear all cached data for this slot
                self.toon_names[i] = None
                self.toon_styles[i] = None
                if i < len(self.slot_badges):
                    self.slot_badges[i].set_dna(None)
                self.toon_colors[i] = None
                self.toon_laffs[i] = None
                self.toon_max_laffs[i] = None
                self.toon_beans[i] = None
                
                if getattr(self, 'rapid_fire_enabled', None) is not None:
                    self.rapid_fire_enabled[i] = False
                if self.keep_alive_enabled[i]:
                    self.toggle_keep_alive(i)
            elif self.service_running and not self.enabled_toons[i]:
                self.enabled_toons[i] = True
                self.toon_buttons[i].setChecked(True)
            self.apply_visual_state(i)
        self.update_status_label()
        self.schedule_toon_data_fetch(1200)
        self._update_glow_timer()
        self._refresh_toon_stats_labels()
        if not any(self.keep_alive_enabled):
            self._stop_keep_alive()

    # ── Name handling ──────────────────────────────────────────────────────

    @Slot(list, list, list, list, list, list, list)
    def _apply_merged_toon_data(self, target_wids, names, styles, colors, laffs, max_laffs, beans):
        wids = list(self.window_manager.ttr_window_ids) if hasattr(self, 'window_manager') and self.window_manager else []
        for source_idx, wid in enumerate(target_wids):
            if wid in wids:
                global_idx = wids.index(wid)
                if global_idx < 4:
                    if source_idx < len(names):
                        self.toon_names[global_idx] = names[source_idx]
                        self.toon_styles[global_idx] = styles[source_idx]
                        self.toon_colors[global_idx] = colors[source_idx]
                        self.toon_laffs[global_idx] = laffs[source_idx]
                        self.toon_max_laffs[global_idx] = max_laffs[source_idx]
                        self.toon_beans[global_idx] = beans[source_idx]
                        
                        if global_idx < len(self.slot_badges):
                            self.slot_badges[global_idx].set_dna(styles[source_idx] if styles and source_idx < len(styles) else None)
        self._refresh_toon_name_labels()
        self._refresh_toon_stats_labels()

    def _on_toon_names_received(self, names, styles, colors, laffs, max_laffs, beans):
        self._toon_names_ready.emit(list(names))
        self._toon_styles_ready.emit(list(styles))
        self._toon_colors_ready.emit(list(colors))
        self._toon_laffs_ready.emit(list(laffs))
        self._toon_max_laffs_ready.emit(list(max_laffs))
        self._toon_beans_ready.emit(list(beans))

    @Slot(list)
    def _apply_toon_names(self, names: list):
        for i, name in enumerate(names):
            if i < len(self.toon_names):
                self.toon_names[i] = name
        self._refresh_toon_name_labels()

    @Slot(list)
    def _apply_toon_styles(self, styles: list):
        for i, style in enumerate(styles):
            if style != self.toon_styles[i]:
                self.toon_styles[i] = style
                if i < len(self.slot_badges):
                    self.slot_badges[i].set_dna(style)
                    self.apply_visual_state(i)

    @Slot(list)
    def _apply_toon_colors(self, colors: list):
        for i, color in enumerate(colors):
            if color != self.toon_colors[i]:
                self.toon_colors[i] = color
                self.apply_visual_state(i)

    @Slot(list)
    def _apply_toon_laffs(self, laffs: list):
        for i, laff in enumerate(laffs):
            self.toon_laffs[i] = laff
        self._refresh_toon_stats_labels()

    @Slot(list)
    def _apply_toon_max_laffs(self, max_laffs: list):
        for i, max_laff in enumerate(max_laffs):
            self.toon_max_laffs[i] = max_laff
        self._refresh_toon_stats_labels()

    @Slot(list)
    def _apply_toon_beans(self, beans: list):
        for i, bean in enumerate(beans):
            self.toon_beans[i] = bean
        self._refresh_toon_stats_labels()

    @Slot()
    def _refresh_toon_stats_labels(self):
        for i in range(len(self.laff_labels)):
            laff_lbl = self.laff_labels[i]
            bean_lbl = self.bean_labels[i]

            # Only show if we have data for the toon
            window_available = i < len(self._last_window_ids)
            has_data =  self.toon_names[i] is not None

            if window_available and has_data:
                # Update Laff
                claff = self.toon_laffs[i]
                mlaff = self.toon_max_laffs[i]
                if claff is not None and mlaff is not None:
                    laff_lbl.setIcon(make_heart_icon(16))
                    laff_lbl.setText(f" {claff}/{mlaff}")
                    laff_lbl.show()
                else:
                    laff_lbl.hide()
                
                # Update Beans
                cbeans = self.toon_beans[i]
                if cbeans is not None:
                    bean_lbl.setIcon(make_jellybean_icon(16))
                    bean_lbl.setText(f" {cbeans:,}")
                    bean_lbl.show()
                else:
                    bean_lbl.hide()
            else:
                laff_lbl.hide()
                bean_lbl.hide()

    @Slot()
    def _refresh_toon_name_labels(self):
        c = self._c()
        for i, (name_label, _) in enumerate(self.toon_labels):
            display = self.toon_names[i] if self.toon_names[i] else f"Toon {i + 1}"
            name_label.setText(display)
            name_label.setStyleSheet(
                f"font-size: 14px; font-weight: bold; color: {c['text_primary']}; background: none; border: none;"
            )
        if self._mode == "full" and hasattr(self, "_full") and self._full is not None:
            for card in self._full._cards:
                card._apply_scaled_styles()

    # ── Accessors ──────────────────────────────────────────────────────────

    def get_enabled_toons(self):
        return self.enabled_toons

    def get_chat_enabled(self):
        return self.chat_enabled

    def get_keymap_assignments(self):
        """Return per-toon set indices from the set selector dropdowns."""
        return [self.set_selectors[i].currentIndex() for i in range(4)]

    def get_movement_modes(self):
        """Legacy accessor — returns stub for backward compat."""
        if self.keymap_manager:
            # Return names for preset save/load compatibility
            return [self.set_selectors[i].currentText() for i in range(4)]
        return [self.set_selectors[i].currentText() for i in range(4)]

    def get_key_event_queue(self):
        return self.key_event_queue

    # ── Keep-alive loop ────────────────────────────────────────────────────

    def _reset_ka_cycle(self):
        """Reset the keep-alive cycle timer — progress bars restart from zero."""
        self._ka_cycle_start = time.monotonic()
        self._ka_cycle_event.set()  # wake up the sleep loop so it restarts

    def _on_setting_changed(self, key, value):
        """Called when any setting changes — reset keep-alive cycle if relevant."""
        if key in ("keep_alive_delay", "keep_alive_action"):
            if any(self.keep_alive_enabled):
                self._reset_ka_cycle()
        elif key == "keep_alive_enabled":
            if value:
                # Master flipped on. Refresh per-toon visuals (they were ghosted)
                # and start the thread if any per-toon flags are set.
                for i in range(4):
                    self.apply_visual_state(i)
                if any(self.keep_alive_enabled):
                    self._start_keep_alive()
            else:
                self._suspend_keep_alive()

    # ── Sleep inhibitor ───────────────────────────────────────────────────

    def _acquire_sleep_inhibitor(self):
        """Hold a systemd sleep/idle inhibitor lock for the duration of keep-alive.
        Works on KDE, GNOME, or any systemd-based distro with no DE at all.
        The fd is owned by this process — released automatically on crash too."""
        if self._inhibitor_fd is not None:
            return
        import sys
        if sys.platform == "win32":
            try:
                import ctypes
                # ES_CONTINUOUS | ES_SYSTEM_REQUIRED
                ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001)
                self._inhibitor_fd = "win32"
                self.log("[KeepAlive] Sleep/idle inhibitor acquired (Windows).")
            except Exception as e:
                self.log(f"[KeepAlive] Could not acquire sleep inhibitor on Windows: {e}")
                self._inhibitor_fd = None
            return

        try:
            import dbus
            bus = dbus.SystemBus()
            manager = bus.get_object("org.freedesktop.login1", "/org/freedesktop/login1")
            iface = dbus.Interface(manager, "org.freedesktop.login1.Manager")
            fd = iface.Inhibit(
                "sleep:idle",
                "ToonTown MultiTool",
                "Keep-Alive is active",
                "block"
            )
            self._inhibitor_fd = fd.take()
            self.log("[KeepAlive] Sleep/idle inhibitor acquired.")
        except Exception as e:
            self.log(f"[KeepAlive] Could not acquire sleep inhibitor (install python3-dbus if needed): {e}")
            self._inhibitor_fd = None

    def _release_sleep_inhibitor(self):
        """Release the inhibitor lock, allowing sleep/idle again."""
        if self._inhibitor_fd is None:
            return
        import sys
        if sys.platform == "win32":
            try:
                import ctypes
                # ES_CONTINUOUS to clear the state
                ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)
                self.log("[KeepAlive] Sleep/idle inhibitor released (Windows).")
            except Exception:
                pass
            finally:
                self._inhibitor_fd = None
            return

        try:
            import os
            os.close(self._inhibitor_fd)
            self.log("[KeepAlive] Sleep/idle inhibitor released.")
        except Exception:
            pass
        finally:
            self._inhibitor_fd = None

    def _start_keep_alive(self):
        if not self._keep_alive_running:
            self._keep_alive_running = True
            self._ka_cycle_start = time.monotonic()
            self._ka_cycle_event.clear()
            self._acquire_sleep_inhibitor()
            self._keep_alive_thread = threading.Thread(
                target=self._run_keep_alive_loop, daemon=True
            )
            self._keep_alive_thread.start()

    def _stop_keep_alive(self):
        self._keep_alive_running = False
        self._ka_cycle_start = 0.0
        self._ka_cycle_event.set()  # wake thread so it exits
        if self._keep_alive_thread is not None and self._keep_alive_thread.is_alive():
            self._keep_alive_thread.join(timeout=2.0)
        self._release_sleep_inhibitor()
        for i in range(4):
            self.keep_alive_buttons[i].set_progress(0.0)
            if i < len(self.ka_progress_bars):
                self.ka_progress_bars[i].set_progress(0.0)

    def _suspend_keep_alive(self):
        """Stop KA execution and clear button visuals while preserving per-toon
        flags. Called when the master toggle flips off — per-toon setup is the
        user's, the master flag is just whether the feature class is enabled."""
        self._stop_keep_alive()
        for i in range(4):
            if i < len(self.keep_alive_buttons):
                btn = self.keep_alive_buttons[i]
                btn.setGraphicsEffect(None)
                btn.set_progress(0.0)
        self._update_glow_timer()
        for i in range(4):
            self.apply_visual_state(i)

    def _get_keep_alive_delay(self) -> float:
        if not self.settings_manager:
            return 60
        delay_str = self.settings_manager.get("keep_alive_delay", "30 sec")
        return {
            "Rapid Fire": 0.25, "1 sec": 1, "5 sec": 5, "10 sec": 10, "30 sec": 30,
            "1 min": 60, "3 min": 180, "5 min": 300, "10 min": 600
        }.get(delay_str, 60)

    def _keep_alive_globally_enabled(self) -> bool:
        """Return True iff the user has opted in to Keep-Alive via Settings.
        Gates per-toon button availability, toggle_keep_alive, and the
        keep-alive thread loop."""
        return bool(
            self.settings_manager
            and self.settings_manager.get("keep_alive_enabled", False)
        )

    def _run_keep_alive_loop(self):
        try:
            last_normal_fire = 0.0
            last_rapid_fire = 0.0
            while self._keep_alive_running:
                # Run the loop every 1 second max if there is a rapid fire, else delay
                if any(getattr(self, 'rapid_fire_enabled', [False]*4)):
                    timeout_val = 1.0
                else:
                    timeout_val = self._get_keep_alive_delay()
                
                self._ka_cycle_event.wait(timeout=timeout_val)
                if self._ka_cycle_event.is_set():
                    self._ka_cycle_event.clear()
                    if not self._keep_alive_running:
                        break
                        
                if not self._keep_alive_running:
                    break

                # Master flag re-check: if the user opted out while we were
                # sleeping, skip this cycle. _suspend_keep_alive will stop
                # the thread soon after; this is defense in depth so at most
                # one in-flight burst can leak.
                if not self._keep_alive_globally_enabled():
                    continue

                now = time.monotonic()
                normal_delay = self._get_keep_alive_delay()
                
                fire_toons = []
                if now - last_rapid_fire >= 1.0:
                    rapid_toons = [i for i, state in enumerate(getattr(self, 'rapid_fire_enabled', [False]*4)) if state and self.keep_alive_enabled[i]]
                    fire_toons.extend(rapid_toons)
                    if rapid_toons:
                        last_rapid_fire = now
                        
                if now - last_normal_fire >= normal_delay or last_normal_fire == 0.0:
                    normal_toons = [i for i, state in enumerate(self.keep_alive_enabled) if state and not getattr(self, 'rapid_fire_enabled', [False]*4)[i]]
                    fire_toons.extend(normal_toons)
                    if normal_toons:
                        last_normal_fire = now
                        self._ka_cycle_start = now
                
                fire_toons = list(set(fire_toons))
                if not fire_toons:
                    continue

                action = self.settings_manager.get("keep_alive_action", "jump") if self.settings_manager else "jump"
                key = None
                if self.keymap_manager:
                    key = self.keymap_manager.get_key_for_direction(0, action)
                if not key:
                    continue

                for i in fire_toons:
                    if i < len(self.window_manager.ttr_window_ids):
                        self.input_service.send_keep_alive_to_window(
                            self.window_manager.ttr_window_ids[i], key
                        )

                action_labels = {"jump": "Jump", "book": "Book", "up": "Move Forward"}
                label = action_labels.get(action, action)
                self.log(f"[KeepAlive] Sent '{label}' ({key}) to {len(fire_toons)} toon(s)")
        except Exception as e:
            self.log(f"[KeepAlive] Error: {e}")

    def log(self, msg):
        if self.logger:
            self.logger.append_log(msg)
        else:
            print(msg)

    def shutdown(self):
        self._stop_keep_alive()
        self.refresh_timer.stop()
        self._toon_fetch_timer.stop()
        self._glow_timer.stop()
        self._bar_timer.stop()
        for badge in self.slot_badges:
            try:
                badge.cancel()
            except Exception:
                pass
        self.input_service.shutdown()
