"""Ghost-cursor occlusion gate, region model (offscreen, probes injected).

On win32 AND darwin the gloves are unconfined always-on-top floats; the gate
clips each glove to its game window's VISIBLE surface - (glove ∩ game rect)
minus every foreign window above the game in z-order - applied as a window
mask so the sprite slides UNDER an occluder's edge pixel by pixel (the X11
confined look). A fully carved glove hides (explicit-hide rule: an EMPTY
setMask is a no-op on cocoa, CP8); the periodic sweep restores it when the
occluder moves away. The z-order probe is an instance attribute, faked here.
"""
import pytest
from PySide6.QtCore import QRect
from PySide6.QtGui import QRegion
from PySide6.QtWidgets import QApplication

from tabs.multitoon._ghost_cursors import (
    CURSOR_SIZE,
    HOTSPOT,
    GhostCursorController,
    _visible_glove_region,
)

GAME = 111
OTHER_GAME = 222
FOREIGN = 333
APP_WIN = 444
OWN_PID = 4242
IDENT = lambda x, y: (x, y)  # noqa: E731  logical == raw in these tests


# ---------------------------------------------------------------------------
# _visible_glove_region (pure)
# ---------------------------------------------------------------------------

def _glove(x=100, y=100):
    return QRect(x, y, CURSOR_SIZE, CURSOR_SIZE)


def test_region_full_over_uncovered_game():
    snap = [(GAME, (0, 0, 800, 600), 777)]
    r = _visible_glove_region(_glove(), GAME, snap, OWN_PID, IDENT)
    assert r == QRegion(QRect(0, 0, CURSOR_SIZE, CURSOR_SIZE))


def test_region_carved_by_overlapping_occluder():
    # Explorer covers the RIGHT half of the glove (x >= 116 in globals).
    snap = [(FOREIGN, (116, 0, 900, 600), 555),
            (GAME, (0, 0, 800, 600), 777)]
    r = _visible_glove_region(_glove(), GAME, snap, OWN_PID, IDENT)
    assert r == QRegion(QRect(0, 0, 16, CURSOR_SIZE))   # left half remains


def test_region_empty_when_fully_covered():
    snap = [(FOREIGN, (0, 0, 900, 600), 555),
            (GAME, (0, 0, 800, 600), 777)]
    r = _visible_glove_region(_glove(), GAME, snap, OWN_PID, IDENT)
    assert r.isEmpty()


def test_region_ignores_windows_below_the_game():
    snap = [(GAME, (0, 0, 800, 600), 777),
            (FOREIGN, (0, 0, 900, 600), 555)]   # below the game in z
    r = _visible_glove_region(_glove(), GAME, snap, OWN_PID, IDENT)
    assert r == QRegion(QRect(0, 0, CURSOR_SIZE, CURSOR_SIZE))


def test_region_ignores_own_process_windows():
    snap = [(APP_WIN, (0, 0, 900, 600), OWN_PID),  # the float cluster
            (GAME, (0, 0, 800, 600), 777)]
    r = _visible_glove_region(_glove(), GAME, snap, OWN_PID, IDENT)
    assert r == QRegion(QRect(0, 0, CURSOR_SIZE, CURSOR_SIZE))


def test_region_clips_to_game_edge():
    # Game ends at x=116: the glove pokes past its right edge.
    snap = [(GAME, (0, 0, 116, 600), 777)]
    r = _visible_glove_region(_glove(), GAME, snap, OWN_PID, IDENT)
    assert r == QRegion(QRect(0, 0, 16, CURSOR_SIZE))


def test_region_empty_when_game_absent():
    snap = [(FOREIGN, (0, 0, 900, 600), 555)]
    r = _visible_glove_region(_glove(), GAME, snap, OWN_PID, IDENT)
    assert r.isEmpty()


def test_region_fails_open_without_snapshot():
    assert _visible_glove_region(_glove(), GAME, None, OWN_PID, IDENT) is None


# ---------------------------------------------------------------------------
# Controller integration (fed via _on_pointer_event, probe injected)
# ---------------------------------------------------------------------------

