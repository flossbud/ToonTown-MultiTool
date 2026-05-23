"""Single account tile for the Launch tab grid. State-aware primary button
swaps label, color, and enabled flag based on the account's current
LoginState. Emits a distinct signal per state-specific click."""
from __future__ import annotations

from PySide6.QtCore import (
    QAbstractAnimation, Property, QByteArray, QPropertyAnimation, Qt, QSize,
    QTimer, Signal,
)
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QStyle,
    QStyleOption, QVBoxLayout, QWidget,
)

import utils.motion as motion
from utils.shared_widgets import PulsingDot
from utils.theme_manager import get_theme_colors, make_edit_icon, make_trash_icon
from utils.widgets.chip_button import ChipButton, QuietChipButton


def _hamburger_icon(color: str, size: int = 12) -> QIcon:
    """Three-line 'expand details' icon. Qt's text engine can't render the
    `☰` glyph at small button sizes under our stylesheet, so we rasterize."""
    svg_bytes = QByteArray((
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"'
        f' fill="none" stroke="{color}" stroke-width="2.5"'
        f' stroke-linecap="round" stroke-linejoin="round">'
        f'<line x1="4" y1="7" x2="20" y2="7"/>'
        f'<line x1="4" y1="12" x2="20" y2="12"/>'
        f'<line x1="4" y1="17" x2="20" y2="17"/>'
        f'</svg>'
    ).encode("utf-8"))
    renderer = QSvgRenderer(svg_bytes)
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    painter = QPainter(pm)
    renderer.render(painter)
    painter.end()
    return QIcon(pm)


# Status -> (bg_token_key, fg_token_key, label)
_STATUS_VISUALS = {
    "logging_in": ("status_warning_bg", "status_warning_text", "Logging in…"),
    "launching":  ("status_warning_bg", "status_warning_text", "Launching…"),
    "queued":     ("status_warning_bg", "status_warning_text", "In queue"),
    "need_2fa":   ("status_info_bg",    "status_info_text",    "2FA Required"),
    "running":    ("status_success_bg", "status_success_text", "Running"),
    "failed":     ("status_error_bg",   "status_error_text",   ""),  # set per-message
}

# Status -> (button_label, button_bg, enabled, signal_name)
_BUTTON_MAP = {
    "idle":       ("Launch",       "#0077ff", True,  "launch_clicked"),
    "logging_in": ("Logging in…",  "rgba(255,255,255,0.06)", False, None),
    "launching":  ("Launching…",   "rgba(255,255,255,0.06)", False, None),
    "queued":     ("Cancel",       "#b34848", True,  "cancel_clicked"),
    "need_2fa":   ("Enter 2FA →",  "#C87EE8", True,  "enter_2fa_clicked"),
    "running":    ("Quit",         "#b34848", True,  "quit_clicked"),
    "failed":     ("Retry",        "#c84e34", True,  "retry_clicked"),
}


def summarize_error(raw_message: str) -> str:
    """Curate a band-sized summary from a raw error string.
    Pure function so it's straightforward to test."""
    if not raw_message:
        return "Failed"
    lower = raw_message.lower()
    if "401" in lower or "bad creds" in lower or "incorrect username or password" in lower:
        return "Bad credentials"
    if "queue" in lower and ("timeout" in lower or "timed out" in lower):
        return "Queue timed out"
    if "network" in lower or "connection" in lower or "timeout" in lower:
        return "Network error"
    if "engine not found" in lower or "ttrengine" in lower:
        return "Engine not found"
    if "not installed" in lower:
        return "Runtime missing"
    if "wine" in lower or "proton" in lower or "umu" in lower:
        return "Runtime error"
    # Default: truncate to ~32 chars.
    return (raw_message[:32] + "…") if len(raw_message) > 32 else raw_message


