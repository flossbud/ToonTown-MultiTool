"""3-state service status bar for the Multitoon compact UI.

States:
    broadcasting   service running, >=1 toon enabled  (blue fill)
    idle           service running, 0 toons enabled   (grey fill)
    stopped        user explicitly stopped service    (red fill)

Inline controls (right-anchored):
    stop / play button  (square in broadcasting/idle, triangle in stopped)
    1 px divider
    refresh button

Replaces the legacy `StatusBar` widget, the standalone `toggle_service_button`,
and the `_section_divider` from the old compact layout.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QWidget,
)

# Re-exported from _tab.py so both the legacy and new widgets can share
# the same dots painting. If StatusDots later moves to its own module,
# update the import here.
from tabs.multitoon._tab import StatusDots


_VALID_STATES = ("broadcasting", "idle", "stopped")
_BAR_HEIGHT_PX = 36


class _IconButton(QPushButton):
    """Transparent square button. Icon-driven so glyphs render reliably
    across platforms."""

    def __init__(self, icon, tooltip: str, parent=None):
        from PySide6.QtCore import QSize
        super().__init__(parent)
        self.setFlat(True)
        self.setFixedSize(28, 28)
        self.setIcon(icon)
        self.setIconSize(QSize(14, 14))
        self.setToolTip(tooltip)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)


class ServiceStatusBar(QFrame):
    """3-state status bar. Emits `stop_requested`, `play_requested`,
    `refresh_requested` from its inline icon buttons."""

    stop_requested = Signal()
    play_requested = Signal()
    refresh_requested = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("ServiceStatusBar")
        self.setFixedHeight(_BAR_HEIGHT_PX)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self.state = "idle"
        self._theme = None
        self._dot_palette = None

        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 0, 4, 0)
        lay.setSpacing(10)

        self.dots = StatusDots(self)
        lay.addWidget(self.dots)

        self.label = QLabel("Idle")
        self.label.setObjectName("svc_label")
        self.label.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        lay.addWidget(self.label, 1)

        from utils.icon_factory import make_stop_icon, make_refresh_icon
        self.stop_play_button = _IconButton(make_stop_icon(14), "Stop broadcasting")
        self.stop_play_button.setObjectName("svc_stop_play")
        self.stop_play_button.setProperty("role", "stop")
        self.stop_play_button.clicked.connect(self._on_stop_play_clicked)
        lay.addWidget(self.stop_play_button)

        self._divider = QFrame()
        self._divider.setObjectName("svc_divider")
        self._divider.setFrameShape(QFrame.VLine)
        self._divider.setFixedWidth(1)
        self._divider.setFixedHeight(15)
        lay.addWidget(self._divider)

        self.refresh_button = _IconButton(make_refresh_icon(14), "Refresh")
        self.refresh_button.setObjectName("svc_refresh")
        self.refresh_button.clicked.connect(self.refresh_requested.emit)
        lay.addWidget(self.refresh_button)

        # Set initial property + apply styles
        self.set_state("idle")

    # -- API ---------------------------------------------------------------

    def set_state(self, state: str) -> None:
        if state not in _VALID_STATES:
            raise ValueError(
                f"ServiceStatusBar.set_state: {state!r} not in {_VALID_STATES}"
            )
        self.state = state
        self.setProperty("svc_state", state)

        from utils.icon_factory import make_stop_icon, make_play_icon
        if state == "stopped":
            self.stop_play_button.setIcon(make_play_icon(14))
            self.stop_play_button.setToolTip("Start broadcasting")
            self.stop_play_button.setProperty("role", "play")
        else:
            self.stop_play_button.setIcon(make_stop_icon(14))
            self.stop_play_button.setToolTip("Stop broadcasting")
            self.stop_play_button.setProperty("role", "stop")

        # Force a style recompute so [svc_state="..."] QSS rules apply.
        self.style().unpolish(self)
        self.style().polish(self)
        # Dots are painted by Python; push the per-state palette now.
        self._apply_dot_palette()
        self.update()

    def set_status_text(self, text: str) -> None:
        self.label.setText(text)

    def set_dot_states(self, states: list[int]) -> None:
        self.dots.set_states(states)

    def set_dot_colors(self, off: str, found: str, active: str) -> None:
        self.dots.set_colors(off, found, active)

    def set_text_color(self, color: str) -> None:
        """Compatibility shim: matches legacy StatusBar.set_text_color so
        callers that set colour via the status_bar alias still work."""
        self.label.setStyleSheet(
            f"font-size: 13px; font-weight: 500; color: {color}; "
            "background: transparent; border: none;"
        )

    def apply_theme(self, c: dict) -> None:
        """Apply the active theme's colours to the bar across all 3 states.
        Caller passes the dict from utils.theme_manager.get_theme_colors.

        Stores per-state dot colours and the per-state QSS, then re-applies
        the current state's dot colours immediately."""
        self._theme = c
        # Per-state dot palettes. Broadcasting puts the bar on blue, so
        # dots are white shades for contrast. Stopped goes red, same idea.
        # Idle (the default neutral) uses the standard segment tokens.
        self._dot_palette = {
            "broadcasting": (
                "rgba(255,255,255,46)",    # off (~18% white)
                "rgba(255,255,255,115)",   # found (~45% white)
                "#ffffff",                 # active (full white + dot's own glow)
            ),
            "idle": (
                c.get("segment_off",    "#333333"),
                c.get("segment_found",  "#555555"),
                c.get("segment_active", "#56c856"),
            ),
            "stopped": (
                "rgba(255,255,255,36)",
                "rgba(255,255,255,90)",
                "rgba(255,255,255,200)",
            ),
        }
        # QSS rules - the [svc_state="..."] selectors cascade off the Qt
        # property set in set_state(). The neutral block runs first as a
        # default; state-specific blocks override.
        self.setStyleSheet(f"""
            QFrame#ServiceStatusBar {{
                background-color: {c['bg_card_inner']};
                border-radius: 8px;
                border: 1px solid {c['border_card']};
            }}
            QFrame#ServiceStatusBar[svc_state="broadcasting"] {{
                background-color: {c['accent_blue_dim']};
                border: 1px solid {c['accent_blue']};
            }}
            QFrame#ServiceStatusBar[svc_state="stopped"] {{
                background-color: {c['red_dim']};
                border: 1px solid {c['accent_red_border']};
            }}

            QFrame#ServiceStatusBar QLabel#svc_label {{
                color: {c['text_secondary']};
                font-size: 12.5px;
                font-weight: 600;
                background: transparent;
                border: none;
            }}
            QFrame#ServiceStatusBar[svc_state="broadcasting"] QLabel#svc_label,
            QFrame#ServiceStatusBar[svc_state="stopped"] QLabel#svc_label {{
                color: #ffffff;
            }}

            QFrame#ServiceStatusBar QPushButton#svc_stop_play,
            QFrame#ServiceStatusBar QPushButton#svc_refresh {{
                background: transparent;
                border: none;
                color: {c['text_secondary']};
            }}
            QFrame#ServiceStatusBar QPushButton#svc_stop_play:hover,
            QFrame#ServiceStatusBar QPushButton#svc_refresh:hover {{
                background: rgba(255,255,255,18);
                border-radius: 6px;
            }}
            QFrame#ServiceStatusBar[svc_state="broadcasting"] QPushButton#svc_stop_play,
            QFrame#ServiceStatusBar[svc_state="broadcasting"] QPushButton#svc_refresh,
            QFrame#ServiceStatusBar[svc_state="stopped"] QPushButton#svc_stop_play,
            QFrame#ServiceStatusBar[svc_state="stopped"] QPushButton#svc_refresh {{
                color: #ffffff;
            }}
        """)
        # Re-apply current state's dot colours immediately.
        self._apply_dot_palette()

    def _apply_dot_palette(self) -> None:
        """Internal: push the dot palette appropriate for self.state into
        the dots widget. Called by apply_theme() and set_state()."""
        if not self._dot_palette:
            return
        off, found, active = self._dot_palette.get(self.state, self._dot_palette["idle"])
        self.dots.set_colors(off, found, active)

    # -- Slots -------------------------------------------------------------

    def _on_stop_play_clicked(self) -> None:
        if self.stop_play_button.property("role") == "play":
            self.play_requested.emit()
        else:
            self.stop_requested.emit()
