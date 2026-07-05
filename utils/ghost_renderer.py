"""Ghost-renderer helper process: cursor-class glove motion (main.py
--ghost-renderer).

CP17: the app's single Qt loop + GIL floor glove cadence at ~50-60Hz under
live load no matter how cheap the per-frame work is. This process's loop
does NOTHING but draw up to four glove windows, so its 4ms frame timer
actually fires every ~4ms and glove motion tracks the display.

Feed: newline protocol on STDIN (utils.ghost_feed_protocol), written by the
app's CAPTURE THREAD - the app's GUI loop is not in the path at all. The
reader thread stores positions into a newest-wins per-slot dict (never
touches Qt); the GUI-side frame timer samples it - the same sampling model
the in-process renderer uses, minus the busy loop underneath. Control
messages (focus/clear/quit) ride a deque drained by the same tick, so ALL
Qt work stays on this process's GUI thread with no cross-thread signals.

Lifecycle: stdin EOF = the app died or dropped the pipe -> quit (the glove
windows must never outlive the app; fail-closed). 'Q' is the polite form.

Never-active-app laws honored here:
- CP8: a panel belonging to a NEVER-ACTIVE app does not map on plain
  show(); every show is followed by orderFrontRegardless.
- The process sets NSApplicationActivationPolicyAccessory: no Dock icon,
  no menu bar, never activates.
- Hardening rides GhostCursorOverlay's own recipe (level GHOST_WINDOW_LEVEL,
  click-through, all-Spaces, fail-closed) - one proven implementation.

Occlusion: same shared machinery as in-process (snapshot stale-while-
revalidate + per-snapshot region inputs), running on THIS process's
threads; the target wid arrives with every position message.
"""
from __future__ import annotations

import collections
import os
import sys
import threading
import time

from utils.ghost_feed_protocol import decode_line

IDLE_HIDE_S = 1.5      # match the in-process renderer's fade timing
# 8ms ~ 125fps: matches the panel. 4ms ticks + interpolation drove 312-490
# window moves/s and the WINDOW SERVER punished the flood with blocking
# backpressure - the renderer's own loop stalled up to 489ms (measured) and
# gloves froze outright. Cross-process NSWindow moves are not a 240Hz
# animation primitive; cap the churn at display rate.
FRAME_INTERVAL_MS = 8
SWEEP_INTERVAL_S = 0.10

# Display smoothing: render the stream this far behind real time and
# INTERPOLATE between samples. The feed is produced inside the app process,
# whose GIL/lock bursts bunch deliveries by 20-40ms once or twice a second
# (measured, TTMT_CLICK_DIAG) - at 120Hz that is a visible 3-5-frame hiccup
# no app-side tuning can remove. Replaying the stream on a fixed delay
# absorbs any bunch up to the window by construction; for a mirror glove on
# ANOTHER window, constant display latency is imperceptible (aim/clicks ride
# the injection path, untouched). 0 disables smoothing (render newest).
DISPLAY_SMOOTH_S = max(0, int(os.environ.get("TTMT_GHOST_SMOOTH_MS", "40"))) / 1000.0
_SAMPLE_KEEP_S = 0.5   # buffer horizon (>> smoothing window)


def _sample_at(samples, target_t):
    """Interpolated (x, y) at time target_t from [(t, x, y), ...] (ascending).
    Newest sample older than target_t -> hold newest (stream idle). Oldest
    sample newer than target_t -> newest too (stream just started: instant
    appearance beats delayed fidelity for the first frames). Pure."""
    if not samples:
        return None
    if samples[-1][0] <= target_t:
        t, x, y = samples[-1]
        return (x, y)
    prev = None
    nxt = None
    for t, x, y in reversed(samples):
        if t <= target_t:
            prev = (t, x, y)
            break
        nxt = (t, x, y)
    if prev is None:
        t, x, y = samples[-1]
        return (x, y)
    span = nxt[0] - prev[0]
    if span <= 0:
        return (nxt[1], nxt[2])
    alpha = (target_t - prev[0]) / span
    return (prev[1] + (nxt[1] - prev[1]) * alpha,
            prev[2] + (nxt[2] - prev[2]) * alpha)


