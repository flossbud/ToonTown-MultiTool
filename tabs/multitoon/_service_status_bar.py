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
    """Transparent square button that inherits the bar's text colour."""

    def __init__(self, glyph: str, tooltip: str, parent=None):
        super().__init__(glyph, parent)
        self.setFlat(True)
        self.setFixedSize(28, 28)
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

        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 0, 4, 0)
        lay.setSpacing(10)

        self.dots = StatusDots(self)
        lay.addWidget(self.dots)

        self.label = QLabel("Idle")
        self.label.setObjectName("svc_label")
        self.label.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        lay.addWidget(self.label, 1)

        self.stop_play_button = _IconButton("■", "Stop broadcasting")
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

        self.refresh_button = _IconButton("⟳", "Refresh")
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

        if state == "stopped":
            self.stop_play_button.setText("▶")
            self.stop_play_button.setToolTip("Start broadcasting")
            self.stop_play_button.setProperty("role", "play")
        else:
            self.stop_play_button.setText("■")
            self.stop_play_button.setToolTip("Stop broadcasting")
            self.stop_play_button.setProperty("role", "stop")

        # Force a style recompute so QSS rules keyed on `svc_state` apply.
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def set_status_text(self, text: str) -> None:
        self.label.setText(text)

    def set_dot_states(self, states: list[int]) -> None:
        self.dots.set_states(states)

    def set_dot_colors(self, off: str, found: str, active: str) -> None:
        self.dots.set_colors(off, found, active)

    # -- Slots -------------------------------------------------------------

    def _on_stop_play_clicked(self) -> None:
        if self.stop_play_button.property("role") == "play":
            self.play_requested.emit()
        else:
            self.stop_requested.emit()
