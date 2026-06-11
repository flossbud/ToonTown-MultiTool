"""Observe-only global mouse capture for click sync on Windows.

pynput's WH_MOUSE_LL listener plays the XRecord thread's role: real device
input only -- PostMessage'd synthetic traffic bypasses the input pipeline
and never reaches LL hooks (spike-verified 2026-06-11), so the feature
cannot echo its own injections. The hook NEVER suppresses anything
(observe-only, per the project's TOS posture).

Emits the XRecordCapture event contract: on_event(kind, root_x, root_y,
state, time_ms) with kind in 'press' | 'release' | 'motion'. `state` is
the X-style button mask (Button1Mask=0x100 ...) -- the service's lingua
franca -- synthesized from a locally tracked held-button set with X
semantics: a press does NOT yet include its own button, a release STILL
includes it.

pynput is imported lazily inside the default listener factory so this
module imports cleanly on every platform (self-check sweep, Linux CI).
"""
from __future__ import annotations

import threading
from time import monotonic

# X-style button masks (Button1Mask..Button5Mask).
_X_BUTTON_MASK = {1: 0x100, 2: 0x200, 3: 0x400, 4: 0x800, 5: 0x1000}
# pynput Button.name -> X button number. Extra buttons (x1/x2) have no X
# core equivalent the service cares about; they are ignored entirely.
_PYNPUT_TO_X = {"left": 1, "middle": 2, "right": 3}


def mask_for(held: set[int]) -> int:
    m = 0
    for b in held:
        m |= _X_BUTTON_MASK.get(b, 0)
    return m


class Win32MouseCapture:
    """XRecordCapture-contract capture: start() -> bool, stop()
    (idempotent, any thread), is_running(). Left-button presses/releases
    are emitted; other known buttons only update the state mask; ALL
    motion is emitted. on_died fires at most once if a consumer callback
    raises (the service also self-detects death via is_running())."""

    def __init__(self, on_event, on_died=None, listener_factory=None):
        self._on_event = on_event
        self._on_died = on_died
        self._listener_factory = listener_factory or self._pynput_listener
        self._listener = None
        self._held: set[int] = set()
        self._lock = threading.Lock()
        self._running = False
        self._died = False

    @staticmethod
    def _pynput_listener(on_move, on_click):
        from pynput import mouse  # lazy: keeps the module importable everywhere
        return mouse.Listener(on_move=on_move, on_click=on_click)

    @staticmethod
    def _now_ms() -> int:
        return int(monotonic() * 1000)

    def start(self) -> bool:
        with self._lock:
            if self._running:
                return True
            try:
                listener = self._listener_factory(self._on_move, self._on_click)
                listener.start()
            except Exception:
                return False
            self._listener = listener
            self._running = True
            self._died = False
            self._held.clear()
        return True

    def stop(self) -> None:
        with self._lock:
            listener, self._listener = self._listener, None
            self._running = False
            self._held.clear()
        if listener is not None:
            try:
                listener.stop()
            except Exception:
                pass

    def is_running(self) -> bool:
        with self._lock:
            if not self._running or self._listener is None:
                return False
            listener = self._listener
        # Thread liveness, NOT pynput's `.running` flag: pynput sets
        # `running` True in run() and never clears it on hook-thread
        # death (the win32 pump swallows exceptions), so a dead hook
        # would report healthy forever; and `.running` is briefly False
        # right after start(), which the service would misread as an
        # instant-death start failure. is_alive() is correct on both
        # edges. Fakes without is_alive() fall back to `running`.
        is_alive = getattr(listener, "is_alive", None)
        if callable(is_alive):
            return bool(is_alive())
        return bool(getattr(listener, "running", True))

    # -- listener callbacks (pynput hook thread) -------------------------

    def _on_move(self, x, y):
        try:
            with self._lock:
                if not self._running:
                    return
                state = mask_for(self._held)
            self._on_event("motion", int(x), int(y), state, self._now_ms())
        except Exception:
            self._die()

    def _on_click(self, x, y, button, pressed):
        try:
            num = _PYNPUT_TO_X.get(getattr(button, "name", None))
            if num is None:
                return  # x1/x2 etc.: invisible to the service
            with self._lock:
                if not self._running:
                    return
                if pressed:
                    state = mask_for(self._held)  # press excludes itself
                    self._held.add(num)
                else:
                    self._held.add(num)           # defensive: unseen press
                    state = mask_for(self._held)  # release includes itself
                    self._held.discard(num)
            if num == 1:
                kind = "press" if pressed else "release"
                self._on_event(kind, int(x), int(y), state, self._now_ms())
        except Exception:
            self._die()

    def _die(self) -> None:
        with self._lock:
            if self._died:
                return
            self._died = True
            self._running = False
            listener, self._listener = self._listener, None
        if listener is not None:
            try:
                listener.stop()
            except Exception:
                pass
        if self._on_died is not None:
            try:
                self._on_died()
            except Exception:
                pass
