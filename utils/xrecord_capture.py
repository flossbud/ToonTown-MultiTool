"""Portal-safe global mouse observation via the X RECORD extension.

Two dedicated Display connections (control + data), one capture thread.
Records core device ButtonPress/ButtonRelease/MotionNotify ONLY; synthetic
XSendEvent traffic is not a device event so our own injected clicks never
appear here (the click-sync echo-loop guarantee). The send_event bit is
checked anyway as a defensive layer.

NEVER replace this with XTEST or pynput-with-XTEST: XTEST triggers the
Wayland RemoteDesktop portal this app deliberately avoids.
"""
from __future__ import annotations

import threading

from Xlib import X, display as xdisplay
from Xlib.ext import record
from Xlib.protocol import rq


class XRecordCapture:
    """on_event(kind, root_x, root_y, state, time) with kind in
    'press' | 'release' | 'motion' (button 1 / pointer only)."""

    def __init__(self, on_event, on_died=None):
        self._on_event = on_event
        self._on_died = on_died  # called once if the capture thread dies unexpectedly
        self._ctl = None
        self._data = None
        self._ctx = None
        self._thread = None
        self._stopping = False
        self._running = False

    def is_running(self) -> bool:
        return self._running

    def start(self) -> bool:
        if self._running:
            return True
        try:
            self._ctl = xdisplay.Display()
            self._data = xdisplay.Display()
            if not self._ctl.has_extension("RECORD"):
                self._cleanup()
                return False
            self._ctx = self._ctl.record_create_context(
                0, [record.AllClients], [{
                    "core_requests": (0, 0), "core_replies": (0, 0),
                    "ext_requests": (0, 0, 0, 0), "ext_replies": (0, 0, 0, 0),
                    "delivered_events": (0, 0),
                    # 4..6 = ButtonPress, ButtonRelease, MotionNotify
                    "device_events": (X.ButtonPress, X.MotionNotify),
                    "errors": (0, 0),
                    "client_started": False, "client_died": False,
                }])
            self._ctl.sync()
        except Exception as e:
            print(f"[XRecordCapture] start failed: {e}")
            self._cleanup()
            return False
        self._stopping = False
        self._thread = threading.Thread(
            target=self._run, name="click-sync-xrecord", daemon=True)
        self._thread.start()
        self._running = True
        return True

    def stop(self):
        """Idempotent. Disables the context from the control display (the
        data display is blocked inside record_enable_context), joins the
        thread, frees the context, closes both displays."""
        if not self._running and self._thread is None:
            return
        self._stopping = True
        try:
            if self._ctl is not None and self._ctx is not None:
                self._ctl.record_disable_context(self._ctx)
                self._ctl.flush()
        except Exception:
            pass
        if self._thread is not None:
            self._thread.join(timeout=3.0)
            if self._thread.is_alive():
                # Forced fallback: closing the data connection unblocks the
                # recv inside record_enable_context.
                try:
                    if self._data is not None:
                        self._data.close()
                except Exception:
                    pass
                self._thread.join(timeout=2.0)
            self._thread = None
        try:
            if self._ctl is not None and self._ctx is not None:
                self._ctl.record_free_context(self._ctx)
        except Exception:
            pass
        self._cleanup()
        self._running = False

    def _cleanup(self):
        for attr in ("_ctl", "_data"):
            d = getattr(self, attr)
            if d is not None:
                try:
                    d.close()
                except Exception:
                    pass
                setattr(self, attr, None)
        self._ctx = None

    def _run(self):
        died = False
        try:
            self._data.record_enable_context(self._ctx, self._reply_callback)
        except Exception as e:
            if not self._stopping:
                died = True
                print(f"[XRecordCapture] capture thread died: {e}")
        finally:
            self._running = False
            if died and self._on_died is not None:
                try:
                    self._on_died()
                except Exception:
                    pass

    def _reply_callback(self, reply):
        if self._stopping:
            return
        if reply.category != record.FromServer or reply.client_swapped:
            return
        if not reply.data or reply.data[0] < 2:
            return  # not a core event
        buf = reply.data
        while len(buf) >= 32:
            try:
                ev, buf = rq.EventField(None).parse_binary_value(
                    buf, self._data.display, None, None)
            except Exception:
                return
            self._dispatch(ev)

    def _dispatch(self, ev):
        if getattr(ev, "send_event", 0):
            return  # defensive: never act on synthetic events
        if ev.type == X.MotionNotify:
            self._on_event("motion", ev.root_x, ev.root_y, ev.state, ev.time)
        elif ev.type == X.ButtonPress and ev.detail == 1:
            self._on_event("press", ev.root_x, ev.root_y, ev.state, ev.time)
        elif ev.type == X.ButtonRelease and ev.detail == 1:
            self._on_event("release", ev.root_x, ev.root_y, ev.state, ev.time)
