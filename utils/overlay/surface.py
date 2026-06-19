"""Parentless, frameless, always-on-top, non-activating widget surface.

Hosts a single borrowed child widget that fills it completely. The surface
paints nothing; the hosted widget paints its own opaque body.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QRect
from PySide6.QtWidgets import QWidget, QVBoxLayout

from utils.overlay.backend import OverlayBackend, get_overlay_backend


class OverlaySurface(QWidget):
    """Generic overlay surface for a single borrowed child widget.

    Must be constructed with NO Qt parent so it stays visible when the main
    window is minimized. Window flags and attributes keep it frameless,
    always-on-top, and non-activating.

    OWNERSHIP CONTRACT (load-bearing for the reparent transaction, Task 4.1):
    this surface never OWNS the hosted widget, but Qt's parent-child
    destruction WILL delete the hosted widget if the surface is destroyed
    while still hosting it. Callers MUST call ``release()`` before destroying
    or deallocating the surface. ``WA_DeleteOnClose=False`` only guards the
    ``close()`` path, not destruction/GC.
    """

    def __init__(self, backend: OverlayBackend | None = None) -> None:
        # Parentless: do not pass a parent so this is always a top-level window.
        super().__init__(None)

        self._backend: OverlayBackend = backend if backend is not None else get_overlay_backend()
        self._hosted: QWidget | None = None
        self._backend_applied: bool = False

        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
            | Qt.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        # Explicitly keep WA_DeleteOnClose OFF to avoid destroying a borrowed widget.
        self.setAttribute(Qt.WA_DeleteOnClose, False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._layout = layout

    # ------------------------------------------------------------------
    # Child management
    # ------------------------------------------------------------------

    def host(self, widget: QWidget) -> None:
        """Reparent *widget* into this surface as the sole full-bleed child.

        If a widget is already hosted, it is released first (no stacking).
        Hosting ``None`` is a no-op (use ``release()`` to clear the surface).
        """
        if widget is None:
            return
        if self._hosted is widget:
            return
        if self._hosted is not None:
            self.release()
        # If the widget is currently hosted by ANOTHER OverlaySurface, release it
        # there first so that surface's _hosted tracking does not go stale (a later
        # release() on it would otherwise orphan the widget out from under us).
        prev = widget.parent()
        if isinstance(prev, OverlaySurface) and prev is not self and prev._hosted is widget:
            prev.release()
        widget.setParent(self)
        self._layout.addWidget(widget)
        self._hosted = widget

    def release(self) -> QWidget | None:
        """Remove the hosted widget from this surface without deleting it.

        Returns the widget (with parent set to None) or None if nothing hosted.
        """
        w = self._hosted
        if w is None:
            return None
        self._layout.removeWidget(w)
        w.setParent(None)  # type: ignore[arg-type]
        self._hosted = None
        return w

    # ------------------------------------------------------------------
    # Geometry
    # ------------------------------------------------------------------

    def set_overlay_geometry(self, rect: QRect) -> None:
        """Set size and position in ONE atomic call to avoid single-frame judder."""
        self.setGeometry(rect)

    # ------------------------------------------------------------------
    # Show event: apply backend hints once native window handle exists
    # ------------------------------------------------------------------

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._backend_applied:
            self._backend_applied = True
            # Independent operations: a failure of one must not skip the other,
            # or the surface could end up "above" but still activating.
            try:
                self._backend.set_above(self)
            except Exception:
                pass
            try:
                self._backend.set_non_activating(self)
            except Exception:
                pass
