import math
import queue
import threading
import time

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QFrame, QGraphicsDropShadowEffect
)
from PySide6.QtCore import Qt, Signal, Slot, QTimer, QVariantAnimation, QEasingCurve, QRectF
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPainterPath, QPixmap
from services.input_service import InputService
from utils.theme_manager import (
    resolve_theme, get_theme_colors, apply_card_shadow,
    make_chat_icon, make_refresh_icon, make_mouse_icon,
    get_set_color,
)
from utils.symbols import S
from utils.ttr_api import get_toon_names_threaded, invalidate_port_to_wid_cache, clear_stale_names


# ── Custom Widgets ─────────────────────────────────────────────────────────


class SmoothProgressBar(QWidget):
    """Keep-alive progress bar painted with sub-pixel precision."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._progress = 0.0  # 0.0 to 1.0
        self._bg_color = QColor("#1a1a1a")
        self._fill_color = QColor("#DC8C28")
        self.setFixedHeight(6)
        self.setMinimumWidth(40)

    def set_progress(self, value: float):
        self._progress = max(0.0, min(1.0, value))
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

    # Emitted from bg thread with (dna, raw_bytes_or_None) — QPixmap built on main thread
    _image_ready = Signal(str, object)

    def __init__(self, slot: int, parent=None):
        super().__init__(parent)
        self._slot    = slot
        self._bg      = QColor("#4a4a4a")
        self._text    = QColor("#ffffff")
        self._pixmap  = None
        self._loading = False
        self._dna     = None
        self.setFixedSize(30, 30)
        self._image_ready.connect(self._on_image_ready)

    def set_colors(self, bg: str, text: str):
        self._bg   = QColor(bg)
        self._text = QColor(text)
        self.update()

    def set_dna(self, dna):
        """Load portrait from Rendition. Pass None to revert to fallback circle."""
        if dna == self._dna:
            return
        self._dna = dna
        if not dna:
            self._pixmap  = None
            self._loading = False
            self.update()
            return
        self._loading = True
        self.update()
        threading.Thread(target=self._fetch, args=(dna,), daemon=True).start()

    def _fetch(self, dna: str):
        """Background thread — network I/O only, no Qt objects constructed here."""
        try:
            import urllib.request
            url = self.RENDITION_URL.format(dna=dna)
            req = urllib.request.Request(url, headers={"User-Agent": "ToonTown MultiTool"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = resp.read()
            self._image_ready.emit(dna, data)
        except Exception as e:
            print(f"[Portrait] Slot {self._slot}: fetch error — {e}")
            self._image_ready.emit(dna, None)

    @Slot(str, object)
    def _on_image_ready(self, dna: str, data):
        """Main thread — safe to construct QPixmap here."""
        if dna != self._dna:
            return
        self._loading = False
        if data:
            pm = QPixmap()
            if pm.loadFromData(data):
                self._pixmap = pm.scaled(30, 30, Qt.KeepAspectRatio, Qt.SmoothTransformation)
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
        r  = min(cx, cy) - 0.5

        # Always draw colored circle background first
        p.setPen(Qt.NoPen)
        p.setBrush(self._bg)
        p.drawEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))

        if self._pixmap and not self._pixmap.isNull():
            path = QPainterPath()
            path.addEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))
            p.setClipPath(path)
            p.drawPixmap(0, 0, self._pixmap)
            p.setClipping(False)
        else:
            font = QFont()
            font.setPixelSize(12)
            font.setBold(True)
            if self._loading:
                p.setPen(QColor(180, 180, 180))
                font.setPixelSize(10)
                p.setFont(font)
                p.drawText(self.rect(), Qt.AlignCenter, "…")
            else:
                p.setFont(font)
                p.setPen(self._text)
                p.drawText(self.rect(), Qt.AlignCenter, str(self._slot))
        p.end()

class PulsingDot(QWidget):
    """Animated status dot — breathes with a soft glow when in 'active' state."""

    def __init__(self, size=10, parent=None):
        super().__init__(parent)
        self._dot_size = size
        # Extra space around the dot for the glow halo
        self.setFixedSize(size + 8, size + 8)
        self._color = QColor("#555555")
        self._pulse_val = 0.0
        self._pulsing = False

        self._anim = QVariantAnimation()
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setDuration(2800)
        self._anim.setLoopCount(-1)
        self._anim.setEasingCurve(QEasingCurve.Linear)
        self._anim.valueChanged.connect(self._on_pulse)

    def set_state(self, state: str, tooltip: str = ""):
        self.setToolTip(tooltip)
        if state == "active":
            self._color = QColor("#56c856")
            if not self._pulsing:
                self._pulsing = True
                self._anim.start()
        elif state == "found":
            self._color = QColor("#888888")
            self._stop_pulse()
        else:
            self._color = QColor("#555555")
            self._stop_pulse()
        self.update()

    def _stop_pulse(self):
        if self._pulsing:
            self._pulsing = False
            self._anim.stop()
            self._pulse_val = 0.0

    def _on_pulse(self, val):
        # Map linear 0→1 through sin(π*val) to get smooth 0→1→0 per cycle
        import math
        self._pulse_val = math.sin(val * math.pi)
        self.update()

    def paintEvent(self, event):
        from PySide6.QtGui import QRadialGradient

        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)

        cx = self.width() / 2.0
        cy = self.height() / 2.0
        r = self._dot_size / 2.0

        if self._pulsing:
            # Soft outer glow — fades in/out with the pulse
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

            # Core dot — gentle brightness shift (only ~18% lighter at peak)
            core = QColor(self._color).lighter(100 + int(18 * self._pulse_val))
            p.setBrush(core)
        else:
            p.setBrush(QColor(self._color))

        p.drawEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))
        p.end()


class StatusSegmentBar(QWidget):
    """Thin segmented bar — each segment represents a toon slot."""

    # States: 0 = off (no window), 1 = found, 2 = active
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(6)
        self._states = [0, 0, 0, 0]
        self._colors = {0: QColor("#333"), 1: QColor("#555"), 2: QColor("#56c856")}

    def set_states(self, states: list):
        self._states = states[:4]
        self.update()

    def set_colors(self, off: str, found: str, active: str):
        self._colors = {0: QColor(off), 1: QColor(found), 2: QColor(active)}
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)

        w = self.width()
        h = self.height()
        gap = 4
        seg_w = (w - gap * 3) / 4.0

        for i in range(4):
            x = i * (seg_w + gap)
            color = self._colors.get(self._states[i], self._colors[0])
            p.setBrush(color)
            p.drawRoundedRect(QRectF(x, 0, seg_w, h), 2, 2)

        p.end()


class KeepAliveBtn(QPushButton):
    """QPushButton that paints a progress-ring border tracing the rounded rect."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._progress = 0.0
        self._ring_color = QColor(220, 140, 40, 200)

    def set_progress(self, val: float):
        self._progress = max(0.0, min(1.0, val))
        self.update()

    def set_ring_color(self, color: QColor):
        self._ring_color = color
        self.update()

    def paintEvent(self, event):
        # Let the stylesheet render the normal button first
        super().paintEvent(event)
        if self._progress < 0.005:
            return

        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        pen_w = 2.5
        inset = pen_w / 2
        rect = QRectF(inset, inset, self.width() - pen_w, self.height() - pen_w)
        radius = 6.0

        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)

        total_len = path.length()
        draw_len = self._progress * total_len
        skip_len = total_len - draw_len

        pen = QPen(self._ring_color, pen_w)
        pen.setCapStyle(Qt.RoundCap)
        if skip_len > 0.01:
            pen.setDashPattern([draw_len / pen_w, skip_len / pen_w])

        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)
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

        self.setFixedHeight(32)
        self.setMinimumWidth(130)
        self.setCursor(Qt.ArrowCursor)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WA_StyledBackground, False)

        self._refresh_display()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        from PySide6.QtGui import QFont

        rect = QRectF(1, 1, self.width() - 2, self.height() - 2)
        show_arrows = self._enabled and self._count() > 1
        az = self.ARROW_ZONE

        # Fill
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(self._bg))
        p.drawRoundedRect(rect, 6, 6)

        # Arrow zone hover highlights
        if show_arrows and self._hover_zone:
            highlight = QColor(255, 255, 255, 35)
            p.setBrush(highlight)
            p.setPen(Qt.NoPen)
            if self._hover_zone == "left":
                clip = QPainterPath()
                clip.addRoundedRect(rect, 6, 6)
                p.setClipPath(clip)
                p.drawRect(QRectF(1, 1, az, self.height() - 2))
                p.setClipping(False)
            elif self._hover_zone == "right":
                clip = QPainterPath()
                clip.addRoundedRect(rect, 6, 6)
                p.setClipPath(clip)
                p.drawRect(QRectF(self.width() - az - 1, 1, az, self.height() - 2))
                p.setClipping(False)

        # Border
        pen = QPen(QColor(self._border_color), 2)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(rect, 6, 6)

        # Center text (name only, no arrows in string)
        font = QFont()
        font.setPixelSize(12)
        font.setBold(True)
        p.setFont(font)
        p.setPen(QColor(self._text_color))
        text_rect = QRectF(az, 0, self.width() - az * 2, self.height())
        p.drawText(text_rect, Qt.AlignCenter, self._display_text)

        # Draw arrows pinned to edges
        if show_arrows:
            arrow_font = QFont()
            arrow_font.setPixelSize(16)
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

            left_rect = QRectF(4, 0, az - 4, self.height())
            p.setPen(left_color)
            p.drawText(left_rect, Qt.AlignCenter, S("‹", "<"))

            right_rect = QRectF(self.width() - az, 0, az - 4, self.height())
            p.setPen(right_color)
            p.drawText(right_rect, Qt.AlignCenter, S("›", ">"))

        p.end()

    def mousePressEvent(self, event):
        if not self._enabled or self._count() <= 1:
            return
        x = event.position().x() if hasattr(event, 'position') else event.x()
        if x < self.ARROW_ZONE:
            self._prev()
        elif x > self.width() - self.ARROW_ZONE:
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
        if x < self.ARROW_ZONE:
            self._hover_zone = "left"
            self.setCursor(Qt.PointingHandCursor)
            self.setToolTip("Previous movement set")
        elif x > self.width() - self.ARROW_ZONE:
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
            bg = "#555555"
            text = "#999999"
            border_color = "#666666"
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

    def __init__(self, logger=None, settings_manager=None, keymap_manager=None, profile_manager=None, window_manager=None):
        super().__init__()
        self.logger = logger
        self.settings_manager = settings_manager
        self.keymap_manager = keymap_manager
        self.profile_manager = profile_manager
        self.window_manager = window_manager
        self.service_running = False
        self.toon_labels = []       # list of (name_label, status_dot)
        self.slot_badges = []       # list of QLabel badges
        self.toon_buttons = []
        self.chat_buttons = []
        self.keep_alive_buttons = []
        self.ka_progress_bars = []
        self.set_selectors = []     # replaces movement_dropdowns
        self.toon_cards = []
        self.profile_pills = []     # list of QPushButton pills
        self.enabled_toons = [False] * 4
        self.chat_enabled  = [True]  * 4
        self.keep_alive_enabled = [False] * 4
        self.toon_names       = [None] * 4
        self.toon_styles      = [None] * 4
        self.toon_colors      = [None] * 4
        self._refresh_gen     = 0
        self._active_profile  = -1  # no profile active initially
        self._last_window_ids = []

        self._keep_alive_running = False
        self._keep_alive_thread = None
        self._ka_cycle_start = 0.0
        self._ka_cycle_event = threading.Event()
        self._inhibitor_fd = None

        self.key_event_queue = queue.Queue()

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
        self.input_service.window_ids_updated.connect(self.update_toon_controls)
        self._toon_names_ready.connect(self._apply_toon_names)
        self._toon_styles_ready.connect(self._apply_toon_styles)
        self._toon_colors_ready.connect(self._apply_toon_colors)

        self.refresh_timer = QTimer(self)
        self.refresh_timer.setInterval(5000)
        self.refresh_timer.timeout.connect(self._auto_refresh)

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

    def build_ui(self):
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(16, 12, 16, 12)
        outer_layout.setSpacing(0)

        self.outer_card = QFrame()
        outer_card_layout = QVBoxLayout(self.outer_card)
        outer_card_layout.setContentsMargins(16, 16, 16, 16)
        outer_card_layout.setSpacing(10)

        # -- Service controls section --
        self.service_label = QLabel("Service Controls")
        outer_card_layout.addWidget(self.service_label)

        self.toggle_service_button = QPushButton(f"{S(chr(9654), chr(9654))} Start Service")
        self.toggle_service_button.setCheckable(True)
        self.toggle_service_button.clicked.connect(self.toggle_service)
        self.toggle_service_button.setFixedHeight(38)
        outer_card_layout.addWidget(self.toggle_service_button)

        # Segment status bar
        self.segment_bar = StatusSegmentBar()
        outer_card_layout.addWidget(self.segment_bar)

        # Text status (compact, below the bar)
        self.status_label = QLabel("Service idle")
        self.status_label.setAlignment(Qt.AlignLeft)
        outer_card_layout.addWidget(self.status_label)

        # -- Toon config header (label | stretch | pills | refresh) --
        config_row = QHBoxLayout()
        config_row.setSpacing(6)
        self.config_label = QLabel("Toon Configuration")
        config_row.addWidget(self.config_label)
        config_row.addStretch()

        for i in range(5):
            pill = QPushButton(str(i + 1))
            pill.setFixedSize(28, 28)
            pill.setToolTip(f"Load Profile {i+1} (Ctrl+{i+1})")
            pill.clicked.connect(lambda checked, idx=i: self.load_profile(idx))
            self.profile_pills.append(pill)
            config_row.addWidget(pill)

        config_row.addSpacing(4)
        self.refresh_button = QPushButton()
        self.refresh_button.setIcon(make_refresh_icon(14))
        self.refresh_button.setFixedSize(26, 26)
        self.refresh_button.setToolTip("Refresh toon windows and configuration")
        self.refresh_button.clicked.connect(self.manual_refresh)
        config_row.addWidget(self.refresh_button)
        outer_card_layout.addLayout(config_row)


        # -- Toon cards (two-row layout) --
        for i in range(4):
            card = QFrame()
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(12, 10, 12, 10)
            card_layout.setSpacing(8)

            # === Top row: badge + name + pulsing dot ===
            top_row = QHBoxLayout()
            top_row.setSpacing(10)

            badge = ToonPortraitWidget(i + 1)
            self.slot_badges.append(badge)
            top_row.addWidget(badge)

            name_label = QLabel(f"Toon {i + 1}")
            status_dot = PulsingDot(10)
            status_dot.setToolTip("Not Found")
            self.toon_labels.append((name_label, status_dot))
            top_row.addWidget(name_label)
            top_row.addWidget(status_dot)

            top_row.addStretch()
            card_layout.addLayout(top_row)

            # === Bottom row: controls ===
            ctrl_row = QHBoxLayout()
            ctrl_row.setSpacing(8)

            btn = QPushButton("Enable")
            btn.setCheckable(True)
            btn.setFixedHeight(32)
            btn.setFixedWidth(88)
            btn.setToolTip("Enable input broadcasting for this toon")
            btn.clicked.connect(lambda checked, idx=i: self.toggle_toon(idx))
            self.toon_buttons.append(btn)
            ctrl_row.addWidget(btn)

            ka_btn = KeepAliveBtn()
            ka_btn.setCheckable(True)
            ka_btn.setChecked(False)
            ka_btn.setFixedHeight(32)
            ka_btn.setFixedWidth(32)
            ka_btn.setIcon(make_mouse_icon(14))
            ka_btn.setToolTip("Toggle keep-alive for this toon")
            ka_btn.clicked.connect(lambda checked, idx=i: self.toggle_keep_alive(idx))
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

            # Order: Enable | Chat | KeepAlive | progress bar | stretch | selector
            ctrl_row.addWidget(chat_btn)
            ctrl_row.addWidget(ka_btn)

            # Keep-alive progress bar (sub-pixel smooth painting)
            ka_bar = SmoothProgressBar()
            self.ka_progress_bars.append(ka_bar)
            ctrl_row.addWidget(ka_bar, 1)  # stretch factor so it fills available space

            # Movement set selector (horizontal color-coded widget)
            selector = SetSelectorWidget(self.keymap_manager)
            selector.setFixedHeight(28)
            selector.setToolTip("Movement set for this toon")
            selector.index_changed.connect(lambda _, idx=i: self._autosave_active_profile())
            self.set_selectors.append(selector)
            ctrl_row.addWidget(selector)

            card_layout.addLayout(ctrl_row)

            self.toon_cards.append(card)
            outer_card_layout.addWidget(card)

        outer_card_layout.addStretch()
        outer_layout.addWidget(self.outer_card)
        outer_layout.addStretch()

        self.update_service_button_style()
        self.update_status_label()

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

        enabled = profile.get("enabled_toons", [False] * 4)
        modes = profile.get("movement_modes", ["Default"] * 4)

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
        for i, pill in enumerate(self.profile_pills):
            active = i == self._active_profile
            if active:
                pill.setStyleSheet(f"""
                    QPushButton {{
                        background-color: {c['accent_blue_btn']};
                        color: white;
                        border: 2px solid {c['accent_blue_btn_border']};
                        border-radius: 14px;
                        font-size: 11px;
                        font-weight: bold;
                        padding: 0px;
                        margin: 0px;
                        text-align: center;
                    }}
                    QPushButton:hover {{
                        background-color: {c['accent_blue_btn_hover']};
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
                        border: 1px solid {c['accent_blue']};
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

        self.service_label.setStyleSheet(
            f"font-size: 12px; font-weight: bold; color: {c['text_secondary']}; background: none; border: none;"
        )
        self.config_label.setStyleSheet(
            f"font-size: 12px; font-weight: bold; color: {c['text_secondary']}; background: none; border: none; margin-top: 4px;"
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

        # Segment bar colors
        self.segment_bar.set_colors(c['segment_off'], c['segment_found'], c['segment_active'])

        # Toon cards
        for i, card in enumerate(self.toon_cards):
            card.setStyleSheet(f"""
                QFrame {{
                    background-color: {c['bg_card_inner']};
                    border-radius: 8px;
                    border: 1px solid {c['border_muted']};
                }}
            """)
            name_label, status_dot = self.toon_labels[i]
            name_label.setStyleSheet(
                f"font-size: 14px; font-weight: bold; color: {c['text_primary']}; background: none; border: none;"
            )

        self.apply_all_visual_states()
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

        slot_colors = self._slot_colors(c)
        active = window_available and self.enabled_toons[index] and self.service_running
        if active:
            status_dot.set_state("active", "Connected")
        elif window_available:
            status_dot.set_state("found", "Found — not enabled")
        else:
            status_dot.set_state("off", "Not Found")

        # -- Slot badge --
        if window_available:
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
                    color: white; font-size: 12px; font-weight: bold;
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
                    color: white;
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

    def _apply_keep_alive_btn_style(self, index, c):
        ka_btn = self.keep_alive_buttons[index]
        ka_btn.setEnabled(True)
        if self.keep_alive_enabled[index]:
            ka_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {c['accent_orange']};
                    color: white;
                    border: 2px solid {c['accent_orange_border']};
                    border-radius: 6px;
                }}
                QPushButton:hover {{
                    background-color: {c['accent_orange_hover']};
                    border: 2px solid {c['accent_orange_border']};
                }}
            """)
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
        val = (math.sin(self._glow_phase * math.pi * 2 / 3.0) + 1.0) / 2.0

        # Keep-alive button glow (warm orange) + progress ring
        ka_alpha = int(30 + 50 * val)
        delay = self._get_keep_alive_delay()
        elapsed = time.monotonic() - self._ka_cycle_start if self._ka_cycle_start else 0
        ring_progress = min(1.0, elapsed / delay) if delay > 0 else 0.0

        for i in range(4):
            ka_btn = self.keep_alive_buttons[i]
            if self.keep_alive_enabled[i]:
                shadow = QGraphicsDropShadowEffect(ka_btn)
                shadow.setColor(QColor(220, 140, 40, ka_alpha))
                shadow.setBlurRadius(12 + 6 * val)
                shadow.setOffset(0, 0)
                ka_btn.setGraphicsEffect(shadow)
                ka_btn.set_progress(ring_progress)
            else:
                ka_btn.setGraphicsEffect(None)
                ka_btn.set_progress(0.0)

        # Service button glow (red pulse when running)
        if self.service_running:
            svc_alpha = int(20 + 40 * val)
            shadow = QGraphicsDropShadowEffect(self.toggle_service_button)
            shadow.setColor(QColor(200, 60, 60, svc_alpha))
            shadow.setBlurRadius(14 + 8 * val)
            shadow.setOffset(0, 0)
            self.toggle_service_button.setGraphicsEffect(shadow)
        else:
            self.toggle_service_button.setGraphicsEffect(None)

    def _update_glow_timer(self):
        needs_glow = any(self.keep_alive_enabled) or self.service_running
        needs_bars = any(self.keep_alive_enabled)

        if needs_glow and not self._glow_timer.isActive():
            self._glow_phase = 0.0
            self._glow_timer.start()
        elif not needs_glow and self._glow_timer.isActive():
            self._glow_timer.stop()
            for i in range(4):
                self.keep_alive_buttons[i].setGraphicsEffect(None)
                self.keep_alive_buttons[i].set_progress(0.0)
            self.toggle_service_button.setGraphicsEffect(None)

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
        progress = min(1.0, elapsed / delay) if delay > 0 else 0.0

        for i in range(4):
            if i < len(self.ka_progress_bars):
                bar = self.ka_progress_bars[i]
                if self.keep_alive_enabled[i]:
                    bar.set_progress(progress)
                else:
                    bar.set_progress(0.0)

    # ── Service button style ───────────────────────────────────────────────

    def update_service_button_style(self):
        c = self._c()
        if self.service_running:
            self.toggle_service_button.setText(f"{S(chr(9632), chr(9632))} Stop Service")
            self.toggle_service_button.setToolTip("Stop the multitoon input service")
            self.toggle_service_button.setStyleSheet(f"""
                QPushButton {{
                    background-color: {c['accent_red']};
                    color: white; font-weight: bold;
                    border: 2px solid {c['accent_red_border']};
                    border-radius: 6px;
                }}
                QPushButton:hover {{
                    background-color: {c['accent_red_hover']};
                    border: 2px solid {c['accent_red_hover_border']};
                }}
            """)
        else:
            self.toggle_service_button.setText(f"{S(chr(9654), chr(9654))} Start Service")
            self.toggle_service_button.setToolTip("Start the multitoon input service")
            self.toggle_service_button.setStyleSheet(f"""
                QPushButton {{
                    background-color: {c['accent_blue_btn']};
                    color: white; font-weight: bold;
                    border: 2px solid {c['accent_blue_btn_border']};
                    border-radius: 6px;
                }}
                QPushButton:hover {{
                    background-color: {c['accent_blue_btn_hover']};
                    border: 2px solid {c['accent_blue_btn_border']};
                }}
            """)

    def apply_all_visual_states(self):
        for i in range(4):
            self.apply_visual_state(i)

    # ── Status label + segment bar ─────────────────────────────────────────

    def update_status_label(self):
        c = self._c()
        count = sum(self.enabled_toons)

        # Update segment bar states
        segments = []
        wids = self.window_manager.ttr_window_ids if hasattr(self, 'input_service') else []
        for i in range(4):
            window_available = i < len(wids)
            if window_available and self.enabled_toons[i] and self.service_running:
                segments.append(2)  # active
            elif window_available:
                segments.append(1)  # found
            else:
                segments.append(0)  # off
        self.segment_bar.set_states(segments)

        # Update text status (compact style)
        base = "QLabel { font-size: 11px; font-weight: 500; border-radius: 4px; padding: 4px 10px; "
        if self.service_running and count > 0:
            self.status_label.setText(f"{S('✅', '✔')} Sending input to {count} toon{'s' if count != 1 else ''}")
            self.status_label.setStyleSheet(base + f"background-color: {c['status_success_bg']}; color: {c['status_success_text']}; border-left: 4px solid {c['status_success_border']}; }}")
        elif self.service_running:
            self.status_label.setText(f"{S('⚠️', '⚠')} Service running — no toons enabled")
            self.status_label.setStyleSheet(base + f"background-color: {c['status_warning_bg']}; color: {c['status_warning_text']}; border-left: 4px solid {c['status_warning_border']}; }}")
        else:
            self.status_label.setText(f"{S('⏸️', '◼')} Service idle")
            self.status_label.setStyleSheet(base + f"background-color: {c['status_idle_bg']}; color: {c['status_idle_text']}; border-left: 4px solid {c['status_idle_border']}; }}")

    # ── Name fetching ──────────────────────────────────────────────────────

    def _fetch_names_if_enabled(self, num_slots: int):
        if self.settings_manager and self.settings_manager.get("enable_companion_app", True):
            self._refresh_gen += 1
            gen = self._refresh_gen
            def _callback(names, styles, colors):
                if gen == self._refresh_gen:
                    self._on_toon_names_received(names, styles, colors)
            get_toon_names_threaded(num_slots, _callback,
                                    list(self.window_manager.ttr_window_ids))

    def manual_refresh(self):
        invalidate_port_to_wid_cache()
        self.input_service.window_manager.assign_windows()
        self._fetch_names_if_enabled(4)
        self.log("[Service] Manual refresh triggered.")

    def _auto_refresh(self):
        self.input_service.window_manager.assign_windows()
        self._fetch_names_if_enabled(4)

    # ── Service lifecycle ──────────────────────────────────────────────────

    def toggle_service(self):
        self.service_running = not self.service_running
        if self.service_running:
            self._start_service_internal()
        else:
            self.input_service.stop()
            self.refresh_timer.stop()
            self.disable_all_toon_controls()
            self.log("[Service] Multitoon service stopped.")
        self.update_service_button_style()
        self._update_glow_timer()

    def _start_service_internal(self):
        self.input_service.start()
        self.log("[Service] Multitoon service started.")
        for i in range(4):
            if i < len(self.window_manager.ttr_window_ids):
                self.enabled_toons[i] = True
                self.chat_enabled[i]  = True
                self.toon_buttons[i].setChecked(True)
                self.chat_buttons[i].setChecked(True)
                self.apply_visual_state(i)
        self.update_status_label()
        self.refresh_timer.start()
        self._fetch_names_if_enabled(len(self.window_manager.ttr_window_ids))

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
            self.enabled_toons[i] = False
            self.chat_enabled[i]  = True
            self.keep_alive_enabled[i] = False
            self.toon_names[i]    = None
            self.toon_styles[i]   = None
            self.toon_colors[i]   = None
            if i < len(self.slot_badges):
                self.slot_badges[i].set_dna(None)
            self.apply_visual_state(i)
        self._update_glow_timer()
        self._refresh_toon_name_labels()
        self.update_status_label()

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
        self.apply_visual_state(index)
        self.update_status_label()
        self._autosave_active_profile()

    def toggle_chat(self, index):
        self.chat_enabled[index] = not self.chat_enabled[index]
        self.chat_buttons[index].setChecked(self.chat_enabled[index])
        self.apply_visual_state(index)

    def toggle_keep_alive(self, index):
        self.keep_alive_enabled[index] = not self.keep_alive_enabled[index]
        self.keep_alive_buttons[index].setChecked(self.keep_alive_enabled[index])
        self.apply_visual_state(index)
        self._update_glow_timer()
        if any(self.keep_alive_enabled):
            self._reset_ka_cycle()
            self._start_keep_alive()
        else:
            self._stop_keep_alive()

    def set_toon_enabled(self, index, enabled: bool):
        self.enabled_toons[index] = enabled
        self.toon_buttons[index].setChecked(enabled)
        self.apply_visual_state(index)
        self.update_status_label()

    # ── Window update handler ──────────────────────────────────────────────

    def update_toon_controls(self, window_ids):
        ids_changed = window_ids != self._last_window_ids
        self._last_window_ids = list(window_ids)

        if ids_changed:
            invalidate_port_to_wid_cache()
            clear_stale_names(window_ids)
            self.toon_names = [None] * 4
            self._refresh_toon_name_labels()

        for i in range(4):
            if i >= len(window_ids):
                self.enabled_toons[i] = False
                self.chat_enabled[i]  = True
                self.keep_alive_enabled[i] = False
                self.toon_buttons[i].setChecked(False)
                self.chat_buttons[i].setChecked(True)
                self.keep_alive_buttons[i].setChecked(False)
            elif self.service_running and not self.enabled_toons[i]:
                self.enabled_toons[i] = True
                self.toon_buttons[i].setChecked(True)
            self.apply_visual_state(i)
        self.update_status_label()
        self._fetch_names_if_enabled(len(window_ids))
        self._update_glow_timer()
        if not any(self.keep_alive_enabled):
            self._stop_keep_alive()

    # ── Name handling ──────────────────────────────────────────────────────

    def _on_toon_names_received(self, names: list, styles: list, colors: list):
        self._toon_names_ready.emit(list(names))
        self._toon_styles_ready.emit(list(styles))
        self._toon_colors_ready.emit(list(colors))

    @Slot(list)
    def _apply_toon_names(self, names: list):
        for i, name in enumerate(names):
            self.toon_names[i] = name
        self._refresh_toon_name_labels()

    @Slot(list)
    def _apply_toon_styles(self, styles: list):
        for i, style in enumerate(styles):
            if style is not None and style != self.toon_styles[i]:
                self.toon_styles[i] = style
                if i < len(self.slot_badges):
                    self.slot_badges[i].set_dna(style)

    @Slot(list)
    def _apply_toon_colors(self, colors: list):
        for i, color in enumerate(colors):
            if color is not None and i < len(self.slot_badges):
                hex_color = f"#{color}" if not color.startswith("#") else color
                lightened = _lighten_hex(hex_color, 0.25)
                self.slot_badges[i].set_colors(lightened, "#ffffff")

    @Slot()
    def _refresh_toon_name_labels(self):
        c = self._c()
        for i, (name_label, _) in enumerate(self.toon_labels):
            display = self.toon_names[i] if self.toon_names[i] else f"Toon {i + 1}"
            name_label.setText(display)
            name_label.setStyleSheet(
                f"font-size: 14px; font-weight: bold; color: {c['text_primary']}; background: none; border: none;"
            )

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

    # ── Sleep inhibitor ───────────────────────────────────────────────────

    def _acquire_sleep_inhibitor(self):
        """Hold a systemd sleep/idle inhibitor lock for the duration of keep-alive.
        Works on KDE, GNOME, or any systemd-based distro with no DE at all.
        The fd is owned by this process — released automatically on crash too."""
        if self._inhibitor_fd is not None:
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
        self._release_sleep_inhibitor()
        for i in range(4):
            self.keep_alive_buttons[i].set_progress(0.0)
            if i < len(self.ka_progress_bars):
                self.ka_progress_bars[i].set_progress(0.0)

    def _get_keep_alive_delay(self) -> float:
        if not self.settings_manager:
            return 60
        delay_str = self.settings_manager.get("keep_alive_delay", "30 sec")
        return {
            "Rapid Fire": 0.25, "1 sec": 1, "5 sec": 5, "10 sec": 10, "30 sec": 30,
            "1 min": 60, "3 min": 180, "5 min": 300, "10 min": 600
        }.get(delay_str, 60)

    def _run_keep_alive_loop(self):
        try:
            while self._keep_alive_running:
                delay = self._get_keep_alive_delay()
                # Wait for the delay, but wake early if cycle is reset
                self._ka_cycle_event.wait(timeout=delay)
                if self._ka_cycle_event.is_set():
                    # Cycle was reset or stop requested — clear and re-loop
                    self._ka_cycle_event.clear()
                    if not self._keep_alive_running:
                        break
                    continue
                if not self._keep_alive_running:
                    break

                # Resolve the action to Set 1's raw key
                action = self.settings_manager.get("keep_alive_action", "jump") if self.settings_manager else "jump"
                key = None
                if self.keymap_manager:
                    key = self.keymap_manager.get_key_for_direction(0, action)
                if not key:
                    self._ka_cycle_start = time.monotonic()
                    continue

                for i in range(4):
                    if (self.keep_alive_enabled[i]
                            and i < len(self.window_manager.ttr_window_ids)):
                        self.input_service.send_keep_alive_to_window(
                            self.window_manager.ttr_window_ids[i], key
                        )

                action_labels = {"jump": "Jump", "book": "Book", "up": "Move Forward"}
                label = action_labels.get(action, action)
                self.log(f"[KeepAlive] Sent '{label}' ({key}) to {sum(self.keep_alive_enabled)} toon(s)")
                self._ka_cycle_start = time.monotonic()
        except Exception as e:
            self.log(f"[KeepAlive] Error: {e}")

    def log(self, msg):
        if self.logger:
            self.logger.append_log(msg)
        else:
            print(msg)