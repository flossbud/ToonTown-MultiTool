"""Hosts the pinwheel cluster in a QGraphicsView and scales it as ONE unit.

A single view transform scales the whole proxied widget tree together, so no child
ever scales independently (the locked requirement). The window is sized to the scaled
bounding box; the input region is derived from the same scaled geometry (see region.py).
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QTransform, QPainter
from PySide6.QtWidgets import QGraphicsScene, QGraphicsView

from utils.overlay.scale import clamp_scale

MARGIN = 28  # room for glow halos + transient scale badge


class ClusterHost(QGraphicsView):
    def __init__(self, content, content_size=None, parent=None):
        super().__init__(parent)
        self._scale = 1.0
        self.setFrameShape(QGraphicsView.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setStyleSheet("background: transparent; border: none;")
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setRenderHint(QPainter.SmoothPixmapTransform, True)
        self._scene = QGraphicsScene(self)
        self._scene.setBackgroundBrush(Qt.transparent)
        self._proxy = self._scene.addWidget(content)
        if content_size is not None:
            # Preserve the size the framed layout gave the cluster; once reparented
            # into the proxy the widget would otherwise collapse to its size hint.
            self._proxy.resize(content_size.width(), content_size.height())
        # SPIKE-PROVEN (2026-06-19): translucency needs ALL THREE layers transparent.
        # The view paints through a viewport widget, and the proxy treats `content` as a
        # top-level widget - each paints the dark palette background in the gaps otherwise.
        self.viewport().setAutoFillBackground(False)
        self.viewport().setStyleSheet("background: transparent;")
        content.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setScene(self._scene)
        self.set_scale(1.0)

    def current_scale(self) -> float:
        return self._scale

    def content_transform(self) -> QTransform:
        return QTransform().scale(self._scale, self._scale)

    def set_scale(self, value: float) -> None:
        self._scale = clamp_scale(value)
        self.resetTransform()
        super().scale(self._scale, self._scale)
        br: QRectF = self._proxy.boundingRect()
        self.setSceneRect(br)
        self.setFixedSize(
            int(br.width() * self._scale) + MARGIN,
            int(br.height() * self._scale) + MARGIN,
        )