@pytest.fixture
def gated(qapp):
    ctrl = GhostCursorController(
        service=None,
        settings_manager=None,
        slot_window_resolver=lambda slot: str(GAME) if slot == 0
        else str(OTHER_GAME),
    )
    assert ctrl._disabled_reason is None, ctrl._disabled_reason
    ctrl._occlusion_gated = True
    ctrl._own_pid = OWN_PID
    ctrl._to_logical = IDENT
    state = {"snap": [(GAME, (0, 0, 1600, 1200), 777)]}
    ctrl._zorder_probe = lambda: state["snap"]
    yield ctrl, state
    ctrl._hide_all()


def _press(ctrl, slot=0, x=100, y=100):
    ctrl._on_pointer_event(("press", [(slot, x, y)]))
    QApplication.processEvents()


def test_glove_shows_unmasked_over_open_game(gated):
    ctrl, state = gated
    _press(ctrl)
    ov = ctrl._overlays[0]
    assert ov.isVisible() is True
    assert ov._occ_region is None          # full region -> mask cleared


def test_glove_masked_at_occluder_edge(gated):
    ctrl, state = gated
    gx, gy = 100 - HOTSPOT[0], 100 - HOTSPOT[1]
    state["snap"] = [(FOREIGN, (gx + 16, 0, 900, 600), 555),
                     (GAME, (0, 0, 1600, 1200), 777)]
    _press(ctrl)
    ov = ctrl._overlays[0]
    assert ov.isVisible() is True
    assert ov._occ_region == QRegion(QRect(0, 0, 16, CURSOR_SIZE))


def test_glove_hidden_when_fully_covered(gated):
    ctrl, state = gated
    state["snap"] = [(FOREIGN, (0, 0, 1600, 1200), 555),
                     (GAME, (0, 0, 1600, 1200), 777)]
    _press(ctrl)
    assert 0 in ctrl._occlusion_hidden
    ov = ctrl._overlays.get(0)
    assert ov is None or ov.isVisible() is False


def test_probe_failure_fails_open(gated):
    ctrl, state = gated
    ctrl._zorder_probe = lambda: None
    _press(ctrl)
    ov = ctrl._overlays[0]
    assert ov.isVisible() is True
    assert ov._occ_region is None


def test_sweep_carves_when_occluder_arrives(gated):
    ctrl, state = gated
    _press(ctrl)
    ov = ctrl._overlays[0]
    assert ov._occ_region is None
    gx = 100 - HOTSPOT[0]
    state["snap"] = [(FOREIGN, (gx + 16, 0, 900, 600), 555),
                     (GAME, (0, 0, 1600, 1200), 777)]
    ctrl._occlusion_sweep()
    assert ov.isVisible() is True
    assert ov._occ_region == QRegion(QRect(0, 0, 16, CURSOR_SIZE))


def test_sweep_hides_then_reshows_across_full_cover(gated):
    ctrl, state = gated
    _press(ctrl)
    ov = ctrl._overlays[0]
    state["snap"] = [(FOREIGN, (0, 0, 1600, 1200), 555),
                     (GAME, (0, 0, 1600, 1200), 777)]
    ctrl._occlusion_sweep()
    assert ov.isVisible() is False
    assert 0 in ctrl._occlusion_hidden
    state["snap"] = [(GAME, (0, 0, 1600, 1200), 777)]
    ctrl._occlusion_sweep()
    assert ov.isVisible() is True
    assert 0 not in ctrl._occlusion_hidden


def test_sweep_respects_focus_suppression(gated):
    ctrl, state = gated
    state["snap"] = [(FOREIGN, (0, 0, 1600, 1200), 555),
                     (GAME, (0, 0, 1600, 1200), 777)]
    _press(ctrl)
    ctrl.set_focused_window(str(GAME))
    state["snap"] = [(GAME, (0, 0, 1600, 1200), 777)]
    ctrl._occlusion_sweep()
    ov = ctrl._overlays.get(0)
    assert ov is None or ov.isVisible() is False


def test_hide_all_clears_gate_state(gated):
    ctrl, state = gated
    _press(ctrl)
    ctrl._hide_all()
    assert ctrl._occlusion_hidden == set()
    assert ctrl._last_logical == {}
    timer = ctrl._occlusion_timer
    assert timer is None or timer.isActive() is False


