"""Per-card QGraphicsView wrapper that scales one card as a single locked unit.

The card is laid out ONCE at its framed 1.0 size and proxied into a scene; the
view applies a single scale transform, so the card + its controls scale together
and never re-layout (no float). Based on tabs/multitoon/_full_layout._FullLayout,
which proves this is crisp + interactive with the real cards.

OWNERSHIP CONTRACT (load-bearing): the card is BORROWED, never owned. But
QGraphicsScene.addWidget() transfers Qt ownership of the card to the proxy, so the
scene WOULD delete the card on destruction. Callers MUST call release_card()
before deleting/closing this wrapper (it revokes the proxy's ownership first).
closeEvent() releases defensively as a safety net for the close() path."""
from __future__ import annotations

from PySide6.QtCore import Qt, QEvent
from PySide6.QtGui import QPainter, QTransform
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QGraphicsScene, QGraphicsView, QFrame,
)


class ScaledCardView(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._scale = 1.0
        self._card: QWidget | None = None
        self._proxy = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self._scene = QGraphicsScene(self)
        self._view = QGraphicsView(self._scene, self)
        self._view.setRenderHints(
            QPainter.Antialiasing | QPainter.SmoothPixmapTransform | QPainter.TextAntialiasing
        )
        self._view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._view.setFrameStyle(QFrame.NoFrame)
        # AlignTop|AlignLeft (vs _FullLayout's AlignHCenter): the per-card view is
        # sized to exactly fit one card, so there is no slack to center within;
        # top-left pins the scaled card to the window origin.
        self._view.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        # Transparent viewport (4 mechanisms, matching _FullLayout).
        self._view.setBackgroundBrush(Qt.transparent)
        self._view.setStyleSheet("QGraphicsView { background: transparent; border: none; }")
        self._view.setAttribute(Qt.WA_TranslucentBackground, True)
        self._view.viewport().setAutoFillBackground(False)
        lay.addWidget(self._view)
        self._apply_transform()

    def card(self) -> QWidget | None:
        return self._card

    def set_card(self, card: QWidget) -> "QWidget | None":
        """Host *card* (borrowed). If a different card was already hosted it is
        released and RETURNED (parentless, undeleted) so the caller never loses it;
        returns None when nothing was displaced."""
        if self._card is card:
            return None
        displaced = self.release_card() if self._card is not None else None
        # addWidget() requires a TOP-LEVEL widget: it silently rejects a parented
        # one (proxy.widget() stays None, the card never embeds). The borrowed card
        # arrives parented to its grid cell, so detach it first.
        card.setParent(None)
        self._card = card
        self._proxy = self._scene.addWidget(card)  # reparents card into the scene
        self._proxy.setPos(0, 0)
        card.installEventFilter(self)
        self._sync_scene_rect()
        return displaced

    def release_card(self) -> "QWidget | None":
        card = self._card
        if card is None:
            return None
        card.removeEventFilter(self)
        if self._proxy is not None:
            self._proxy.setWidget(None)     # detach + un-own the card (NOT deleted)
            self._scene.removeItem(self._proxy)
            self._proxy = None
        # setWidget(None) already re-parented the card to None; explicit for clarity.
        card.setParent(None)
        self._card = None
        return card

    def closeEvent(self, ev):
        # Safety net: un-own the borrowed card before Qt's destruction cascade, so
        # the scene never deletes it on close() (see the ownership contract above).
        self.release_card()
        super().closeEvent(ev)

    def set_scale(self, scale: float) -> None:
        self._scale = float(scale)
        self._apply_transform()

    def view_transform(self) -> QTransform:
        return self._view.transform()

    def _apply_transform(self) -> None:
        # setTransform REPLACES (never multiplies) so repeated calls don't compound.
        self._view.setTransform(QTransform().scale(self._scale, self._scale))

    def _sync_scene_rect(self) -> None:
        if self._card is None:
            return
        hint = self._card.sizeHint()
        size = self._card.size()
        w = max(hint.width(), size.width(), 1)
        h = max(hint.height(), size.height(), 1)
        self._scene.setSceneRect(0, 0, w, h)

    def eventFilter(self, obj, ev):
        if obj is self._card and ev.type() == QEvent.Resize:
            self._sync_scene_rect()
        return super().eventFilter(obj, ev)
