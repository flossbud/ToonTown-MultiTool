"""How a strip stays with its game window, one strategy per platform.

A strip must sit directly above its own game window and nowhere else: under
any window raised over the game, gone when the game is minimized. Each
platform gets there differently, so the surface and the follower talk to one
small interface and never to a platform API:

  x11-transient      X11 and XWayland. The strip is a managed window made
                     transient for the game window and restacked right above
                     it. The window manager then keeps it there: covered when
                     the game is covered, minimized with it. Nothing computed.
  win32-topmost-gate Windows. A topmost tool window, masked every 100 ms to
                     the part of the game window no foreign window covers.
  cocoa-panel-gate   macOS. A non-activating panel at a floating level with
                     the same mask, from the cached window-list snapshot.
  floating           Anything else (and offscreen tests): plain keep-above.

A compositor that needs its own mechanism gets a new strategy here and an
entry in pick_attach_strategy(); nothing else changes.
"""
from __future__ import annotations

import os
import sys

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QGuiApplication, QRegion

from utils import screen_coords, x11_transient

_BASE_FLAGS = Qt.FramelessWindowHint | Qt.WindowDoesNotAcceptFocus


class AttachStrategy:
    name = "floating"
    # True when visibility over other windows has to be computed (and
    # re-computed on a timer) instead of being the window manager's job.
    gated = False
    # True when window rectangles from the tracker and input regions are in
    # Qt logical units already (cocoa); otherwise they are physical pixels.
    logical_native = False

    def window_flags(self):
        return Qt.Window | _BASE_FLAGS | Qt.WindowStaysOnTopHint

    def prepare(self, surface, backend) -> None:
        """Native handle exists, window not mapped yet."""

    def attach(self, surface, backend, game_wid: str) -> bool:
        """Tie a MAPPED surface to its game window. Called after every map
        and whenever the target changes. False when the tie did not take."""
        return True

    def visible_region(self, strip_rect: QRect, game_wid: str,
                       own_window_ids) -> QRegion | None:
        """Gated strategies: the part of `strip_rect` (logical, global) that
        may show, in strip-local coordinates. None means "no information,
        show everything"; an empty region means fully covered."""
        return None

    def to_logical(self, x: float, y: float) -> tuple[int, int]:
        """A native screen point in Qt logical coordinates."""
        if self.logical_native:
            return int(x), int(y)
        return screen_coords.native_to_logical(x, y)

    def region_ratio(self, surface) -> float:
        """Device pixels per logical pixel for input regions."""
        if self.logical_native:
            return 1.0
        try:
            return float(surface.devicePixelRatioF()) or 1.0
        except Exception:
            return 1.0


class X11TransientAttach(AttachStrategy):
    """Managed, never keep-above, never a DOCK: the strip takes its place in
    the stack from WM_TRANSIENT_FOR, so it can never float over a window
    that covers its game."""

    name = "x11-transient"

    def window_flags(self):
        return Qt.Window | _BASE_FLAGS

    def prepare(self, surface, backend) -> None:
        x11_transient.premap_skip_lists(int(surface.winId()))

    def attach(self, surface, backend, game_wid: str) -> bool:
        # Qt deletes WM_TRANSIENT_FOR on every show(), and a fresh map lands
        # on top of the whole stack: assert the property and restack, every
        # time the surface is mapped.
        try:
            return x11_transient.confine(int(surface.winId()), int(game_wid))
        except (TypeError, ValueError):
            return False


def _own_ids(own_window_ids) -> set[int]:
    out = set()
    for wid in own_window_ids or ():
        try:
            out.add(int(wid))
        except (TypeError, ValueError):
            pass
    return out