class GhostRendererCore:
    """The renderer's testable core: message application + frame rendering.
    Constructed on the GUI thread of a live QApplication (offscreen in
    tests, cocoa in production)."""

    def __init__(self, exempt_pids=None):
        from PySide6.QtCore import Qt, QTimer

        self._latest: dict[int, tuple[int, int, str | None]] = {}
        self._rendered_seq: dict[int, int] = {}
        self._seq: dict[int, int] = {}
        # Smoothing buffers: slot -> list of (t, x, y), appended on the
        # reader thread, consumed by the tick (GIL-atomic list ops; the
        # tick swaps/prunes). The newest wid rides _latest.
        self._samples: dict[int, list] = {}
        self._last_drawn: dict[int, tuple] = {}
        self._controls: collections.deque = collections.deque()
        self._overlays: dict[int, object] = {}
        self._focused_wid: str | None = None
        self._last_sample_t: dict[int, float] = {}
        self._last_sweep = 0.0
        self._quit_requested = False
        # "Own windows never occlude" spans the whole TTMT process FAMILY:
        # this renderer AND the app that spawned it (the parent). With only
        # the renderer's pid exempt, the app's float cards - which sit
        # ABOVE the game windows - carved gloves to nothing wherever they
        # overlapped (live 3-toon regression: toon 2's glove vanished).
        self._exempt_pids = frozenset(
            exempt_pids if exempt_pids is not None
            else (os.getpid(), os.getppid()))
        # Per-target region inputs, valid for one snapshot identity:
        # {target: (snapshot, inputs)} - multiple gloves alternate targets
        # every tick, so a single-entry cache would thrash.
        self._inputs_cache: dict[int, tuple] = {}
        # Opt-in arrival diagnostics (TTMT_CLICK_DIAG, inherited from the
        # app): the renderer draws within one 4ms tick of what it RECEIVES,
        # so residual jank means the FEED is bursty - inter-arrival gaps of
        # position batches (reader thread) are the discriminator. Gaps
        # >500ms are stream restarts, not jitter, and reset the chain.
        self._rdiag = None
        if os.environ.get("TTMT_CLICK_DIAG"):
            self._rdiag = {"t0": time.monotonic(), "batches": 0,
                           "last_arr": 0.0, "arr_s": 0.0, "arr_max": 0.0,
                           "arrs": 0, "renders": 0, "last_tick": 0.0,
                           "tick_s": 0.0, "tick_max": 0.0, "ticks": 0}
        self._timer = QTimer()
        self._timer.setTimerType(Qt.PreciseTimer)
        self._timer.setInterval(FRAME_INTERVAL_MS)
        self._timer.timeout.connect(self.tick)

    # -- reader-thread side (never touches Qt) --------------------------

    def feed_line(self, line: str) -> None:
        msg = decode_line(line)
        if msg is None:
            return
        if msg[0] == "position":
            _kind, slot, x, y, wid, t_ms = msg
            now = time.monotonic()
            # Replay timeline: the capture's EVENT stamp (kernel CGEvent
            # time - same since-boot basis as monotonic, in BOTH processes)
            # keeps sample spacing true even when DELIVERY bunches (the
            # whole point of the jitter buffer; arrival stamps replayed the
            # bunching verbatim). Fallback to arrival on old feeds or a
            # basis surprise (>5s divergence).
            if t_ms is not None and abs(now - t_ms / 1000.0) < 5.0:
                t_evt = t_ms / 1000.0
            else:
                t_evt = now
            self._latest[slot] = (x, y, wid)
            self._seq[slot] = self._seq.get(slot, 0) + 1
            self._last_sample_t[slot] = now
            buf = self._samples.get(slot)
            if buf is None:
                buf = self._samples[slot] = []
            if buf and t_evt <= buf[-1][0]:
                # Coalesced/equal stamps must stay strictly ascending for
                # the interpolator.
                t_evt = buf[-1][0] + 0.0001
            buf.append((t_evt, x, y))
            d = self._rdiag
            if d is not None:
                now = time.monotonic()
                last = d["last_arr"]
                if last and now - last < 0.5:
                    gap = now - last
                    d["arr_s"] += gap
                    d["arrs"] += 1
                    if gap > d["arr_max"]:
                        d["arr_max"] = gap
                d["last_arr"] = now
                d["batches"] += 1
        else:
            self._controls.append(msg)

    def feed_eof(self) -> None:
        self._controls.append(("quit",))

    # -- GUI-thread side -------------------------------------------------

    def start(self) -> None:
        self._timer.start()

    def tick(self) -> None:
        now = time.monotonic()
        while self._controls:
            msg = self._controls.popleft()
            if msg[0] == "quit":
                self._quit_requested = True
                self._hide_all()
                from PySide6.QtWidgets import QApplication
                app = QApplication.instance()
                if app is not None:
                    app.quit()
                return
            if msg[0] == "clear":
                self._hide_all()
            elif msg[0] == "focus":
                self._focused_wid = msg[1]
                # The focused window never shows a ghost: hide any glove
                # currently on it (its stream stops arriving suppressed).
                for slot, (_x, _y, wid) in list(self._latest.items()):
                    if wid and wid == self._focused_wid:
                        ov = self._overlays.get(slot)
                        if ov is not None:
                            ov.hide_now()
        rendered = 0
        target_t = now - DISPLAY_SMOOTH_S
        for slot, buf in list(self._samples.items()):
            if not buf:
                continue
            if DISPLAY_SMOOTH_S > 0:
                pos = _sample_at(buf, target_t)
            else:
                pos = (buf[-1][1], buf[-1][2])
            if pos is None:
                continue
            x, y = int(round(pos[0])), int(round(pos[1]))
            latest = self._latest.get(slot)
            wid = latest[2] if latest is not None else None
            # Draw only on change; the focused wid is part of the key so a
            # focus flip re-evaluates suppression for a stationary glove.
            key = (x, y, wid, self._focused_wid)
            if self._last_drawn.get(slot) != key:
                self._last_drawn[slot] = key
                self._render(slot, x, y, wid)
                rendered += 1
            cutoff = target_t - _SAMPLE_KEEP_S
            while len(buf) > 2 and buf[0][0] < cutoff:
                buf.pop(0)
        d = self._rdiag
        if d is not None:
            if rendered:
                d["renders"] += rendered
                last = d["last_tick"]
                if last and now - last < 0.5:
                    gap = now - last
                    d["tick_s"] += gap
                    d["ticks"] += 1
                    if gap > d["tick_max"]:
                        d["tick_max"] = gap
                d["last_tick"] = now
            elapsed = now - d["t0"]
            if elapsed >= 1.0 and d["batches"]:
                arr_mean = (d["arr_s"] / d["arrs"] * 1000) if d["arrs"] else 0.0
                tick_mean = (d["tick_s"] / d["ticks"] * 1000) if d["ticks"] else 0.0
                print(f"[renderer_perf] arrivals={d['batches']/elapsed:.0f}/s "
                      f"gap mean={arr_mean:.1f}ms max={d['arr_max']*1000:.1f}ms | "
                      f"renders={d['renders']/elapsed:.0f}/s render gap "
                      f"mean={tick_mean:.1f}ms max={d['tick_max']*1000:.1f}ms",
                      flush=True)
                d.update(t0=now, batches=0, arr_s=0.0, arr_max=0.0, arrs=0,
                         renders=0, tick_s=0.0, tick_max=0.0, ticks=0)
        if now - self._last_sweep >= SWEEP_INTERVAL_S:
            self._last_sweep = now
            self._sweep(now)

    def _render(self, slot: int, x: int, y: int, wid: str | None) -> None:
        if self._focused_wid and wid and wid == self._focused_wid:
            ov = self._overlays.get(slot)
            if ov is not None:
                ov.hide_now()
            return
        region = self._compute_region(slot, x, y, wid)
        ov = self._overlay_for(slot)
        if ov is None:
            return
        if region is not None and region.isEmpty():
            ov.hide_now()
            return
        was_visible = ov.isVisible()
        ov.show_at(x, y)
        if not was_visible:
            # CP8: never-active app - plain show() may not map. Ordering is
            # a window-server op, so ONLY on the hidden->shown transition
            # (calling it per frame was ~390 ordering ops/sec).
            _order_front(ov)
        ov.set_visible_region(region)

    def _compute_region(self, slot: int, x: int, y: int, wid: str | None):
        """Occlusion mask, same shared machinery as in-process. None = fail
        open (no wid / no snapshot yet / TTMT_GHOST_UNCONFINED=1 - the env
        is inherited from the app, keeping the kill switch's semantics)."""
        if not wid or os.environ.get("TTMT_GHOST_UNCONFINED") == "1":
            return None
        from PySide6.QtCore import QRect
        from tabs.multitoon._ghost_cursors import (
            CURSOR_SIZE, HOTSPOT, _darwin_zorder_snapshot,
            _region_from_inputs, _scan_region_inputs,
        )
        snapshot = _darwin_zorder_snapshot()
        if snapshot is None:
            return None
        try:
            target = int(wid)
        except (TypeError, ValueError):
            return None
        glove = QRect(int(x) - HOTSPOT[0], int(y) - HOTSPOT[1],
                      CURSOR_SIZE, CURSOR_SIZE)
        cached = self._inputs_cache.get(target)
        if cached is not None and cached[0] is snapshot:
            inputs = cached[1]
        else:
            inputs = _scan_region_inputs(target, snapshot, self._exempt_pids,
                                         lambda a, b: (a, b))
            self._inputs_cache[target] = (snapshot, inputs)
        return _region_from_inputs(glove, inputs)

    def _sweep(self, now: float) -> None:
        """Idle fades + occlusion refresh for stationary gloves (the same
        two jobs the in-process idle timers and occlusion sweep do)."""
        for slot, ov in self._overlays.items():
            if not ov.isVisible():
                continue
            last = self._last_sample_t.get(slot, 0.0)
            if now - last >= IDLE_HIDE_S:
                ov.fade_out()
                continue
            latest = self._latest.get(slot)
            if latest is not None:
                x, y, wid = latest
                region = self._compute_region(slot, x, y, wid)
                if region is not None and region.isEmpty():
                    ov.hide_now()
                else:
                    ov.set_visible_region(region)

    def _overlay_for(self, slot: int):
        ov = self._overlays.get(slot)
        if ov is not None:
            return ov
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QGuiApplication, QPixmap
        from tabs.multitoon._ghost_cursors import (
            CURSOR_SIZE, SLOT_COUNT, GhostCursorOverlay, _cursor_path,
        )
        if not 0 <= slot < SLOT_COUNT:
            return None
        pm = QPixmap(_cursor_path(slot))
        if pm.isNull():
            return None
        screen = QGuiApplication.primaryScreen()
        dpr = screen.devicePixelRatio() if screen is not None else 1.0
        scaled = pm.scaled(round(CURSOR_SIZE * dpr), round(CURSOR_SIZE * dpr),
                           Qt.KeepAspectRatio, Qt.SmoothTransformation)
        scaled.setDevicePixelRatio(dpr)
        ov = GhostCursorOverlay(scaled, confined=False)
        self._overlays[slot] = ov
        return ov

    def _hide_all(self) -> None:
        for ov in self._overlays.values():
            ov.hide_now()
        self._latest.clear()
        self._seq.clear()
        self._rendered_seq.clear()
        self._samples.clear()
        self._last_drawn.clear()
        self._last_sample_t.clear()