def test_gate_off_keeps_legacy_behavior(qapp, monkeypatch):
    # The kill switch disarms the gate on every platform (win32/darwin arm
    # it by default when unconfined).
    monkeypatch.setenv("TTMT_GHOST_UNCONFINED", "1")
    ctrl = GhostCursorController(service=None, settings_manager=None)
    assert ctrl._occlusion_gated is False
    ctrl._zorder_probe = lambda: [(FOREIGN, (0, 0, 1600, 1200), 555)]
    _press(ctrl)
    assert ctrl._overlays[0].isVisible() is True


# ---------------------------------------------------------------------------
# darwin arming + CGWindowList snapshot parsing
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_darwin_snap_cache():
    """The darwin snapshot is TTL-cached (a CGWindowList probe per pointer
    event per glove saturated the GUI thread live); keep the cache from
    leaking between tests."""
    from tabs.multitoon import _ghost_cursors as gc
    gc._reset_darwin_snapshot_cache()
    yield
    gc._reset_darwin_snapshot_cache()


def test_gate_armed_on_darwin_unconfined(qapp, monkeypatch):
    import sys as _sys
    from tabs.multitoon import _ghost_cursors as gc
    monkeypatch.setattr(_sys, "platform", "darwin")
    ctrl = GhostCursorController(service=None, settings_manager=None)
    assert ctrl._occlusion_gated is True
    assert ctrl._zorder_probe is gc._darwin_zorder_snapshot
    ctrl._hide_all()


def test_gate_armed_on_win32_unconfined_unchanged(qapp, monkeypatch):
    import sys as _sys
    from tabs.multitoon import _ghost_cursors as gc
    monkeypatch.setattr(_sys, "platform", "win32")
    ctrl = GhostCursorController(service=None, settings_manager=None)
    assert ctrl._occlusion_gated is True
    assert ctrl._zorder_probe is gc._win32_zorder_snapshot
    ctrl._hide_all()


def test_darwin_refresh_parses_bounds_pid_number_only(monkeypatch):
    """Front-to-back order preserved; bounds dict -> (l, t, r, b);
    degenerate/malformed records dropped. Only kCGWindowNumber /
    kCGWindowOwnerPID / kCGWindowBounds are consulted (kCGWindowName can
    demand the Screen Recording TCC prompt - the fakes simply omit it)."""
    from tabs.multitoon import _ghost_cursors as gc
    from utils import macos_discovery as md

    def _info(num, pid, x, y, w, h):
        return {"kCGWindowNumber": num, "kCGWindowOwnerPID": pid,
                "kCGWindowBounds": {"X": x, "Y": y, "Width": w, "Height": h}}

    infos = [
        _info(FOREIGN, 555, 10, 20, 100, 50),
        _info(GAME, 777, 0, 30, 800, 600),
        {"kCGWindowNumber": 999},                 # no pid/bounds: dropped
        _info(1010, 888, 5, 5, 0, 40),            # zero width: dropped
    ]
    monkeypatch.setattr(md, "_raw_window_info", lambda: infos)
    snap = gc._refresh_darwin_snapshot()
    assert snap == [
        (FOREIGN, (10, 20, 110, 70), 555),
        (GAME, (0, 30, 800, 630), 777),
    ]
    # The frame-path read serves the freshly stored snapshot.
    assert gc._darwin_zorder_snapshot() is snap


def test_darwin_refresh_error_keeps_previous_snapshot(monkeypatch):
    """A transient window-server error must not blank the mask basis: the
    previous snapshot stays in place (stale beats blank; the next sweep or
    TTL expiry retries)."""
    from tabs.multitoon import _ghost_cursors as gc
    from utils import macos_discovery as md
    monkeypatch.setattr(md, "_raw_window_info", lambda: [])
    good = gc._refresh_darwin_snapshot()
    assert good == []

    def _boom():
        raise RuntimeError("window server gone")

    monkeypatch.setattr(md, "_raw_window_info", _boom)
    assert gc._refresh_darwin_snapshot() is good
    assert gc._darwin_snap_cache["snap"] is good