def _gate_region(strip_rect: QRect, game_wid: str, snapshot, own_window_ids,
                 to_logical) -> QRegion | None:
    """Shared occlusion maths: the strip, clipped to its game window and
    carved by every foreign window above the game. The strips' own surfaces
    never count as occluders; every other window does, this app's main
    window included."""
    if snapshot is None:
        return None
    try:
        target = int(game_wid)
    except (TypeError, ValueError):
        return None
    from utils.ghost_cursors import _region_from_inputs, _scan_region_inputs
    own = _own_ids(own_window_ids)
    foreign = [entry for entry in snapshot if entry[0] not in own]
    inputs = _scan_region_inputs(target, foreign, (), to_logical)
    return _region_from_inputs(strip_rect, inputs)


class Win32TopmostAttach(AttachStrategy):
    """Topmost WS_EX_NOACTIVATE tool window plus the occlusion gate. Windows
    has no "stay directly above that window" for a window of another
    process, so the strip is topmost and what must not show is masked off."""

    name = "win32-topmost-gate"
    gated = True

    def prepare(self, surface, backend) -> None:
        backend.set_initial_state(surface)     # NOACTIVATE + TOOLWINDOW

    def attach(self, surface, backend, game_wid: str) -> bool:
        backend.set_above(surface)
        backend.set_non_activating(surface)
        return True

    def visible_region(self, strip_rect, game_wid, own_window_ids):
        from utils.ghost_cursors import _win32_zorder_snapshot
        return _gate_region(strip_rect, game_wid, _win32_zorder_snapshot(),
                            own_window_ids, self.to_logical)


# NSWindowCollectionBehaviorFullScreenAuxiliary: lets the panel share a
# full-screen game's space instead of being left behind on the desktop.
_FULLSCREEN_AUXILIARY = 1 << 8


class CocoaPanelAttach(AttachStrategy):
    """Non-activating NSPanel at a floating level plus the occlusion gate.
    The window-list snapshot is the cached, refreshed-off-thread one: this
    never waits on the window server."""

    name = "cocoa-panel-gate"
    gated = True
    logical_native = True

    def window_flags(self):
        # Qt.Tool makes the native window an NSPanel, the only kind that
        # accepts the non-activating mask.
        return Qt.Tool | _BASE_FLAGS | Qt.WindowStaysOnTopHint

    def _fullscreen_auxiliary(self, surface, backend) -> None:
        try:
            win = backend._nswindow(surface)
            if win is not None:
                win.setCollectionBehavior_(
                    int(win.collectionBehavior()) | _FULLSCREEN_AUXILIARY)
        except Exception:
            pass

    def prepare(self, surface, backend) -> None:
        backend.set_initial_state(surface)     # level, spaces, non-activating
        self._fullscreen_auxiliary(surface, backend)

    def attach(self, surface, backend, game_wid: str) -> bool:
        backend.set_above(surface)
        backend.set_non_activating(surface)
        self._fullscreen_auxiliary(surface, backend)
        return True

    def visible_region(self, strip_rect, game_wid, own_window_ids):
        from utils.ghost_cursors import _darwin_zorder_snapshot
        # Strips are not layer-0 windows, so they are never in the snapshot.
        return _gate_region(strip_rect, game_wid, _darwin_zorder_snapshot(),
                            (), self.to_logical)


def pick_attach_strategy(platform_name: str | None = None) -> AttachStrategy:
    """The strategy for the running Qt platform. TTMT_STRIPS_ATTACH forces
    one by name (for diagnosis)."""
    forced = os.environ.get("TTMT_STRIPS_ATTACH", "").strip().lower()
    by_name = {cls.name: cls for cls in (AttachStrategy, X11TransientAttach,
                                         Win32TopmostAttach, CocoaPanelAttach)}
    if forced in by_name:
        return by_name[forced]()
    if platform_name is None:
        app = QGuiApplication.instance()
        platform_name = app.platformName() if app is not None else ""
    name = (platform_name or "").lower()
    if name == "xcb" and x11_transient.available():
        return X11TransientAttach()
    if name == "windows" and sys.platform == "win32":
        return Win32TopmostAttach()
    if name == "cocoa" and sys.platform == "darwin":
        return CocoaPanelAttach()
    return AttachStrategy()
