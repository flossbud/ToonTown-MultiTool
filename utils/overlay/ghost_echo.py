"""Glove echo layer: ghost cursors composited onto the cluster's own content.

The confined click-sync ghost overlays (tabs.multitoon._ghost_cursors) stack
directly above their game window and BELOW everything else - including this
DOCK-layer cluster window, whose cards deliberately float over the games. A
glove that wanders over a card therefore vanishes under it, even though the
glove can press that card's controls (ghost control clicks). No window
stacking can fix that: the cluster sits in a WM layer above every regular
window, so "above the cards but below a file manager" is a stacking cycle.
Instead the cluster window paints the glove itself.

``GhostEchoLayer`` is a paint-only, input-inert child of the cluster surface,
raised above the hosted cluster view. The ``GhostCursorController`` mirrors
every glove state change into it through the cluster controller's
``ghost_echo_*`` sink methods, and the layer draws the glove pixmaps CLIPPED
to the union of the visible cards' painted bodies plus the emblem disc
(``ClusterOverlayController._echo_content_path``). Echo pixels therefore exist
only where cluster content actually covers the under-layer glove; everywhere
else (the transparent envelope, the gaps between cards) nothing is drawn and
the confined ghost - correctly stacked below any occluder - stays the sole
renderer. FAIL-CLOSED: with no clip path the layer draws nothing at all, so a
geometry failure can never float a glove over a window that should cover it.

Input safety: the widget is ``WA_TransparentForMouseEvents`` and the X11
input shape lives on the WINDOW (untouched by children), so the echo can
never eat a click or register in the click-sync resolver's hit tests.
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, Qt, QVariantAnimation
from PySide6.QtGui import QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QWidget


class GhostEchoLayer(QWidget):
    """Paint-only glove echoes, clipped to the cluster's visible content."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        # Never erase/fill a background: this layer composites over the hosted
        # cluster view and must stay fully transparent wherever it does not
        # explicitly draw a sprite.
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        # slot -> {"pos": QPoint (sprite top-left, layer-local), "pixmap":
        # QPixmap, "opacity": float, "fade": QVariantAnimation | None}
        self._slots: dict[int, dict] = {}
        self._clip: QPainterPath | None = None

    # -- state pushed by the controller sink (GUI thread) ----------------

    def set_clip(self, path: QPainterPath | None) -> None:
        """The window-local painted-content path echoes are confined to.
        ``None`` (or an empty path) draws NOTHING - fail closed, never a
        full-window echo that would float over occluders in the transparent
        envelope."""
        self._clip = path
        self.update()

    def show_slot(self, slot: int, pos: QPoint, pixmap: QPixmap) -> None:
        """Show/move one slot's glove sprite (top-left at *pos*, layer-local
        logical coords) at full opacity, cancelling any in-flight fade."""
        entry = self._slots.get(slot)
        dirty = QRect()
        if entry is not None:
            self._stop_fade(entry)
            dirty = self._sprite_rect(entry)
            entry["pos"] = QPoint(pos)
            entry["pixmap"] = pixmap
            entry["opacity"] = 1.0
        else:
            entry = {"pos": QPoint(pos), "pixmap": pixmap,
                     "opacity": 1.0, "fade": None}
            self._slots[slot] = entry
        self.update(dirty.united(self._sprite_rect(entry)))

    def fade_slot(self, slot: int, duration_ms: int) -> None:
        """Fade one slot's echo out over *duration_ms* (mirrors the overlay's
        idle fade), dropping the slot when it reaches zero. No-op for a slot
        that is not showing."""
        entry = self._slots.get(slot)
        if entry is None or entry["fade"] is not None:
            return
        anim = QVariantAnimation(self)
        anim.setDuration(max(0, int(duration_ms)))
        anim.setStartValue(float(entry["opacity"]))
        anim.setEndValue(0.0)
        anim.valueChanged.connect(
            lambda v, s=slot: self._on_fade_value(s, v))
        anim.finished.connect(lambda s=slot: self.hide_slot(s))
        entry["fade"] = anim
        anim.start()

    def hide_slot(self, slot: int) -> None:
        """Drop one slot's echo immediately."""
        entry = self._slots.pop(slot, None)
        if entry is None:
            return
        self._stop_fade(entry)
        self.update(self._sprite_rect(entry))

    def clear(self) -> None:
        """Drop every echo immediately."""
        for entry in self._slots.values():
            self._stop_fade(entry)
        if self._slots:
            self._slots.clear()
            self.update()

    # -- internals --------------------------------------------------------

    @staticmethod
    def _sprite_rect(entry: dict) -> QRect:
        """The sprite's layer-local logical rect (pixmap DPR-aware)."""
        pm = entry["pixmap"]
        size = pm.deviceIndependentSize().toSize()
        return QRect(entry["pos"], size)

    @staticmethod
    def _stop_fade(entry: dict) -> None:
        anim = entry.get("fade")
        if anim is not None:
            entry["fade"] = None
            anim.stop()
            anim.deleteLater()

    def _on_fade_value(self, slot: int, value) -> None:
        entry = self._slots.get(slot)
        if entry is None:
            return
        entry["opacity"] = float(value)
        self.update(self._sprite_rect(entry))

    def paintEvent(self, _event) -> None:
        clip = self._clip
        if clip is None or clip.isEmpty() or not self._slots:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        p.setClipPath(clip)
        for entry in self._slots.values():
            op = entry["opacity"]
            if op <= 0.0:
                continue
            p.setOpacity(op)
            p.drawPixmap(entry["pos"], entry["pixmap"])
        p.end()