def test_darwin_read_never_probes_fresh_cache(monkeypatch):
    """CP15/CP16 law: the frame path never talks to the window server.
    A FRESH cache is served without any refresh kick."""
    from tabs.multitoon import _ghost_cursors as gc
    from utils import macos_discovery as md
    monkeypatch.setattr(md, "_raw_window_info", lambda: [])
    snap = gc._refresh_darwin_snapshot()
    kicks = []
    monkeypatch.setattr(gc, "_kick_darwin_snapshot_refresh",
                        lambda: kicks.append(1))
    assert gc._darwin_zorder_snapshot() is snap
    assert kicks == []


def test_darwin_read_serves_stale_and_kicks_refresh(monkeypatch):
    """Expired cache: the read returns the STALE snapshot immediately (never
    blocks) and kicks exactly one background refresh."""
    from tabs.multitoon import _ghost_cursors as gc
    from utils import macos_discovery as md
    monkeypatch.setattr(md, "_raw_window_info", lambda: [])
    stale = gc._refresh_darwin_snapshot()
    gc._darwin_snap_cache["t"] -= gc._DARWIN_SNAP_TTL_S * 2  # age it
    kicks = []
    monkeypatch.setattr(gc, "_kick_darwin_snapshot_refresh",
                        lambda: kicks.append(1))
    assert gc._darwin_zorder_snapshot() is stale
    assert kicks == [1]


def test_darwin_read_before_first_refresh_fails_open(monkeypatch):
    """Empty cache (startup): None = fail open (gloves render unmasked for
    the first frames), refresh kicked."""
    from tabs.multitoon import _ghost_cursors as gc
    kicks = []
    monkeypatch.setattr(gc, "_kick_darwin_snapshot_refresh",
                        lambda: kicks.append(1))
    assert gc._darwin_zorder_snapshot() is None
    assert kicks == [1]


def test_darwin_kick_spawns_single_refresh(monkeypatch):
    """The refreshing flag admits ONE in-flight refresh; the thread updates
    the cache and clears the flag (real-thread integration, bounded wait)."""
    import time as _time
    from tabs.multitoon import _ghost_cursors as gc
    from utils import macos_discovery as md
    monkeypatch.setattr(md, "_raw_window_info", lambda: [])
    gc._kick_darwin_snapshot_refresh()
    deadline = _time.monotonic() + 2.0
    while gc._darwin_snap_cache["t"] < 0 and _time.monotonic() < deadline:
        _time.sleep(0.005)
    assert gc._darwin_snap_cache["snap"] == []
    assert gc._darwin_snap_refreshing is False


def test_darwin_kick_noop_while_refresh_in_flight(monkeypatch):
    from tabs.multitoon import _ghost_cursors as gc
    import threading as _threading
    spawned = []
    monkeypatch.setattr(
        _threading, "Thread",
        lambda *a, **k: spawned.append(1) or type(
            "T", (), {"start": lambda self: None})())
    with gc._darwin_snap_lock:
        gc._darwin_snap_refreshing = True
    gc._kick_darwin_snapshot_refresh()
    assert spawned == []


def test_set_visible_region_empty_hides_never_empty_masks(qapp):
    """CP8 landmine defense: setMask(QRegion()) is a NO-OP on cocoa (fully
    visible). A fully-carved region must HIDE the glove, never be handed to
    setMask - enforced inside set_visible_region so no call site can trip
    the trap."""
    from PySide6.QtGui import QPixmap
    from tabs.multitoon._ghost_cursors import GhostCursorOverlay
    ov = GhostCursorOverlay(QPixmap(32, 32))
    ov.show()
    ov.set_visible_region(QRegion())
    assert ov.isVisible() is False
    assert ov._occ_region is None
    ov.hide_now()


@pytest.fixture(autouse=True)
def _sync_ghost_frames():
    """Ghost rendering is frame-paced (the live smoothness fix): pointer
    events SAMPLE the newest point per slot and the frame driver renders at
    frame cadence. This suite asserts synchronously after each emit, so
    flush the sampled points right after every pointer event; the paced
    path itself is pinned by tests/test_ghost_frame_pacing.py."""
    from tabs.multitoon._ghost_cursors import GhostCursorController
    orig = GhostCursorController._on_pointer_event

    def synced(self, payload):
        orig(self, payload)
        self._frame_tick()

    GhostCursorController._on_pointer_event = synced
    yield
    GhostCursorController._on_pointer_event = orig
