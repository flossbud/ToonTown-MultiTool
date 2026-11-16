"""Build click sync (mouse mirroring) and its ghost cursors for this platform.

Click sync runs on Linux/X11, Windows and macOS. Anywhere else
``build_click_sync`` returns None and the feature is simply absent; no
platform backend is imported (python-xlib does not exist on macOS, pywin32
does not exist on Linux), so each one is imported inside its own branch.

The service addresses toons by slot (the position of the window in
``WindowManager.get_window_ids()``); ``click_sync_slot_window`` is the one
rule for which window, if any, a slot stands for.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

from utils.settings_keys import CLICK_SYNC_ENABLED

CLICK_SYNC_GAME = "ttr"


def click_sync_supports_game(game: str | None) -> bool:
    """Click sync mirrors into Toontown Rewritten windows only."""
    return game == CLICK_SYNC_GAME


def click_sync_slot_window(window_manager, slot: int):
    """The window id slot ``slot`` stands for, or None when the slot is empty
    or holds a window click sync cannot drive."""
    ids = window_manager.get_window_ids()
    if 0 <= slot < len(ids) and click_sync_supports_game(
            window_manager.window_games.get(ids[slot])):
        return ids[slot]
    return None


@dataclass
class ClickSyncWiring:
    service: object
    backend: object
    ghost_cursor_controller: object

    def shutdown(self) -> None:
        if self.service is not None:
            self.service.shutdown()
        if self.backend is not None:
            self.backend.disconnect()


def build_click_sync(window_manager, settings_manager, parent) -> ClickSyncWiring | None:
    """Construct the service, its injection backend and the ghost cursors.

    ``parent`` owns the service and the controller as Qt children: the
    resolver closures below keep the window manager and each other alive in
    a cycle, and Qt parenting destroys the C++ objects with their owner
    instead of leaving the order to Python's collector at interpreter exit.

    The caller connects ``service.slot_states_changed`` /
    ``service.service_error``, feeds ``service.recompute`` on window-list and
    geometry changes, and applies the master switch.
    """
    if sys.platform not in ("win32", "linux", "darwin"):
        return None

    from services.click_sync_service import ClickSyncService

    wiring = ClickSyncWiring(service=None, backend=None, ghost_cursor_controller=None)

    def _slot_wid(slot, _wm=window_manager):
        return click_sync_slot_window(_wm, slot)

    def _capture_died(holder):
        # The capture closes over its own instance so the service can
        # identity-check stale generations.
        return lambda: wiring.service.notify_capture_died(holder[0])

    delivery_ready = None   # darwin sets this to backend.mouse_delivery_ready

    if sys.platform == "win32":
        from utils import win32_discovery as _disc
        from utils.win32_backend import Win32Backend
        from utils.win32_mouse_capture import Win32MouseCapture

        # Capture events arrive INSIDE the WH_MOUSE_LL hook callback, so time
        # spent handling them (including waiting on the service lock) delays
        # ALL system mouse input, and a callback exceeding the OS hook timeout
        # (~300ms) gets the hook silently removed. Work under the service lock
        # must stay trivially fast.

        def _source_resolver(root_x, root_y, member_wids):
            # Tri-state hit test (wid | "" | None). Member wids ARE toplevel
            # hwnds, so a direct comparison replaces the X11 ancestor walk.
            # Ghost overlays need no guard: WindowFromPoint skips
            # WS_EX_TRANSPARENT layered windows.
            frame = _disc.toplevel_at_point(root_x, root_y)
            if frame:
                return frame if frame in member_wids else None
            if frame == "":
                # Clean miss; kept for tri-state parity with X11.
                return None
            for wid in member_wids:
                g = window_manager.get_window_geometry(wid)
                if (g and g[0] <= root_x < g[0] + g[2]
                        and g[1] <= root_y < g[1] + g[3]):
                    return wid
            return None

        def _capture_factory(on_event):
            holder = []
            cap = Win32MouseCapture(on_event, on_died=_capture_died(holder))
            holder.append(cap)
            return cap

        # PostMessage is connection-less: a dedicated instance is free.
        wiring.backend = Win32Backend()
        fresh_geometry = _disc.get_window_geometry
    elif sys.platform == "linux":
        from utils import x11_discovery as _x11d

        def _source_resolver(root_x, root_y, member_wids):
            # Stacking-aware: the frame under the point must be a member's
            # toplevel ancestor. Tri-state: wid = a toplevel contains the
            # point; "" = clean miss (bare root); None = lookup FAILURE.
            frame = _x11d.toplevel_at_point(root_x, root_y)
            gc = wiring.ghost_cursor_controller
            if frame and gc is not None and frame in gc.overlay_wids():
                # One of our own ghost overlays under the point. It only ever
                # sits on top of a member window, so resolve through the
                # rect-containment fallback, never as a foreign toplevel.
                frame = None
            lookup_failed = frame is None
            if frame:
                for wid in member_wids:
                    anc = _x11d.toplevel_ancestor(wid)
                    if anc is None:
                        # Transient X error on this member's ancestor walk;
                        # the fallback below covers for it.
                        lookup_failed = True
                    elif anc == frame:
                        return wid
                if not lookup_failed:
                    # Cleanly resolved to a non-member toplevel (a foreign
                    # window overlapping a game window): ignore the gesture,
                    # never rect-match the member underneath.
                    return None
            elif frame == "":
                # Clean miss over the bare root: ignore, never rect-match.
                return None
            # Rect containment only for stacking-resolution FAILURES.
            for wid in member_wids:
                g = window_manager.get_window_geometry(wid)
                if g and g[0] <= root_x < g[0] + g[2] and g[1] <= root_y < g[1] + g[3]:
                    return wid
            return None

        def _capture_factory(on_event):
            from utils.xrecord_capture import XRecordCapture
            holder = []
            cap = XRecordCapture(on_event, on_died=_capture_died(holder))
            holder.append(cap)
            return cap

        # Dedicated injection connection. Never share the InputService
        # Display: that one belongs to its worker thread, and click sync
        # injects from the XRecord capture thread and the hover-flush timers.
        # Its own calls are serialized under the service lock, so one
        # dedicated Display is safe.
        from utils.xlib_backend import XlibBackend
        wiring.backend = XlibBackend()
        fresh_geometry = _x11d.get_window_geometry
    else:  # darwin
        from utils import macos_discovery as _macd
        from utils.macos_backend import MacOSBackend
        from utils.macos_mouse_capture import MacOSMouseCapture
        from utils.macos_mouse_delivery import EchoLedger

        # ONE shared ledger: the delivery engine records every posted event
        # into it and the capture's echo guard matches against it.
        echo_ledger = EchoLedger()

        def _source_resolver(root_x, root_y, member_wids):
            # The frontmost game window must be a member AND contain the
            # point. The key-flip never changes system-front, so the active
            # window is a reliable source.
            return _macd.active_source_window(root_x, root_y, member_wids)

        def _capture_factory(on_event):
            holder = []
            cap = MacOSMouseCapture(on_event, ledger=echo_ledger,
                                    on_died=_capture_died(holder))
            holder.append(cap)
            return cap

        wiring.backend = MacOSBackend()
        wiring.backend.set_echo_ledger(echo_ledger)   # same instance into both
        fresh_geometry = _macd.get_window_geometry_fresh
        delivery_ready = wiring.backend.mouse_delivery_ready

    try:
        wiring.backend.connect()   # no-op on Windows
    except Exception as e:  # noqa: BLE001
        print(f"[ClickSync] backend connect failed: {e}")

    # A real WindowManager provides get_window_geometry; a duck-typed one
    # without it degrades to "no geometry" (slots resolve unusable, capture
    # never starts).
    geometry = getattr(window_manager, "get_window_geometry", None)
    if geometry is None:
        print("[ClickSync] window manager lacks get_window_geometry; "
              "geometry lookups disabled")
        geometry = lambda _wid: None  # noqa: E731

    wiring.service = ClickSyncService(
        slot_window_resolver=_slot_wid,
        geometry_provider=geometry,
        source_resolver=_source_resolver,
        backend=wiring.backend,
        capture_factory=_capture_factory,
        parent=parent,
        # Gesture snapshots need LIVE geometry: the cache can be ~2s stale
        # after a window move, which would mismap the injection.
        fresh_geometry_provider=fresh_geometry,
        delivery_ready=delivery_ready,
    )
    if settings_manager is not None:
        wiring.service.set_enabled(
            bool(settings_manager.get(CLICK_SYNC_ENABLED, False)))

    from utils.ghost_cursors import GhostCursorController

    def _slot_rect(slot):
        # NATIVE game-window rect for the slot; the confined ghost renderer
        # clips the glove to it (cache-backed, GUI-thread safe).
        wid = _slot_wid(slot)
        return geometry(wid) if wid else None

    wiring.ghost_cursor_controller = GhostCursorController(
        wiring.service, settings_manager, parent=parent,
        slot_window_resolver=_slot_wid,
        slot_rect_resolver=_slot_rect)
    return wiring
