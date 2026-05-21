"""Single account tile for the Launch tab grid. State-aware primary button
swaps label, color, and enabled flag based on the account's current
LoginState. Emits a distinct signal per state-specific click."""
from __future__ import annotations

from PySide6.QtCore import QByteArray, Qt, QSize, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

from utils.shared_widgets import PulsingDot
from utils.theme_manager import make_edit_icon, make_trash_icon


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


GAME_ACCENT = {"ttr": "#4A8FE7", "cc": "#F26D21"}

# Status -> (band_bg, band_fg, band_label)
_STATUS_VISUALS = {
    "logging_in": ("rgba(232,168,56,0.15)", "#E8A838", "Logging in…"),
    "launching":  ("rgba(232,168,56,0.15)", "#E8A838", "Launching…"),
    "queued":     ("rgba(232,168,56,0.15)", "#E8A838", "In queue"),
    "need_2fa":   ("rgba(200,126,232,0.15)", "#C87EE8", "2FA Required"),
    "running":    ("rgba(86,200,86,0.15)",  "#6fdf6f", "Running"),
    "failed":     ("rgba(224,82,82,0.18)",  "#ff7575", ""),  # set per-message
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
    if "wine" in lower or "proton" in lower or "umu" in lower:
        return "Runtime error"
    # Default: truncate to ~32 chars.
    return (raw_message[:32] + "…") if len(raw_message) > 32 else raw_message


class AccountTile(QFrame):
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

        self.setObjectName("account_tile")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.setMinimumHeight(130)

        accent = GAME_ACCENT[game]
        self.setStyleSheet(
            f"QFrame#account_tile {{"
            f" background: #252525;"
            f" border-radius: 10px;"
            f" border-top: 3px solid {accent};"
            f"}}"
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(8)

        # Header row
        head = QHBoxLayout()
        head.setSpacing(8)
        self.badge = QLabel(str(slot_index + 1))
        self.badge.setFixedSize(22, 22)
        self.badge.setAlignment(Qt.AlignCenter)
        self.badge.setStyleSheet(
            f"background: {accent}; color: white; border-radius: 11px;"
            f" font-weight: 700; font-size: 11px;"
        )
        head.addWidget(self.badge)
        self.name_label = QLabel("")
        self.name_label.setStyleSheet(
            "color: #fff; font-weight: 600; font-size: 13px; background: transparent;"
        )
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
        self.primary_button = QPushButton("Launch")
        self.primary_button.setMinimumHeight(28)
        self.primary_button.setCursor(Qt.PointingHandCursor)
        acts.addWidget(self.primary_button, 1)
        _muted = QColor("#8a9bb8")
        self.edit_btn = QPushButton()
        self.edit_btn.setIcon(make_edit_icon(14, _muted))
        self.edit_btn.setIconSize(QSize(14, 14))
        self.edit_btn.setFixedSize(26, 26)
        self.edit_btn.setCursor(Qt.PointingHandCursor)
        self.edit_btn.setStyleSheet(
            "QPushButton { background: transparent; border: 1px solid rgba(255,255,255,0.1);"
            " color: #8a9bb8; border-radius: 6px; }"
        )
        self.edit_btn.clicked.connect(self.edit_clicked.emit)
        acts.addWidget(self.edit_btn)
        self.delete_btn = QPushButton()
        self.delete_btn.setIcon(make_trash_icon(14, _muted))
        self.delete_btn.setIconSize(QSize(14, 14))
        self.delete_btn.setFixedSize(26, 26)
        self.delete_btn.setCursor(Qt.PointingHandCursor)
        self.delete_btn.setStyleSheet(
            "QPushButton { background: transparent; border: 1px solid rgba(255,255,255,0.1);"
            " color: #8a9bb8; border-radius: 6px; }"
        )
        self.delete_btn.clicked.connect(self.delete_clicked.emit)
        acts.addWidget(self.delete_btn)
        outer.addLayout(acts)

        self._connected_signal = None
        self._apply_button_for_state("idle")

    # ── public API ─────────────────────────────────────────────────

    def set_account(self, label: str, username: str, slot_index: int) -> None:
        self._slot_index = slot_index
        self.badge.setText(str(slot_index + 1))
        display = label or username or f"Account {slot_index + 1}"
        self.name_label.setText(display)

    def set_state(self, state: str, message: str = "", raw_message: str = "") -> None:
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
        bg, fg, default_label = _STATUS_VISUALS[state]
        self.status_band.setStyleSheet(
            f"background: {bg}; border-radius: 5px;"
        )
        self.status_label.setStyleSheet(f"color: {fg}; font-size: 11px; font-weight: 600;")
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
            f"QPushButton {{"
            f" background: {bg}; color: {text_color}; border: none;"
            f" border-radius: 6px; padding: 7px; font-size: 12px; font-weight: 600;"
            f"}}"
            f"QPushButton:disabled {{ background: rgba(255,255,255,0.06); color: #5d6a82; }}"
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
