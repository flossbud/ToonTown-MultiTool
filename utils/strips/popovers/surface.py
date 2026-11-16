"""A top-level surface for one popover.

Built like the strip surface: translucent, frameless, never focused, staged
at opacity 0 until its first paint has happened and it is stacked where it
belongs. On X11 it is made transient for its STRIP's window, so the window
manager keeps it over the strip, which it keeps over the game window.
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QRegion
from PySide6.QtWidgets import QWidget

from utils.overlay.region import controls_region


class PopoverSurface(QWidget):
    dismissed = Signal()
    # Same role as on the strip surface: the macOS backend's level lookup.
    WM_WINDOW_TYPE = "strip"

    def __init__(self, strategy, backend, content: QWidget) -> None:
        super().__init__(None)
        self._strategy = strategy
        self._backend = backend
        self.setWindowFlags(strategy.window_flags())
        self.setWindowTitle("TTMT strip popover")
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_DeleteOnClose, False)
        self.setAttribute(Qt.WA_ContentsMarginsRespectsSafeArea, False)
        self.setFocusPolicy(Qt.NoFocus)
        self.content = content
        content.setParent(self)
        content.move(0, 0)
        self._above: int | None = None     # window id this surface stacks over
        self._prepared = False
        self._attached = False
        self._concealed = True
        self._covered = False
        self._visible: QRegion | None = None
        self._shown = False
        self._gone = False
        self.resize(content.sizeHint())

    # -- showing ------------------------------------------------------------

    def is_presented(self) -> bool:
        return self._shown

    def present(self, top_left: QPoint, above_window: int | None) -> None:
        """Show at a global position, stacked over `above_window` (the
        strip's native window id)."""
        if self._gone:
            return
        self._above = int(above_window) if above_window else None
        self.fit(top_left)
        self._concealed = False
        if not self.isVisible():
            if not self._prepared:
                self._prepared = True
                self.winId()
                try:
                    self._strategy.prepare(self, self._backend)
                except Exception:
                    pass
            self.setWindowOpacity(0.0)
            self.show()
        else:
            self._present()

    def fit(self, top_left: QPoint | None = None) -> None:
        """The content changed size, or the popover moves."""
        size = self.content.sizeHint()
        self.content.resize(size)
        pos = top_left if top_left is not None else self.pos()
        self.setGeometry(QRect(pos, size))
        if self.isVisible():
            self._present()

    def conceal(self) -> None:
        """Invisible and inert, still mapped (cheap to show again)."""
        self._concealed = True
        self._present()

    def dismiss(self) -> None:
        """Gone for good."""
        if self._gone:
            return
        self._gone = True
        self._shown = False
        self.hide()
        self.dismissed.emit()
        self.deleteLater()

    def paintEvent(self, _event) -> None:
        if not self._attached:
            QTimer.singleShot(0, self._after_map)

    def _after_map(self) -> None:
        if self._attached or self._gone or not self.isVisible():
            return
        if self._above is not None:
            try:
                self._strategy.attach(self, self._backend, str(self._above))
            except Exception:
                pass
        self._attached = True
        self._present()

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self._shown = False
        if not event.spontaneous():
            self._attached = False

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if event.spontaneous() and self._attached:
            QTimer.singleShot(0, self._restack)

    def _restack(self) -> None:
        if self._gone or not self.isVisible():
            return
        if self._above is not None:
            try:
                self._strategy.attach(self, self._backend, str(self._above))
            except Exception:
                pass
        self._present()

    def closeEvent(self, event) -> None:
        if event.spontaneous():
            event.ignore()
            return
        event.accept()

    # -- gate (platforms that compute visibility) ---------------------------

    def set_visible_region(self, region: QRegion | None) -> None:
        if region is None or region == QRegion(self.rect()):
            covered, visible = False, None
        elif region.isEmpty():
            covered, visible = True, None
        else:
            covered, visible = False, QRegion(region)
        if covered == self._covered and visible == self._visible:
            return
        self._covered, self._visible = covered, visible
        if visible is None:
            self.clearMask()
        else:
            self.setMask(visible)
        self._present()

    # -- presentation -------------------------------------------------------

    def input_region(self) -> QRegion:
        ratio = self._strategy.region_ratio(self)
        rects = getattr(self.content, "input_rects", None)
        rects = rects() if callable(rects) else [self.content.rect()]
        region = controls_region(rects, 1.0, ratio)
        if self._visible is not None:
            mask = QRegion()
            for r in self._visible:
                mask = mask.united(QRegion(
                    round(r.x() * ratio), round(r.y() * ratio),
                    round(r.width() * ratio), round(r.height() * ratio)))
            region = region.intersected(mask)
        return region

    def refresh_input(self) -> None:
        """The content's clickable area changed."""
        self._present()

    def _present(self) -> None:
        shown = (self._attached and not self._concealed and not self._covered
                 and not self._gone and self.isVisible())
        self._shown = shown
        if not self.isVisible():
            return
        try:
            self._backend.apply_input_region(
                self, self.input_region() if shown else QRegion())
        except Exception:
            pass
        self.setWindowOpacity(1.0 if shown else 0.0)
