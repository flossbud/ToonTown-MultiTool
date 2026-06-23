"""Render an account's last toon into a circular QPixmap for the radial menu.

Reuses the real ToonPortraitWidget (so the portrait matches the multitoon
cards) via QWidget.grab(), then clips to a circle. Falls back to a themed
azure placeholder disc with a person glyph when there is no toon.

Real ToonPortraitWidget constructor (tabs/multitoon/_tab.py):
    ToonPortraitWidget(slot: int, parent=None)
Setters used: set_game(), set_toon_name(), set_customizations_manager(),
              set_dna().
The widget has a hard max of 64x64 so we grab at that size and scale to
the requested diameter inside _circular().
"""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import QPixmap, QPainter, QPainterPath, QColor, QBrush, QLinearGradient


@dataclass(frozen=True)
class PortraitRender:
    pixmap: "QPixmap"   # always non-null, diameter x diameter
    status: str         # "complete" | "pending" | "no_pose"


def _circular(src: QPixmap, diameter: int) -> QPixmap:
    out = QPixmap(diameter, diameter)
    out.fill(Qt.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.Antialiasing, True)
    clip = QPainterPath()
    clip.addEllipse(QRectF(0, 0, diameter, diameter))
    p.setClipPath(clip)
    p.drawPixmap(0, 0, src.scaled(diameter, diameter,
                                  Qt.KeepAspectRatioByExpanding,
                                  Qt.SmoothTransformation))
    p.end()
    return out


def _placeholder(diameter: int) -> QPixmap:
    out = QPixmap(diameter, diameter)
    out.fill(Qt.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.Antialiasing, True)
    g = QLinearGradient(0, 0, 0, diameter)
    g.setColorAt(0.0, QColor(0, 185, 249))
    g.setColorAt(1.0, QColor(0, 119, 239))
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(g))
    p.drawEllipse(QRectF(0, 0, diameter, diameter))
    p.setBrush(QColor(255, 255, 255))
    r = diameter * 0.5
    cx = cy = diameter / 2
    hr = r * 0.42
    p.drawEllipse(QPointF(cx, cy - r * 0.38), hr, hr)
    body = QPainterPath()
    bw = r * 1.25
    bh = r * 1.05
    body.addRoundedRect(QRectF(cx - bw / 2, cy + r * 0.02, bw, bh), bw * 0.5, bw * 0.5)
    p.drawPath(body)
    p.end()
    return out


# ToonPortraitWidget.setMaximumSize is hardcoded to 64x64 in _tab.py.
_WIDGET_MAX = 64


def render_account_portrait(game, toon_name, dna, customizations, diameter):
    """Return a ``PortraitRender`` for ``(game, toon_name)``.

    ``status`` is "complete" when the toon body is present, "pending" when a
    pose fetch is in flight (background-only, fill in via pose_ready), or
    "no_pose" when there is no pose to fetch (no toon name, or empty DNA).
    The pixmap is always ``diameter`` x ``diameter`` and non-null. The grabbed
    widget suppresses its own fallback glyph so the ring owns the loading cue.
    """
    if not toon_name:
        return PortraitRender(_placeholder(diameter), "no_pose")

    from tabs.multitoon._tab import ToonPortraitWidget

    # Slot 0 is a dummy value; only the setters below drive visible content.
    w = ToonPortraitWidget(slot=0)
    w.set_suppress_fallback_glyph(True)
    w.set_game(game)
    w.set_toon_name(toon_name)
    if customizations is not None:
        w.set_customizations_manager(customizations)

    status = "no_pose"
    if dna:
        status = "pending"
        w.set_dna(dna)
        # set_dna kicks off an ASYNC pose fetch, so grabbing right away would
        # capture only the background. Pull the pose from the disk cache
        # synchronously; on a hit the toon is complete, on a miss it stays
        # pending and pose_ready will fill it in later.
        try:
            from utils.rendition_poses import RenditionPoseFetcher
            cached = RenditionPoseFetcher.instance().cached_pixmap(dna, w._pose)
            if cached is not None and not cached.isNull():
                w._pixmap = cached
                w._loading = False
                status = "complete"
        except Exception:
            pass

    # Grab at the widget's maximum supported size; _circular scales to diameter.
    grab_size = min(diameter, _WIDGET_MAX)
    w.setMinimumSize(grab_size, grab_size)
    w.setMaximumSize(grab_size, grab_size)
    w.resize(grab_size, grab_size)

    pm = w.grab()
    w.deleteLater()
    return PortraitRender(_circular(pm, diameter), status)
