"""A top-level surface for one popover.

Built like the strip surface: translucent, frameless, never focused, staged
at opacity 0 until its first paint has happened and it is stacked where it
belongs. On X11 it is made transient for its STRIP's window, so the window
manager keeps it over the strip, which it keeps over the game window.
"""
from __future__ import annotations

from PySide6.QtCore import (QAbstractAnimation, QEasingCurve, QPoint, QRect, Qt,
                            QTimer, Signal, QVariantAnimation)
from PySide6.QtGui import QRegion
from PySide6.QtWidgets import QWidget

from utils.overlay.region import controls_region
from utils import motion

COUNTERS_FADE_IN_MS = 140
COUNTERS_FADE_OUT_MS = 100


class PopoverSurface(QWidget):
    dismissed = Signal()
    # Same role as on the strip surface: the macOS backend's level lookup.
    WM_WINDOW_TYPE = "strip"

    def __init__(self, strategy, backend, content: QWidget, *, fade: bool = False) -> None:
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
        self._fade_enabled = bool(fade)
        self._fade_target = 0.0
        self._fade = QVariantAnimation(self)
        self._fade.setEasingCurve(QEasingCurve.OutCubic)
        self._fade.valueChanged.connect(self._fade_value)
        self._fade.finished.connect(self._fade_finished)
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
            try:
                self._backend.apply_input_region(self, QRegion())
            except Exception:
                pass
            if self._strategy.shaped():
                self._apply_shape(False)
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

    def conceal(self, *, immediate: bool = False) -> None:
        """Drop input now; an opted-in counter may finish fading while mapped.

        Movement and user suppression pass immediate=True: nothing may be
        left at the old position while the game moves away.
        """
        self._concealed = True
        self._present(immediate=immediate)

    def dismiss(self) -> None:
        """Gone for good."""
        if self._gone:
            return
        self._gone = True
        self._present(immediate=True)
        self._fade.stop()
        self.hide()
        self.dismissed.emit()
        self.deleteLater()

    def paintEvent(self, _event) -> None:
        if not self._attached:
            QTimer.singleShot(0, self, self._after_map)

    def _after_map(self) -> None:
        if self._attached or self._gone or not self.isVisible():
            return
        self._attached = self._attach()
        self._present()

    def _attach(self) -> bool:
        if self._above is not None:
            try:
                return bool(self._strategy.attach(self, self._backend, str(self._above)))
            except Exception:
                return False
        return True

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self._fade.stop()
        self._shown = False
        if not event.spontaneous():
            self._attached = False

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if event.spontaneous() and self._attached:
            QTimer.singleShot(0, self, self._restack)

    def _restack(self) -> None:
        if self._gone or not self.isVisible():
            return
        self._attached = self._attach()
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

    def _apply_shape(self, shown: bool) -> None:
        """No compositor: cut the window to what the content paints."""
        try:
            backed = getattr(self.content, "set_backed", None)
            if callable(backed):
                backed(True)
            shape = getattr(self.content, "shape_region", None)
            region = shape() if callable(shape) else QRegion(self.content.rect())
            self._strategy.set_shape(self, region if shown else QRegion())
            self._shape_set = True
        except Exception:
            pass

    def refresh_presentation(self) -> None:
        """A compositing manager came or went."""
        if not self._strategy.shaped() and getattr(self, "_shape_set", False):
            self._shape_set = False
            try:
                backed = getattr(self.content, "set_backed", None)
                if callable(backed):
                    backed(False)
                self._strategy.set_shape(self, None)
            except Exception:
                pass
        self._present()

    def refresh_input(self) -> None:
        """The content's clickable area changed."""
        self._present()

    def _set_shown(self, shown: bool) -> None:
        was_shown, self._shown = self._shown, bool(shown)
        if was_shown and not self._shown:
            cancel = getattr(self.content, "cancel_capture", None)
            if callable(cancel):
                cancel()

    def _apply_input(self) -> None:
        try:
            self._backend.apply_input_region(
                self, self.input_region() if self._shown else QRegion())
        except Exception:
            pass
        if self._strategy.shaped():
            self._apply_shape(self._shown)

    def _may_fade(self) -> bool:
        return (self._fade_enabled and not self._strategy.shaped()
                and not motion.is_reduced())

    def _fade_value(self, value) -> None:
        if self._gone:
            return
        if not self._may_fade():
            self._present(immediate=True)
            return
        self.setWindowOpacity(float(value))

    def _fade_finished(self) -> None:
        self._present(immediate=True)

    def _present(self, *, immediate: bool = False) -> None:
        wanted = (self._attached and not self._concealed and not self._covered
                  and not self._gone and self.isVisible())
        if not self.isVisible():
            self._fade.stop()
            self._set_shown(False)
            return
        target = 1.0 if wanted else 0.0
        # First paint/attach and the occlusion gate always win over animation.
        instant = (immediate or not self._attached or self._covered or self._gone
                   or not self._may_fade())
        if instant:
            self._fade.stop()
            self._fade_target = target
            if not wanted:
                self._set_shown(False)
                self._apply_input()
            self.setWindowOpacity(target)
            self._set_shown(wanted)
            self._apply_input()
            return
        if self._fade.state() == QAbstractAnimation.Running and self._fade_target == target:
            self._set_shown(False)
            self._apply_input()
            return
        current = self.windowOpacity()
        self._fade.stop()
        self._fade_target = target
        if abs(current - target) < 1e-6:
            self._set_shown(wanted)
            self._apply_input()
            return
        # No interactive region during either transition. In particular the
        # region is dropped before the first fade-out frame, and only the
        # finished callback restores it after a fade-in reaches full opacity.
        self._set_shown(False)
        self._apply_input()
        duration = COUNTERS_FADE_IN_MS if wanted else COUNTERS_FADE_OUT_MS
        duration = round(duration * abs(target - current) * motion._TEST_DURATION_SCALE)
        if duration <= 0:
            self._present(immediate=True)
            return
        # Reconfiguring a stopped animation can emit its old current-time
        # value. Only the new run may write opacity, including on reversal.
        blocked = self._fade.blockSignals(True)
        try:
            self._fade.setStartValue(current)
            self._fade.setEndValue(target)
            self._fade.setDuration(duration)
        finally:
            self._fade.blockSignals(blocked)
        self._fade.start()
