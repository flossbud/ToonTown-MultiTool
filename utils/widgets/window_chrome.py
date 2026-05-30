"""Custom window chrome for the frameless main window: resize-edge math,
control-button glyphs, the traffic-light control buttons, and the
WindowChromeController that wires drag / resize / window-state behavior.

Move and resize delegate to the compositor via QWindow.startSystemMove() /
startSystemResize(), which is the only reliable cross-platform path
(X11, Wayland, Windows) and preserves native snap/tiling. We never hand-roll
move()/resize() — that breaks on Wayland."""

from PySide6.QtCore import Qt, QObject, QEvent
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QAbstractButton


def resize_edge_for_pos(x: int, y: int, w: int, h: int, margin: int = 6):
    """Return the Qt.Edge (or OR'd corner edges) for a point near the window
    frame, or None if the point is in the interior. Pure function for testing."""
    left = x <= margin
    right = x >= w - margin
    top = y <= margin
    bottom = y >= h - margin
    edges = Qt.Edge(0)
    if left:
        edges |= Qt.Edge.LeftEdge
    if right:
        edges |= Qt.Edge.RightEdge
    if top:
        edges |= Qt.Edge.TopEdge
    if bottom:
        edges |= Qt.Edge.BottomEdge
    # PySide6 6.10: Qt.Edge is a flag type; int() fails — use .value instead
    return edges if edges.value else None


def maximize_glyph(is_maximized: bool) -> str:
    """Glyph for the maximize/restore control."""
    return "❐" if is_maximized else "□"  # restore / maximize