def _order_front(ov) -> None:
    """orderFrontRegardless on the overlay's NSWindow (cocoa only, queued
    is unnecessary - show_at already ran). CP8: windows of a never-active
    app need this to actually map. Never raises."""
    try:
        from PySide6.QtGui import QGuiApplication
        if QGuiApplication.platformName() != "cocoa":
            return
        import objc
        view = objc.objc_object(c_void_p=int(ov.winId()))
        window = view.window()
        if window is not None:
            window.orderFrontRegardless()
    except Exception:
        pass


def _set_accessory_policy() -> None:
    """No Dock icon, no menu bar, never activates. Cocoa only; never
    raises (offscreen tests and exotic setups just skip it)."""
    try:
        from PySide6.QtGui import QGuiApplication
        if QGuiApplication.platformName() != "cocoa":
            return
        import AppKit
        AppKit.NSApp.setActivationPolicy_(
            AppKit.NSApplicationActivationPolicyAccessory)
    except Exception:
        pass


def run_ghost_renderer() -> int:
    """Process entry (main.py --ghost-renderer). Blocks in the Qt loop
    until stdin EOF or a Q message."""
    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)   # gloves hide/show constantly
    _set_accessory_policy()
    core = GhostRendererCore()

    def _reader():
        try:
            for line in sys.stdin:
                core.feed_line(line)
        except Exception:
            pass
        core.feed_eof()

    threading.Thread(target=_reader, name="ghost-feed-reader",
                     daemon=True).start()
    core.start()
    print(f"[GhostRenderer] ready pid={os.getpid()} "
          f"frame={FRAME_INTERVAL_MS}ms", flush=True)
    app.exec()
    return 0
