"""Pure functions that turn a stored customization entry into the
QBrush / QColor / pattern values the paint code needs.

Keeps schema knowledge out of widgets and the manager. Every helper
has a `fallback` parameter (or returns None) so the caller controls
what the default looks like.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QPointF
from PySide6.QtGui import QBrush, QColor, QLinearGradient


def _is_hex(s) -> bool:
    return isinstance(s, str) and s.startswith("#") and len(s) in (4, 7, 9)


def resolve_portrait_brush(entry: dict, fallback: QColor) -> QBrush:
    """Returns a QBrush. Gradient takes precedence over color; missing
    entry or invalid types fall back to `fallback`."""
    portrait = entry.get("portrait") if isinstance(entry, dict) else None
    if isinstance(portrait, dict):
        grad = portrait.get("gradient")
        if isinstance(grad, dict):
            start = grad.get("start")
            end = grad.get("end")
            if _is_hex(start) and _is_hex(end):
                lin = QLinearGradient(QPointF(0, 0), QPointF(1, 1))
                lin.setCoordinateMode(QLinearGradient.ObjectBoundingMode)
                lin.setColorAt(0.0, QColor(start))
                lin.setColorAt(1.0, QColor(end))
                return QBrush(lin)
        color = portrait.get("color")
        if _is_hex(color):
            return QBrush(QColor(color))
    return QBrush(fallback)


def resolve_portrait_pattern(entry: dict) -> Optional[tuple[str, QColor]]:
    """Returns (pattern_name, color) or None when no pattern is set."""
    portrait = entry.get("portrait") if isinstance(entry, dict) else None
    if not isinstance(portrait, dict):
        return None
    pat = portrait.get("pattern")
    if not isinstance(pat, dict):
        return None
    name = pat.get("name")
    color = pat.get("color")
    if not isinstance(name, str) or not _is_hex(color):
        return None
    return name, QColor(color)


def resolve_accent(entry: dict, fallback: QColor) -> QColor:
    val = entry.get("accent") if isinstance(entry, dict) else None
    if _is_hex(val):
        return QColor(val)
    return fallback


def resolve_body(entry: dict) -> Optional[QColor]:
    val = entry.get("body") if isinstance(entry, dict) else None
    if _is_hex(val):
        return QColor(val)
    return None


def resolve_pose(entry: dict, fallback: str = "portrait") -> str:
    """Returns the pose name to render. Validates against POSE_NAMES;
    unknown values fall back to `fallback`."""
    from utils.rendition_poses import POSE_NAMES
    val = entry.get("pose") if isinstance(entry, dict) else None
    if isinstance(val, str) and val in POSE_NAMES:
        return val
    return fallback


def resolve_portrait_transform(
    entry: dict,
) -> tuple[float, float, float, float]:
    """Returns (zoom, offset_x, offset_y, rotate). Defaults to
    (1.0, 0.0, 0.0, 0.0). Clamps zoom to [0.5, 3.0], clamps offsets
    to [-1.0, 1.0] (fractions of the rendered circle diameter), and
    normalizes rotate into [-180, 180]. Non-dict transform → defaults."""
    portrait = entry.get("portrait") if isinstance(entry, dict) else None
    if not isinstance(portrait, dict):
        return (1.0, 0.0, 0.0, 0.0)
    t = portrait.get("transform")
    if not isinstance(t, dict):
        return (1.0, 0.0, 0.0, 0.0)
    zoom = float(t.get("zoom", 1.0))
    zoom = max(0.5, min(3.0, zoom))
    off_x = float(t.get("offset_x", 0.0))
    off_x = max(-1.0, min(1.0, off_x))
    off_y = float(t.get("offset_y", 0.0))
    off_y = max(-1.0, min(1.0, off_y))
    rot = float(t.get("rotate", 0.0))
    while rot > 180.0:
        rot -= 360.0
    while rot < -180.0:
        rot += 360.0
    return (zoom, off_x, off_y, rot)
