"""Single account tile for the Launch tab grid (v2 pinwheel skin).

A FIXED 336x96 two-row tile: row 1 carries the primary-toon portrait, the
toon/account identity, and an inline status pill; row 2 carries the
state-aware primary button plus the edit/delete controls. The primary button
swaps label, color, and enabled flag based on the account's current
LoginState and emits a distinct signal per state-specific click. Only the
layout and visuals changed in the reskin - the state machine, click signals,
error summarization, and press-scale animation are preserved."""
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
from utils.color_math import alpha as _alpha, with_alpha
from utils.shared_widgets import ElidingLabel, PulsingDot
from utils.theme_manager import (
    V2_ACCENTS, get_theme_colors, get_v2_tokens, make_edit_icon, make_trash_icon,
)
from utils.widgets.chip_button import QuietChipButton
from utils.widgets.primary_toon_slot import PrimaryToonSlot


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
    "loading":    ("status_info_bg",    "status_info_text",    "Loading…"),
    "queued":     ("status_warning_bg", "status_warning_text", "In queue"),
    "need_2fa":   ("status_info_bg",    "status_info_text",    "2FA Required"),
    "running":    ("status_success_bg", "status_success_text", "Running"),
    "failed":     ("status_error_bg",   "status_error_text",   ""),  # set per-message
}

# Status -> (button_label, button_fill, enabled, signal_name)
# A fill of None means "use the game accent" (resolved per-instance in
# _apply_button_for_state, since the accent depends on self._game).
_BUTTON_MAP = {
    "idle":       ("Launch",       None,      True,  "launch_clicked"),
    "logging_in": ("Logging in…",  None,      False, None),
    "launching":  ("Launching…",   None,      False, None),
    "loading":    ("Quit",         "#e05252", True,  "quit_clicked"),
    "queued":     ("Cancel",       "#e05252", True,  "cancel_clicked"),
    "need_2fa":   ("Enter 2FA →",  "#a763d8", True,  "enter_2fa_clicked"),
    "running":    ("Quit",         "#e05252", True,  "quit_clicked"),
    "failed":     ("Retry",        "#c84e34", True,  "retry_clicked"),
}