class AccountTile(QFrame):
    NORMAL_SCALE = 1.0
    PRESS_SCALE = 0.96  # gentler than ChipButton's 0.88 — tile is a larger surface
    DURATION_PRESS_MS = 130

    launch_clicked       = Signal()
    quit_clicked         = Signal()
    cancel_clicked       = Signal()
    retry_clicked        = Signal()
    enter_2fa_clicked    = Signal()
    edit_clicked         = Signal()
    delete_clicked       = Signal()
    expand_error_clicked = Signal()

    def __init__(self, game: str, slot_index: int, parent: QWidget | None = None):
        super().__init__(parent)
        self._game = game
        self._slot_index = slot_index
        self._state = "idle"
        self.raw_error_message = ""
        self._paint_scale = 1.0
        self._tile_opacity = 1.0
        self._is_pressed = False
        self._scale_anim: QPropertyAnimation | None = None

        self.setObjectName("account_tile")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.setMinimumHeight(130)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(8)

        # Header row
        head = QHBoxLayout()
        head.setSpacing(8)
        self.badge = QLabel(str(slot_index + 1))
        self.badge.setFixedSize(22, 22)
        self.badge.setAlignment(Qt.AlignCenter)
        head.addWidget(self.badge)
        self.name_label = QLabel("")
        self.name_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        head.addWidget(self.name_label)
        outer.addLayout(head)

        # Status band (hidden by default)
        self.status_band = QWidget()
        self.status_band.setVisible(False)
        band_lay = QHBoxLayout(self.status_band)
        band_lay.setContentsMargins(9, 5, 9, 5)
        band_lay.setSpacing(6)
        self.status_dot = PulsingDot(8)
        self.status_dot.setVisible(False)
        band_lay.addWidget(self.status_dot)
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("font-size: 11px; font-weight: 600;")
        band_lay.addWidget(self.status_label, 1)
        # expand_btn stays a plain QPushButton: it's a tiny status-band
        # chevron that doesn't need the press-scale feedback the action-row
        # buttons get from QuietChipButton.
        self.expand_btn = QPushButton()
        self.expand_btn.setFixedSize(20, 20)
        self.expand_btn.setIconSize(QSize(12, 12))
        self.expand_btn.setVisible(False)
        self.expand_btn.setStyleSheet(
            "QPushButton { background: transparent; border: none; color: inherit; }"
        )
        self.expand_btn.clicked.connect(self.expand_error_clicked.emit)
        band_lay.addWidget(self.expand_btn)
        outer.addWidget(self.status_band)

        # Action row
        acts = QHBoxLayout()
        acts.setSpacing(6)
        self.primary_button = QuietChipButton()
        self.primary_button.setText("Launch")
        self.primary_button.setMinimumHeight(28)
        self.primary_button.setCursor(Qt.PointingHandCursor)
        acts.addWidget(self.primary_button, 1)
        _muted = QColor("#8a9bb8")
        self.edit_btn = QuietChipButton()
        self.edit_btn.setIcon(make_edit_icon(14, _muted))
        self.edit_btn.setIconSize(QSize(14, 14))
        self.edit_btn.setFixedSize(26, 26)
        self.edit_btn.setCursor(Qt.PointingHandCursor)
        self.edit_btn.clicked.connect(self.edit_clicked.emit)
        acts.addWidget(self.edit_btn)
        self.delete_btn = QuietChipButton()
        self.delete_btn.setIcon(make_trash_icon(14, _muted))
        self.delete_btn.setIconSize(QSize(14, 14))
        self.delete_btn.setFixedSize(26, 26)
        self.delete_btn.setCursor(Qt.PointingHandCursor)
        self.delete_btn.clicked.connect(self.delete_clicked.emit)
        acts.addWidget(self.delete_btn)
        outer.addLayout(acts)

        # State cache for Task 4's _refresh_status_band implementation. `_current_theme`
        # is also used here by apply_theme; the state/message fields are set ahead of
        # time so the Task 3 stub doesn't need a guard.
        self._current_theme = get_theme_colors(True)  # dark default; overridden immediately by apply_theme
        self._current_state = "idle"
        self._current_status_message = ""

        self._connected_signal = None
        self._apply_button_for_state("idle")
        self.apply_theme(self._current_theme)

    def apply_theme(self, c: dict) -> None:
        """Rebuild every QSS string from the theme dict `c`. Called by the
        constructor (dark default) and by LaunchSection.apply_theme on
        every theme switch."""
        self._current_theme = c
        self.setStyleSheet(
            "QFrame#account_tile {"
            f" background: {c['bg_card_inner']};"
            " border-radius: 10px;"
            f" border: 1px solid {c['border_card']};"
            "}"
            "QFrame#account_tile:hover {"
            f" background: {c['bg_card_inner_hover']};"
            "}"
        )
        badge_bg = (
            c["game_pill_ttr"] if self._game == "ttr"
            else c["game_pill_cc"]
        )
        self.badge.setStyleSheet(
            f"background: {badge_bg}; color: {c['text_on_accent']};"
            " border-radius: 11px; min-width: 22px; min-height: 22px;"
            " font-weight: 700; font-size: 11px;"
        )
        self.name_label.setStyleSheet(
            f"color: {c['text_primary']}; font-weight: 600; font-size: 13px;"
            " background: transparent;"
        )
        chip_qss = (
            "QToolButton { background: transparent;"
            f" border: 1px solid {c['border_muted']};"
            f" color: {c['text_muted']};"
            " border-radius: 6px; }"
            "QToolButton:hover {"
            f" background: {c['bg_card_inner_hover']};"
            f" color: {c['text_secondary']};"
            "}"
        )
        self.edit_btn.setStyleSheet(chip_qss)
        self.delete_btn.setStyleSheet(chip_qss)
        # Re-apply status band styling for the current state (no-op if idle).
        self._refresh_status_band()

    def _refresh_status_band(self) -> None:
        """Re-apply the status band QSS for the current state, used by
        apply_theme() on theme switch."""
        if self._current_state and self._current_state != "idle":
            # Re-run set_state with the cached state + message so band
            # styling re-resolves against the new theme dict.
            self.set_state(self._current_state, self._current_status_message)

    # ── public API ─────────────────────────────────────────────────

    def set_account(self, label: str, username: str, slot_index: int) -> None:
        self._slot_index = slot_index
        self.badge.setText(str(slot_index + 1))
        display = label or username or f"Account {slot_index + 1}"
        self.name_label.setText(display)

    def set_state(self, state: str, message: str = "", raw_message: str = "") -> None:
        self._current_state = state
        self._current_status_message = message
        self._state = state
        if state == "failed" and raw_message:
            self.raw_error_message = raw_message
        elif state == "failed":
            self.raw_error_message = message
        self._apply_status_band(state, message)
        self._apply_button_for_state(state)

    # ── internals ──────────────────────────────────────────────────

    def _apply_status_band(self, state: str, message: str) -> None:
        if state == "idle" or state not in _STATUS_VISUALS:
            self.status_band.setVisible(False)
            return
        bg_key, fg_key, default_label = _STATUS_VISUALS[state]
        c = self._current_theme
        bg = c[bg_key]
        fg = c[fg_key]
        self.status_band.setStyleSheet(
            f"background: {bg}; border-radius: 5px;"
            f" color: {fg};"  # written on band so token appears in status_band.styleSheet() for tests
        )
        self.status_label.setStyleSheet(f"font-size: 11px; font-weight: 600; color: {fg};")
        if state == "failed":
            text = "⚠ " + summarize_error(message)
        elif state == "queued" and message:
            text = f"In queue · {message}"
        elif message:
            text = (default_label + " · " + message) if default_label else message
        else:
            text = default_label
        self.status_label.setText(text)
        self.status_band.setVisible(True)
        self.status_dot.setVisible(state == "running")
        if state == "running":
            self.status_dot.set_color("#56c856", pulse=True)
        self.expand_btn.setVisible(state == "failed")
        if state == "failed":
            self.expand_btn.setIcon(_hamburger_icon(fg, 12))
        self.expand_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; border: none; color: {fg}; }}"
        )

    def _apply_button_for_state(self, state: str) -> None:
        label, bg, enabled, signal_name = _BUTTON_MAP.get(state, _BUTTON_MAP["idle"])
        self.primary_button.setText(label)
        self.primary_button.setEnabled(enabled)
        text_color = "white" if enabled else "#5d6a82"
        self.primary_button.setStyleSheet(
            f"QToolButton {{"
            f" background: {bg}; color: {text_color}; border: none;"
            f" border-radius: 6px; padding: 7px; font-size: 12px; font-weight: 600;"
            f"}}"
            f"QToolButton:disabled {{ background: rgba(255,255,255,0.06); color: #5d6a82; }}"
        )
        # Disconnect prior handler (if any) before connecting the new one.
        if self._connected_signal is not None:
            try:
                self.primary_button.clicked.disconnect()
            except (RuntimeError, TypeError):
                pass
        if signal_name is not None:
            sig = getattr(self, signal_name)
            self.primary_button.clicked.connect(sig.emit)
        self._connected_signal = signal_name

    # ── paint_scale Qt property ──────────────────────────────────────────
    def _get_paint_scale(self) -> float:
        return self._paint_scale

    def _set_paint_scale(self, value: float) -> None:
        self._paint_scale = float(value)
        self.update()

    paint_scale = Property(float, _get_paint_scale, _set_paint_scale)

    # ── tile_opacity Qt property ─────────────────────────────────────────
    def _get_tile_opacity(self) -> float:
        return self._tile_opacity

    def _set_tile_opacity(self, value: float) -> None:
        self._tile_opacity = float(value)
        self.update()

    tile_opacity = Property(float, _get_tile_opacity, _set_tile_opacity)

    # ── Press state ──────────────────────────────────────────────────────
    def _target_scale(self) -> float:
        return self.PRESS_SCALE if self._is_pressed else self.NORMAL_SCALE

    def _animate_to(self, target: float) -> None:
        if motion.is_reduced():
            self._set_paint_scale(target)
            return
        if (
            self._scale_anim is not None
            and self._scale_anim.state() == QAbstractAnimation.Running
        ):
            self._scale_anim.stop()
        raw = self.DURATION_PRESS_MS * motion._TEST_DURATION_SCALE
        duration = 0 if raw == 0.0 else max(1, int(raw))
        anim = QPropertyAnimation(self, b"paint_scale")
        anim.setDuration(duration)
        anim.setEasingCurve(motion.EASE_STANDARD)
        anim.setStartValue(self._paint_scale)
        anim.setEndValue(target)
        anim.finished.connect(lambda t=target: self._set_paint_scale(t))
        self._scale_anim = anim
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(anim.start)
        timer.start(0)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and not self._is_pressed:
            self._is_pressed = True
            self._animate_to(self._target_scale())
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self._is_pressed:
            self._is_pressed = False
            self._animate_to(self._target_scale())
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event) -> None:
        # Reset press state when the cursor leaves while still held. Qt
        # does not deliver mouseReleaseEvent to a widget when the release
        # happens outside its bounds (and we have not grabbed the mouse),
        # so without this reset a press-then-drag-out leaves the tile
        # stuck at PRESS_SCALE. Mirrors the leaveEvent pattern at
        # utils/widgets/chip_button.py:133-135.
        if self._is_pressed:
            self._is_pressed = False
            self._animate_to(self.NORMAL_SCALE)
        super().leaveEvent(event)

    # ── Painting: scale the entire tile via QPainter ────────────────────
    def paintEvent(self, event) -> None:
        # Fast path: at NORMAL_SCALE with full opacity we have nothing to
        # transform; let QFrame's own paintEvent handle the QSS background
        # and border.
        if self._paint_scale == 1.0 and self._tile_opacity == 1.0:
            super().paintEvent(event)
            return
        # During the press animation OR a reveal fade we cannot delegate
        # to super().paintEvent through our painter — QFrame.paintEvent
        # grabs its own QPainter on the same paint device and Qt rejects
        # the recursive begin(). So we render the QSS-styled background
        # manually via QStyle.PE_Widget, with the painter pre-scaled
        # around the widget center and tinted by tile_opacity. Child
        # widgets (buttons, labels) paint themselves through Qt's normal
        # widget tree and are NOT scaled or opacity-tinted by this
        # transform — that mirrors the same tradeoff ChipButton accepts.
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        p.setOpacity(self._tile_opacity)
        if self._paint_scale != 1.0:
            cx, cy = self.width() / 2.0, self.height() / 2.0
            p.translate(cx, cy)
            p.scale(self._paint_scale, self._paint_scale)
            p.translate(-cx, -cy)
        opt = QStyleOption()
        opt.initFrom(self)
        self.style().drawPrimitive(QStyle.PE_Widget, opt, p, self)
