"""Modern auto-hide scrollbar — thin pill that fades in on activity."""
from __future__ import annotations

from PySide6.QtWidgets import QScrollBar


_QSS_TEMPLATE = """
QScrollBar:vertical {{
    background: transparent;
    width: 12px;
    margin: 0;
    border: none;
}}
QScrollBar::handle:vertical {{
    background: {active_color};
    min-width: 8px;
    margin-left: 4px;
    min-height: 36px;
    border-radius: 4px;
}}
QScrollBar::handle:vertical:hover {{
    background: {hover_color};
    min-width: 12px;
    margin-left: 0px;
    border-radius: 6px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
    background: transparent;
    border: none;
}}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: transparent;
}}
"""

_DARK_ACTIVE = "rgba(255, 255, 255, 0.45)"
_DARK_HOVER  = "rgba(255, 255, 255, 0.70)"
_LIGHT_ACTIVE = "rgba(15, 23, 42, 0.30)"
_LIGHT_HOVER  = "rgba(15, 23, 42, 0.55)"


class AutoHideScrollBar(QScrollBar):
    """A QScrollBar that fades in on activity and fades out at idle."""

    def __init__(self, parent=None):
        super().__init__(parent)

    def set_theme(self, is_dark: bool) -> None:
        if is_dark:
            qss = _QSS_TEMPLATE.format(
                active_color=_DARK_ACTIVE,
                hover_color=_DARK_HOVER,
            )
        else:
            qss = _QSS_TEMPLATE.format(
                active_color=_LIGHT_ACTIVE,
                hover_color=_LIGHT_HOVER,
            )
        self.setStyleSheet(qss)
