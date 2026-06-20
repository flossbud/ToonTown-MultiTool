"""Proxy-safe painted dim for inactive overlay cards.

A live QGraphicsColorizeEffect renders corrupt inside a QGraphicsProxyWidget
(PySide6 6.11), so dimming an inactive card is done by painting a translucent
grey wash on top of it via this sibling overlay (mouse-transparent, raised),
rather than a graphics effect."""
from __future__ import annotations

from PySide6.QtCore import Qt, QEvent
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QWidget


class CardDimOverlay(QWidget):
    # Grey wash that approximates the prior colorize(#808080, strength 0.55);
    # alpha tuned during live validation to match the framed dim.
    _WASH = QColor(0x80, 0x80, 0x80, 140)

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self._dimmed = False
        if parent is not None:
            parent.installEventFilter(self)
            self.setGeometry(parent.rect())
        self.raise_()
        self.hide()

    def is_dimmed(self) -> bool:
        return self._dimmed

    def set_dimmed(self, on: bool) -> None:
        # No early-return on an unchanged value: raise_() must re-run so the dim
        # self-heals back on top after a sibling was restacked (e.g. populate()
        # re-parenting a control). Keep this unconditional.
        self._dimmed = bool(on)
        self.setVisible(self._dimmed)
        if self._dimmed:
            self.raise_()
        self.update()

    def eventFilter(self, obj, ev):
        # ChildAdded re-raises us above any sibling the card just re-parented in,
        # so the dim wash stays on top of the content without relying on the
        # caller's restack/hide ordering.
        if obj is self.parent() and ev.type() in (
            QEvent.Resize, QEvent.Show, QEvent.ChildAdded,
        ):
            self.setGeometry(self.parent().rect())
            if self._dimmed:
                self.raise_()
        return super().eventFilter(obj, ev)

    def paintEvent(self, event):
        if not self._dimmed:
            return
        p = QPainter(self)
        p.fillRect(self.rect(), self._WASH)
        p.end()
