#!/usr/bin/env python3
"""macOS ghost-cursor overlay feasibility spike (THROWAWAY, operator-run).

Proves whether a Qt frameless / floating / input-transparent overlay owned by
a backgrounded app reliably floats ABOVE the frontmost TTR window, positioned
correctly, on macOS. Pins the exact NSWindow hardening recipe, the
fail-open-vs-closed click-through policy, and empirical coordinate identity.
Results go into the spec's Section 11. NOT production code.

Run on the Mac:
    /usr/bin/python3 scripts/macos_ghost_overlay_spike.py --mode point --x 800 --y 600
    /usr/bin/python3 scripts/macos_ghost_overlay_spike.py --mode follow --anchor center
Add --recipe N to cycle the candidate NSWindow recipes (see RECIPE_CANDIDATES).
"""
from __future__ import annotations

import argparse
import sys

from PySide6.QtCore import QEvent, QPoint, Qt, QTimer
from PySide6.QtGui import QColor, QGuiApplication, QPainter
from PySide6.QtWidgets import QWidget

# Fingertip hotspot at 32px, identical to the shipped GhostCursorOverlay.
HOTSPOT = (1, 3)
CURSOR_SIZE = 32


def coordinate_readout(emitted, qt_global, overlay_origin, hotspot=HOTSPOT):
    """Compare the three coordinate samples that decide identity.

    emitted        - the (x, y) Click Sync would emit (screen point).
    qt_global      - the Qt global logical point the overlay was moved to.
    overlay_origin - the overlay window frame top-left actually realized.

    A correct darwin identity run has emitted_vs_qt_delta == (0, 0) and
    origin_error == (0, 0). Negative virtual-desktop coordinates pass through
    untouched."""
    ex, ey = int(emitted[0]), int(emitted[1])
    gx, gy = int(qt_global[0]), int(qt_global[1])
    ox, oy = int(overlay_origin[0]), int(overlay_origin[1])
    expected_origin = (gx - hotspot[0], gy - hotspot[1])
    return {
        "emitted": (ex, ey),
        "qt_global": (gx, gy),
        "overlay_origin": (ox, oy),
        "emitted_vs_qt_delta": (gx - ex, gy - ey),
        "expected_origin": expected_origin,
        "origin_error": (ox - expected_origin[0], oy - expected_origin[1]),
    }


# Candidate NSWindow recipes, tried in order by --recipe N. The operator finds
# which one floats above the frontmost TTR window; the winner is recorded in
# spec Section 11. level_name / collection_behavior entries are AppKit symbol
# NAMES, resolved lazily when applied (Task 3) so this module imports anywhere.
RECIPE_CANDIDATES = [
    {
        "name": "floating",
        "level_name": "NSFloatingWindowLevel",
        "collection_behavior": ("NSWindowCollectionBehaviorCanJoinAllSpaces",
                                "NSWindowCollectionBehaviorStationary"),
        "ignores_mouse": True,
    },
    {
        "name": "status",
        "level_name": "NSStatusWindowLevel",
        "collection_behavior": ("NSWindowCollectionBehaviorCanJoinAllSpaces",
                                "NSWindowCollectionBehaviorStationary"),
        "ignores_mouse": True,
    },
    {
        "name": "popup",
        "level_name": "NSPopUpMenuWindowLevel",
        "collection_behavior": ("NSWindowCollectionBehaviorCanJoinAllSpaces",
                                "NSWindowCollectionBehaviorStationary",
                                "NSWindowCollectionBehaviorFullScreenAuxiliary"),
        "ignores_mouse": True,
    },
    {
        # Control: Qt flags only, no native ignoresMouseEvents. Tells us whether
        # WindowTransparentForInput alone guarantees click-through (fail-open) or
        # native ignoresMouseEvents is load-bearing (fail-closed).
        "name": "qt-flags-only",
        "level_name": "NSFloatingWindowLevel",
        "collection_behavior": ("NSWindowCollectionBehaviorCanJoinAllSpaces",),
        "ignores_mouse": False,
    },
]


def describe_recipe(recipe) -> str:
    cb = " | ".join(recipe["collection_behavior"]) or "(none)"
    return (f"recipe '{recipe['name']}': level={recipe['level_name']} "
            f"collectionBehavior=[{cb}] ignoresMouseEvents={recipe['ignores_mouse']}")


