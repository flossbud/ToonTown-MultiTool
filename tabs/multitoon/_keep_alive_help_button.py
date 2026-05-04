"""Per-slot Keep-Alive discovery affordance.

A QToolButton-based help icon that surfaces the existence of Keep-Alive
when the master setting is disabled. Click opens an explanatory popover
with a "Go to Settings" CTA that emits help_requested; the consuming
MultitoonTab connects that signal to a tab-level signal which the main
window uses to navigate to Settings and highlight the Keep-Alive group.

The popover is added in Task 3 (see plan). This file currently only
contains the button shell and accessibility metadata.
"""

from PySide6.QtCore import Qt, QSize, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QToolButton

from utils.icon_factory import make_help_icon


class KeepAliveHelpButton(QToolButton):
    """Help-icon button surfacing the now-opt-in Keep-Alive feature."""

    help_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(32, 32)
        self.setIconSize(self._icon_size())
        self.setCursor(Qt.PointingHandCursor)
        self.setAccessibleName("Keep-Alive help")
        self.setAccessibleDescription(
            "Keep-Alive is currently disabled. Click to learn how to enable it in Settings."
        )
        self.setToolTip("Keep-Alive is disabled. Click to learn more.")
        # Default colour — refresh_theme overrides with the current palette.
        self.setIcon(make_help_icon(self._icon_size().width(), QColor("#bbbbbb")))

    def _icon_size(self) -> QSize:
        return QSize(14, 14)

    def refresh_theme(self, theme_colors: dict):
        """Update the icon stroke colour for the active theme."""
        color = QColor(theme_colors.get("text_secondary", "#bbbbbb"))
        self.setIcon(make_help_icon(self._icon_size().width(), color))
