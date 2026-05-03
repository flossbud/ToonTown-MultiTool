"""Small layout helpers shared across tabs."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QBoxLayout, QWidget


def clamp_centered(layout: QBoxLayout, widget: QWidget, max_width: int) -> QWidget:
    """Clamp `widget` to `max_width` and add it to `layout` horizontally centered.

    Mirrors the Launch tab pattern: `setMaximumWidth(max_width)` plus
    `Qt.AlignHCenter`. Returns the widget so calls can be chained.
    """
    widget.setMaximumWidth(max_width)
    layout.addWidget(widget, alignment=Qt.AlignHCenter)
    return widget