def summarize_error(raw_message: str) -> str:
    """Curate a pill-sized summary from a raw error string.
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
    PRESS_SCALE = 0.96  # gentler than ChipButton's 0.88 - tile is a larger surface
    DURATION_PRESS_MS = 130

    TILE_W = 336
    TILE_H = 96

    launch_clicked       = Signal()
    quit_clicked         = Signal()
    cancel_clicked       = Signal()
    retry_clicked        = Signal()
    enter_2fa_clicked    = Signal()
    edit_clicked         = Signal()
    delete_clicked       = Signal()
    expand_error_clicked = Signal()
    portrait_clicked     = Signal()

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
        self._identity: dict | None = None

        self.setObjectName("account_tile")
        self.setFixedSize(self.TILE_W, self.TILE_H)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(11, 10, 11, 10)
        outer.setSpacing(0)

        # ── Row 1: portrait · identity · status pill ─────────────────────
        row1 = QHBoxLayout()
        row1.setContentsMargins(0, 0, 0, 0)
        row1.setSpacing(9)

        self.portrait = PrimaryToonSlot(self._game)
        self.portrait.clicked.connect(self.portrait_clicked.emit)
        row1.addWidget(self.portrait, 0, Qt.AlignVCenter)

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(1)
        self.name_label = ElidingLabel("")
        self.name_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        text_col.addWidget(self.name_label)
        self.sub_label = QLabel("")
        self.sub_label.setTextFormat(Qt.RichText)
        # Ignored horizontal policy: the sub line never pushes the status pill
        # off the row - it takes whatever width the column is given and clips.
        self.sub_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        text_col.addWidget(self.sub_label)
        text_col_w = QWidget()
        text_col_w.setLayout(text_col)
        text_col_w.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        row1.addWidget(text_col_w, 1)

        # Status pill (hidden by default). Flex-none, capped at 132px wide.
        self.status_pill = QFrame()
        self.status_pill.setObjectName("status_pill")
        self.status_pill.setFixedHeight(21)
        self.status_pill.setMaximumWidth(132)
        self.status_pill.setVisible(False)
        pill_lay = QHBoxLayout(self.status_pill)
        pill_lay.setContentsMargins(9, 0, 9, 0)
        pill_lay.setSpacing(5)
        # PulsingDot(7): green pulse shown only while running. Kept under the
        # name `status_dot` so the Multitoon sync-dot recolor path in
        # launch_tab (_apply_dot_color) can still drive it.
        self.status_dot = PulsingDot(7)
        self.status_dot.setVisible(False)
        pill_lay.addWidget(self.status_dot, 0, Qt.AlignVCenter)
        self.status_label = ElidingLabel("")
        self.status_label.setMaximumWidth(104)
        pill_lay.addWidget(self.status_label, 0, Qt.AlignVCenter)
        # expand_btn stays a plain QPushButton: it's a tiny status-pill
        # hamburger that doesn't need the press-scale feedback the action-row
        # buttons get from QuietChipButton.
        self.expand_btn = QPushButton()
        self.expand_btn.setFixedSize(16, 16)
        self.expand_btn.setIconSize(QSize(12, 12))
        self.expand_btn.setCursor(Qt.PointingHandCursor)
        self.expand_btn.setVisible(False)
        self.expand_btn.setStyleSheet(
            "QPushButton { background: transparent; border: none; color: inherit; }"
        )
        self.expand_btn.clicked.connect(self.expand_error_clicked.emit)
        pill_lay.addWidget(self.expand_btn, 0, Qt.AlignVCenter)
        row1.addWidget(self.status_pill, 0, Qt.AlignVCenter)

        outer.addLayout(row1)
        outer.addStretch(1)

        # ── Row 2: primary action · edit · delete ────────────────────────
        row2 = QHBoxLayout()
        row2.setContentsMargins(0, 0, 0, 0)
        row2.setSpacing(6)
        self.primary_button = QuietChipButton()
        self.primary_button.setText("Launch")
        self.primary_button.setMinimumHeight(28)
        self.primary_button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.primary_button.setCursor(Qt.PointingHandCursor)
        row2.addWidget(self.primary_button, 1)
        self.edit_btn = QuietChipButton()
        self.edit_btn.setFixedSize(28, 28)
        self.edit_btn.setIconSize(QSize(14, 14))
        self.edit_btn.setCursor(Qt.PointingHandCursor)
        self.edit_btn.clicked.connect(self.edit_clicked.emit)
        row2.addWidget(self.edit_btn, 0)
        self.delete_btn = QuietChipButton()
        self.delete_btn.setFixedSize(28, 28)
        self.delete_btn.setIconSize(QSize(14, 14))
        self.delete_btn.setCursor(Qt.PointingHandCursor)
        self.delete_btn.clicked.connect(self.delete_clicked.emit)
        row2.addWidget(self.delete_btn, 0)
        outer.addLayout(row2)

        # Theme + state caches. `_v2` holds the v2 token dict; `_is_dark`
        # drives the identity accent colors. Both are set before the first
        # _apply_button_for_state so it can read control tokens.
        self._current_theme = get_theme_colors(True)  # dark default; overridden by apply_theme
        self._is_dark = True
        self._v2 = get_v2_tokens(True)
        self._current_state = "idle"
        self._current_status_message = ""

        self._connected_signal = None
        self._apply_button_for_state("idle")
        self.apply_theme(self._current_theme)

    def apply_theme(self, c: dict) -> None:
        """Rebuild every QSS string from the theme dict `c`. Called by the
        constructor (dark default) and by LaunchSection.apply_theme on
        every theme switch. Signature is unchanged - `c` is still the legacy
        theme dict (the status-pill colors are read from it); the tile
        surface/text/control colors come from the v2 token set derived from
        `c`'s polarity."""
        self._current_theme = c
        is_dark = QColor(c["text_primary"]).lightnessF() > 0.5
        self._is_dark = is_dark
        t = get_v2_tokens(is_dark)
        self._v2 = t
        self.portrait.set_theme(is_dark)

        self.setStyleSheet(
            "QFrame#account_tile {"
            f" background: {t['row_bg']};"
            f" border: 1px solid {t['row_border']};"
            " border-radius: 13px;"
            "}"
            "QFrame#account_tile:hover {"
            f" background: {t['ctrl_hover']};"
            "}"
        )
        self.name_label.setStyleSheet(
            f"color: {t['title']}; font-size: 13.5px; font-weight: 700;"
            " background: transparent;"
        )
        self.sub_label.setStyleSheet(
            f"color: {t['sub']}; font-size: 10.5px; background: transparent;"
        )
        icon_color = with_alpha("#ffffff" if is_dark else "#0f172a",
                                0.62 if is_dark else 0.55)
        icon_qss = (
            "QToolButton {"
            f" background: {t['ctrl_bg']};"
            f" border: 1px solid {t['ctrl_border']};"
            " border-radius: 14px; }"
            "QToolButton:hover {"
            f" background: {t['ctrl_hover']}; }}"
        )
        self.edit_btn.setIcon(make_edit_icon(14, icon_color))
        self.edit_btn.setStyleSheet(icon_qss)
        self.delete_btn.setIcon(make_trash_icon(14, icon_color))
        self.delete_btn.setStyleSheet(icon_qss)

        # Re-render the identity (faint separator color is theme-dependent)
        # and re-resolve the status pill + primary button for the current
        # state so a theme switch restyles them against the new tokens.
        self._render_identity()
        self._apply_status_pill(self._current_state, self._current_status_message)
        self._apply_button_for_state(self._current_state)

    # ── public API ─────────────────────────────────────────────────

    def set_account(self, label: str, username: str, slot_index: int) -> None:
        self._slot_index = slot_index
        display = label or username or f"Account {slot_index + 1}"
        # No primary toon captured yet: dashed + numbered portrait slot, and
        # the "Set a primary toon" sub line.
        self._identity = {
            "is_set": False, "name": display, "username": username, "laff": None,
        }
        self.portrait.set_toon(species=None, accent=None, slot_number=slot_index + 1)
        self._render_identity()

    def set_primary_toon(self, *, name: str, username: str, dna: str | None = None,
                         species: str | None = None, accent: str | None = None,
                         slot_number: int | None = None, is_set: bool = False) -> None:
        self.portrait.set_toon(
            toon_name=name if is_set else None,
            dna=dna if is_set else None,
            species=species if is_set else None,
            accent=accent, slot_number=slot_number,
        )
        self._identity = {
            "is_set": is_set,
            "name": name if is_set else username,
            "username": username,
        }
        self._render_identity()

    def set_state(self, state: str, message: str = "", raw_message: str = "") -> None:
        self._current_state = state
        self._current_status_message = message
        self._state = state
        if state == "failed" and raw_message:
            self.raw_error_message = raw_message
        elif state == "failed":
            self.raw_error_message = message
        self._apply_status_pill(state, message)
        self._apply_button_for_state(state)

    # ── internals ──────────────────────────────────────────────────

    def _render_identity(self) -> None:
        """Rebuild name_label + sub_label from the cached identity. The faint
        separator color is theme-dependent, so this re-runs on theme switch."""
        idy = self._identity
        if idy is None:
            return
        self.name_label.setText(idy["name"] or "")
        if idy["is_set"]:
            # Username under the toon name (laff intentionally not shown).
            self.sub_label.setText(idy["username"] or "")
        else:
            self.sub_label.setText(
                '<span style="font-style:italic;">Set a primary toon</span>'
            )

    def _apply_status_pill(self, state: str, message: str) -> None:
        if state == "idle" or state not in _STATUS_VISUALS:
            self.status_pill.setVisible(False)
            return
        bg_key, fg_key, default_label = _STATUS_VISUALS[state]
        c = self._current_theme
        bg = c[bg_key]
        fg = c[fg_key]
        self.status_pill.setStyleSheet(
            "QFrame#status_pill {"
            f" background: {bg}; border-radius: 10px; color: {fg};"  # fg on frame so token appears in styleSheet() for tests
            "}"
            "QFrame#status_pill QLabel {"
            f" color: {fg}; background: transparent;"
            " font-size: 10.5px; font-weight: 600;"
            "}"
        )
        if state == "failed":
            text = "⚠ " + summarize_error(message)
        elif state == "queued" and message:
            text = f"In queue · {message}"
        elif message:
            text = (default_label + " · " + message) if default_label else message
        else:
            text = default_label
        self.status_label.setText(text)
        # Green pulse dot only while running (kept green here; the Multitoon
        # sync path may override the color afterwards via _apply_dot_color).
        self.status_dot.setVisible(state == "running")
        if state == "running":
            self.status_dot.set_color("#56c856", pulse=True)
        # Hamburger expand affordance only for the failed state.
        self.expand_btn.setVisible(state == "failed")
        if state == "failed":
            self.expand_btn.setIcon(_hamburger_icon(fg, 12))
        self.expand_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; border: none; color: {fg}; }}"
        )
        self.status_pill.setVisible(True)

    def _apply_button_for_state(self, state: str) -> None:
        label, fill, enabled, signal_name = _BUTTON_MAP.get(state, _BUTTON_MAP["idle"])
        t = self._v2
        if fill is None:
            fill = V2_ACCENTS[self._game]["c"]  # idle / disabled -> game accent base
        self.primary_button.setText(label)
        self.primary_button.setEnabled(enabled)
        self.primary_button.setStyleSheet(
            "QToolButton {"
            f" background: {fill}; color: white; border: none;"
            " border-radius: 14px; min-height: 28px; padding: 0 13px;"
            " font-size: 12.5px; font-weight: 700;"
            "}"
            "QToolButton:disabled {"
            f" background: {t['ctrl_bg']}; color: {t['sub']};"
            "}"
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
        # to super().paintEvent through our painter - QFrame.paintEvent
        # grabs its own QPainter on the same paint device and Qt rejects
        # the recursive begin(). So we render the QSS-styled background
        # manually via QStyle.PE_Widget, with the painter pre-scaled
        # around the widget center and tinted by tile_opacity. Child
        # widgets (buttons, labels) paint themselves through Qt's normal
        # widget tree and are NOT scaled or opacity-tinted by this
        # transform - that mirrors the same tradeoff ChipButton accepts.
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
