"""Notices a click outside the open popovers, and Escape, without focus.

A popover never takes focus or grabs the pointer (the game must keep both),
so it cannot be told about a click somewhere else. While something is open
this polls the pointer buttons about sixty times a second and reports a
button going down outside every rectangle the owner calls "inside".

Escape: on X11 the key is grabbed passively for as long as something is
open, so the press closes the popover and does not reach the game. Elsewhere
its state is polled, and the game sees the key as well.
"""
from __future__ import annotations

import sys

from PySide6.QtCore import QObject, QPoint, QTimer, Signal
from PySide6.QtGui import QCursor, QGuiApplication

POLL_MS = 16


def _platform_name() -> str:
    app = QGuiApplication.instance()
    return (app.platformName() if app is not None else "").lower()


class _X11Probe:
    """Pointer buttons and a passive Escape grab on a connection of its own."""

    def __init__(self) -> None:
        from Xlib import X, XK, display
        self.X = X
        self.d = display.Display()
        self.root = self.d.screen().root
        self.escape = self.d.keysym_to_keycode(XK.XK_Escape)
        self._grabbed = False
        self._button_mask = (X.Button1Mask | X.Button2Mask | X.Button3Mask)
        # NumLock, CapsLock and ScrollLock must not defeat the grab.
        self._locks = [0, X.LockMask, X.Mod2Mask, X.Mod5Mask,
                       X.LockMask | X.Mod2Mask, X.LockMask | X.Mod5Mask,
                       X.Mod2Mask | X.Mod5Mask,
                       X.LockMask | X.Mod2Mask | X.Mod5Mask]
        self.d.set_error_handler(lambda *_: None)

    def buttons_down(self) -> bool:
        return bool(self.root.query_pointer().mask & self._button_mask)

    def grab_escape(self, on: bool) -> None:
        if on == self._grabbed or not self.escape:
            return
        self._grabbed = on
        for mods in self._locks:
            if on:
                self.root.grab_key(self.escape, mods, False,
                                   self.X.GrabModeAsync, self.X.GrabModeAsync)
            else:
                self.root.ungrab_key(self.escape, mods)
        self.d.sync()

    def escape_pressed(self) -> bool:
        """True once per Escape press delivered by the grab."""
        hit = False
        while self.d.pending_events():
            ev = self.d.next_event()
            if ev.type == self.X.KeyPress and ev.detail == self.escape:
                hit = True
        return hit

    def close(self) -> None:
        try:
            self.grab_escape(False)
        except Exception:
            pass
        finally:
            try:
                self.d.close()
            except Exception:
                pass


class _PollProbe:
    """Windows and macOS: read button and Escape state; nothing is grabbed."""

    def __init__(self) -> None:
        self._escape_was_down = False

    def buttons_down(self) -> bool:
        if sys.platform == "win32":
            import ctypes
            get = ctypes.windll.user32.GetAsyncKeyState
            return any(get(vk) & 0x8000 for vk in (0x01, 0x02, 0x04))
        if sys.platform == "darwin":
            import Quartz
            return any(Quartz.CGEventSourceButtonState(
                Quartz.kCGEventSourceStateCombinedSessionState, b) for b in (0, 1, 2))
        return bool(QGuiApplication.mouseButtons())

    def grab_escape(self, on: bool) -> None:
        # Start from the key's state NOW: an Escape already held when a
        # popover opens is not a press meant for it.
        try:
            self._escape_was_down = self._escape_down() if on else False
        except Exception:
            self._escape_was_down = False

    def _escape_down(self) -> bool:
        if sys.platform == "win32":
            import ctypes
            return bool(ctypes.windll.user32.GetAsyncKeyState(0x1B) & 0x8000)
        if sys.platform == "darwin":
            import Quartz
            return bool(Quartz.CGEventSourceKeyState(
                Quartz.kCGEventSourceStateCombinedSessionState, 53))
        return False

    def escape_pressed(self) -> bool:
        down = self._escape_down()
        edge = down and not self._escape_was_down
        self._escape_was_down = down
        return edge

    def close(self) -> None:
        pass


def _make_probe():
    if _platform_name() == "xcb":
        try:
            return _X11Probe()
        except Exception:
            pass
    return _PollProbe()


class PointerWatch(QObject):
    pressed_outside = Signal()
    escape = Signal()

    def __init__(self, probe=None, cursor_fn=None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._probe = probe
        self._cursor_fn = cursor_fn or QCursor.pos
        self._inside_fn = None
        self._was_down = False
        self._paused = False
        self._timer = QTimer(self)
        self._timer.setInterval(POLL_MS)
        self._timer.timeout.connect(self.tick)

    def is_watching(self) -> bool:
        return self._timer.isActive()

    def watch(self, inside_fn) -> None:
        """Start (or keep) watching. `inside_fn(QPoint) -> bool` says whether
        a global point belongs to something open or to its anchor."""
        self._inside_fn = inside_fn
        if self._probe is None:
            self._probe = _make_probe()
        if not self._timer.isActive():
            # A button already held (the click that opened the popover) must
            # not count as a press outside.
            try:
                self._was_down = self._probe.buttons_down()
            except Exception:
                self._was_down = False
            self._set_escape(True)
            self._timer.start()

    def stop(self) -> None:
        self._timer.stop()
        self._inside_fn = None
        if self._probe is not None:
            self._set_escape(False)

    def pause_escape(self, paused: bool) -> None:
        """A key capture owns the keyboard: Escape is its to handle."""
        self._paused = bool(paused)
        if self._timer.isActive():
            self._set_escape(not paused)

    def _set_escape(self, on: bool) -> None:
        try:
            self._probe.grab_escape(on and not self._paused)
        except Exception:
            pass

    def tick(self) -> None:
        probe = self._probe
        if probe is None or self._inside_fn is None:
            return
        try:
            down = probe.buttons_down()
            escaped = (not self._paused) and probe.escape_pressed()
        except Exception:
            # A dead connection cannot dismiss anything. Release it and
            # close the popovers; their next open creates a fresh probe.
            self.shutdown()
            self.escape.emit()
            return
        pressed = down and not self._was_down
        self._was_down = down
        if escaped:
            self.escape.emit()
            return
        if pressed:
            try:
                inside = bool(self._inside_fn(QPoint(self._cursor_fn())))
            except Exception:
                inside = True
            if not inside:
                self.pressed_outside.emit()

    def shutdown(self) -> None:
        self.stop()
        if self._probe is not None:
            try:
                self._probe.close()
            except Exception:
                pass
            self._probe = None
