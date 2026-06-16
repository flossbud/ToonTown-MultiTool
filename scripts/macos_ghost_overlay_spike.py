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
import os
import sys

# Run-as-script: put the repo root on sys.path so the follow mode's
# `from utils import macos_discovery` resolves (otherwise sys.path[0] is
# scripts/ and `utils` is not importable).
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

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
        # Only poke the native NSWindow on the REAL cocoa backend. Under any
        # other QPA (offscreen in tests, or a stray non-cocoa run) winId() is
        # not an NSView pointer, so resolving it through objc would segfault.
        if sys.platform != "darwin" or QGuiApplication.platformName() != "cocoa":
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


def anchor_point(geom, anchor):
    """Map a TTR window content-rect (x, y, w, h) + anchor name to a screen
    point. Pure."""
    x, y, w, h = geom
    if anchor == "center":
        return (x + w // 2, y + h // 2)
    if anchor == "corner":
        return (x, y)
    if anchor == "br":
        return (x + w, y + h)
    raise ValueError(f"unknown anchor {anchor!r}")


def _list_ttr_windows():
    """Live TTR windows via the real discovery path (operator-run on the Mac)."""
    from utils import macos_discovery as macd
    return [gw for gw in macd.find_game_windows() if gw.game == "ttr"]


def _schedule_measurement(ov, emitted, delay_ms=300):
    """After the event loop has realized AND positioned the overlay, measure
    where it ACTUALLY landed (realized Qt geometry) vs where we asked. Reading
    ov.x()/ov.y() synchronously right after move() would be self-referential."""
    def _measure():
        origin = ov.frameGeometry().topLeft()
        ghot = ov.mapToGlobal(QPoint(*HOTSPOT))   # realized global pos of hotspot
        r = coordinate_readout(emitted=emitted,
                               qt_global=(ghot.x(), ghot.y()),
                               overlay_origin=(origin.x(), origin.y()))
        print(f"[coords:realized] {r}")
    QTimer.singleShot(delay_ms, _measure)


def _run_point(recipe, x, y, harden_enabled):
    ov = SpikeOverlay(recipe, harden_enabled=harden_enabled)
    ov.show_at(x, y)
    print(f"[point] {describe_recipe(recipe)} harden_enabled={harden_enabled}")
    _schedule_measurement(ov, (x, y))
    return ov


def _run_follow(recipe, anchor, index, harden_enabled):
    from utils import macos_discovery as macd
    wins = _list_ttr_windows()
    if not wins:
        print("[follow] no TTR windows found; open a toon first")
        return None
    gw = wins[min(index, len(wins) - 1)]
    geom = macd.get_window_geometry_fresh(str(gw.window_id)) or gw.bounds
    pt = anchor_point(geom, anchor)
    ov = SpikeOverlay(recipe, harden_enabled=harden_enabled)
    ov.show_at(*pt)
    print(f"[follow] window_id={gw.window_id} owner={gw.owner!r} geom={geom}")
    print(f"[follow] {describe_recipe(recipe)} harden_enabled={harden_enabled}")
    _schedule_measurement(ov, pt)
    return ov


def _build_parser():
    ap = argparse.ArgumentParser(description="macOS ghost-overlay spike")
    ap.add_argument("--mode", choices=("point", "follow"), default="point")
    ap.add_argument("--x", type=int, default=800)
    ap.add_argument("--y", type=int, default=600)
    ap.add_argument("--anchor", choices=("center", "corner", "br"), default="center")
    ap.add_argument("--index", type=int, default=0, help="which TTR window (follow)")
    ap.add_argument("--recipe", type=int, default=0,
                    help=f"0..{len(RECIPE_CANDIDATES) - 1}")
    ap.add_argument("--no-harden", action="store_true",
                    help="skip ALL native NSWindow hardening: the true fail-open "
                         "control (is Qt's WindowTransparentForInput alone "
                         "click-through?)")
    ap.add_argument("--seconds", type=int, default=20, help="how long to show")
    return ap


def main(argv=None):
    args = _build_parser().parse_args(argv)
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    # A misleading-facts guard: a Mac run on the wrong backend (e.g. offscreen)
    # must be obvious in the log.
    print(f"[spike] Qt platform = {QGuiApplication.platformName()!r} "
          f"(expect 'cocoa' on a real Mac run)")
    recipe = RECIPE_CANDIDATES[args.recipe]
    harden_enabled = not args.no_harden

    if args.mode == "point":
        ov = _run_point(recipe, args.x, args.y, harden_enabled)
    else:
        ov = _run_follow(recipe, args.anchor, args.index, harden_enabled)
    if ov is None:
        return 1
    QTimer.singleShot(args.seconds * 1000, app.quit)
    print(f"[spike] showing for {args.seconds}s; focus a TTR toon and observe "
          f"z-order + click-through. Ctrl-C to stop early.")
    app.exec()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
