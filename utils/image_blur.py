"""Pixmap-level Gaussian-blur approximation.

Used to produce the static blurred backdrop behind the customization
overlay. We cannot use QGraphicsBlurEffect on a live widget tree
because PySide6 6.11 renders QGraphicsBlurEffect (and
QGraphicsOpacityEffect) invisibly when applied to widgets hosted
inside a QGraphicsProxyWidget, which is what _FullLayout's scale
wrapper is. Blurring a captured pixmap instead works regardless of
which mode the multitoon tab is in.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap


def gaussian_blur_pixmap(pix: QPixmap, radius: int) -> QPixmap:
    """Approximate a Gaussian blur by repeatedly downscaling and
    upscaling with bilinear filtering. Three passes gives a visually
    Gaussian-like result at a fraction of the cost of a true
    convolution.

    radius is interpreted loosely: higher radius -> more downscaling
    per pass. radius <= 0 returns a copy of the input."""
    if radius <= 0:
        return QPixmap(pix)

    # Downscale factor: roughly 1 / (radius + 1) per pass.
    w = pix.width()
    h = pix.height()
    if w == 0 or h == 0:
        return QPixmap(pix)

    factor = max(2, radius + 1)
    small_w = max(1, w // factor)
    small_h = max(1, h // factor)

    out = pix
    for _ in range(3):
        out = out.scaled(
            small_w, small_h,
            Qt.IgnoreAspectRatio,
            Qt.SmoothTransformation,
        )
        out = out.scaled(
            w, h,
            Qt.IgnoreAspectRatio,
            Qt.SmoothTransformation,
        )
    return out