def apply_recipe_to_window(window, recipe, *, resolve_level, resolve_behavior,
                           is_panel):
    """Apply a recipe's knobs to an NSWindow-like object. Pure given the three
    injected resolvers (so it is unit-tested on the host with fakes)."""
    window.setLevel_(resolve_level(recipe["level_name"]))
    window.setCollectionBehavior_(resolve_behavior(recipe["collection_behavior"]))
    window.setIgnoresMouseEvents_(bool(recipe["ignores_mouse"]))
    if is_panel(window):
        # Tool windows realized as NSPanel hide when the app deactivates; we want
        # the overlay to persist while TTR (another app) is frontmost.
        window.setHidesOnDeactivate_(False)
    return {"ok": True, "reason": None}


def _appkit_resolvers():
    """Lazily build the AppKit symbol resolvers. Raises if PyObjC/AppKit is
    unavailable; callers wrap this in try/except."""
    import AppKit  # noqa: F401  (PyObjC)
    import objc    # noqa: F401

    def resolve_level(name):
        return int(getattr(AppKit, name))

    def resolve_behavior(names):
        bits = 0
        for n in names:
            bits |= int(getattr(AppKit, n))
        return bits

    def is_panel(window):
        return bool(window.isKindOfClass_(AppKit.NSPanel))

    return resolve_level, resolve_behavior, is_panel


def harden_widget(*, view_resolver, recipe):
    """Resolve the NSWindow from a view (view_resolver() -> NSView) and apply the
    recipe. Never raises; returns {ok, reason, facts}. The facts dict records the
    hard observations the spike exists to capture."""
    facts = {"recipe": recipe["name"]}
    try:
        view = view_resolver()
    except Exception as e:  # winId() / objc wrap failure
        return {"ok": False, "reason": f"view resolve failed: {e}", "facts": facts}
    facts["view_type"] = type(view).__name__
    try:
        window = view.window()
    except Exception as e:
        return {"ok": False, "reason": f"view.window() raised: {e}", "facts": facts}
    facts["window_is_nil"] = window is None
    if window is None:
        return {"ok": False, "reason": "view.window() is nil (not realized yet)",
                "facts": facts}
    try:
        resolve_level, resolve_behavior, is_panel = _appkit_resolvers()
    except Exception as e:
        return {"ok": False, "reason": f"AppKit unavailable: {e}", "facts": facts}
    try:
        apply_recipe_to_window(window, recipe, resolve_level=resolve_level,
                               resolve_behavior=resolve_behavior, is_panel=is_panel)
    except Exception as e:
        return {"ok": False, "reason": f"apply failed: {e}", "facts": facts}
    return {"ok": True, "reason": None, "facts": facts}


class SpikeOverlay(QWidget):
    """Mirrors the shipped GhostCursorOverlay flags. Paints a solid glove-sized
    marker (no asset dependency in the spike) and hardens its NSWindow after the
    native surface is realized, printing the hard facts each time. harden_enabled
    False is the true fail-open control: shown with ZERO native hardening."""

    def __init__(self, recipe, parent=None, harden_enabled=True):
        flags = (Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
                 | Qt.Tool | Qt.WindowTransparentForInput
                 | Qt.WindowDoesNotAcceptFocus)
        super().__init__(parent, flags)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFixedSize(CURSOR_SIZE, CURSOR_SIZE)
        self._recipe = recipe
        self._harden_enabled = harden_enabled

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setBrush(QColor(255, 0, 200, 220))   # vivid so z-order is obvious
        p.setPen(QColor(0, 0, 0, 255))
        p.drawEllipse(2, 2, CURSOR_SIZE - 4, CURSOR_SIZE - 4)

    def _resolve_view(self):
        import objc
        # On cocoa, winId() is an NSView*; wrap the pointer as an objc id.
        # (c_void_p is PyObjC's keyword-arg name, not ctypes.c_void_p.)
        return objc.objc_object(c_void_p=int(self.winId()))

    def _harden(self, why):
        if not self._harden_enabled:
            print(f"[harden:{why}] skipped (--no-harden: true fail-open control)")
            return
        if sys.platform != "darwin":
            return
        res = harden_widget(view_resolver=self._resolve_view, recipe=self._recipe)
        print(f"[harden:{why}] ok={res['ok']} reason={res['reason']} "
              f"facts={res.get('facts')}")

    def show_at(self, x, y):
        self.move(int(x) - HOTSPOT[0], int(y) - HOTSPOT[1])
        # Probe view.window() nil-ness BEFORE show (winId() may realize it),
        # per the spec's before / after / queued-after timing matrix.
        self._harden("pre-show")
        if not self.isVisible():
            self.show()

    def showEvent(self, e):
        super().showEvent(e)
        self._harden("showEvent")
        QTimer.singleShot(0, lambda: self._harden("singleShot"))

    def event(self, e):
        if e.type() == QEvent.PlatformSurface:
            # Native surface (re)created, e.g. on screen change -> re-harden.
            QTimer.singleShot(0, lambda: self._harden("platformSurface"))
        return super().event(e)
