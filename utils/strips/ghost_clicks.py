"""Ghost cursors pressing strip blocks.

Click sync mirrors a click into the other game windows and shows a glove
there. With "ghost cursors control cards" on, a mirrored press that lands on
a block of that window's strip (or on something hanging off it) presses the
block, the way the real pointer would.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, Qt
from PySide6.QtGui import QGuiApplication, QMouseEvent
from PySide6.QtWidgets import QApplication

from utils import settings_keys
from utils.screen_coords import emitted_to_logical


class GhostClicks(QObject):
    def __init__(self, controller, service=None, settings=None,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._controller = controller
        self._settings = settings
        if service is not None:
            # Emitted on a capture thread: Qt queues it to this object's thread.
            service.ghost_pointer_event.connect(self.on_ghost_event)

    def enabled(self) -> bool:
        s = self._settings
        if s is None:
            return False
        try:
            return bool(s.get(settings_keys.GHOST_CURSORS_ENABLED, True)
                        and s.get(settings_keys.GHOST_CURSORS_CONTROL_CARDS, True))
        except Exception:
            return False

    def on_ghost_event(self, payload) -> None:
        """A queued slot fed from another thread: it must never raise."""
        try:
            kind, items = payload
            if kind != "press" or not self.enabled():
                return
            screens = QGuiApplication.screens()
            for item in items:
                try:
                    slot, x, y = item
                    self.press(int(slot), QPoint(*emitted_to_logical(x, y, screens)))
                except Exception:
                    continue
        except Exception:
            return

    def _targets(self, wid: str):
        """(top-level surface, widget that takes the click), topmost first."""
        pops = self._controller.popovers
        for surface in (pops.open_surface(wid), pops.counters_surface(wid)):
            if surface is not None and surface.is_presented():
                yield surface, surface.content
        strip = self._controller.follower.surface(wid)
        if strip is not None and strip.is_presented():
            yield strip, strip.strip

    def press(self, slot: int, point: QPoint) -> bool:
        """Press whatever block of the strip in `slot` lies under a global
        point. True when something took the click."""
        wid = self._controller.window_for_slot(slot)
        if wid is None:
            return False
        for surface, widget in self._targets(wid):
            if not surface.geometry().contains(point):
                continue
            local = point - surface.pos()
            if not any(r.contains(local) for r in widget.input_rects()):
                continue
            where = QPointF(local)
            for etype in (QEvent.MouseButtonPress, QEvent.MouseButtonRelease):
                held = Qt.LeftButton if etype == QEvent.MouseButtonPress else Qt.NoButton
                QApplication.sendEvent(widget, QMouseEvent(
                    etype, where, QPointF(point), Qt.LeftButton, held, Qt.NoModifier))
            return True
        return False
