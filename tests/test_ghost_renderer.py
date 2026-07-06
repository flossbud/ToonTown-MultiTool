"""Ghost-renderer helper process (CP17): protocol, renderer core, client
write semantics, controller mode selection + fallback, and a real
subprocess round trip (offscreen).

The renderer exists because the app's single Qt loop + GIL floor in-process
glove cadence at ~50-60Hz under live load (measured, ledger CP17); its own
loop renders gloves at true frame cadence, fed from the capture thread.
"""
import os
import sys

import pytest
from PySide6.QtCore import QObject, Signal

from utils import ghost_feed_protocol as proto
from utils.ghost_renderer import GhostRendererCore
from utils.ghost_renderer_client import GhostRendererClient, _spawn_command

GAME = 111
FOREIGN = 333


# ── protocol codec ───────────────────────────────────────────────────────────

def test_protocol_roundtrips():
    assert proto.decode_line(proto.encode_position(2, 10, -5, "123")) == \
        ("position", 2, 10, -5, "123", None)
    assert proto.decode_line(proto.encode_position(0, 1, 2, None)) == \
        ("position", 0, 1, 2, None, None)
    assert proto.decode_line(proto.encode_position(1, 5, 6, "9", 12345)) == \
        ("position", 1, 5, 6, "9", 12345)
    assert proto.decode_line(proto.encode_focus("77")) == ("focus", "77")
    assert proto.decode_line(proto.encode_focus(None)) == ("focus", None)
    assert proto.decode_line(proto.encode_clear()) == ("clear",)
    assert proto.decode_line(proto.encode_quit()) == ("quit",)


def test_protocol_tolerates_garbage():
    for junk in ("", "\n", "X 1 2", "P 1 2", "P a b c d", "PP 1 2 3 4"):
        assert proto.decode_line(junk) is None


# ── renderer core (offscreen) ────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _stub_darwin_snapshot(monkeypatch):
    """De-flake: renderer-core tests that feed a REAL-looking wid (e.g.
    str(GAME)) hit the occlusion path, which - unless a test mocks it - reads
    the CI runner's LIVE window list. GAME is never a real window there, so the
    region computed empty or open depending on whatever happened to be on screen
    -> intermittent isVisible() failures on macOS CI (test_core_focus_* flaked
    for months). Default the darwin snapshot to None (occlusion open); the
    occlusion tests set their own snapshot in-body, which overrides this."""
    from tabs.multitoon import _ghost_cursors as gc
    monkeypatch.setattr(gc, "_darwin_zorder_snapshot", lambda: None)


@pytest.fixture
def core(qapp):
    c = GhostRendererCore()
    yield c
    c._hide_all()
    for ov in c._overlays.values():
        getattr(ov, "label", ov).deleteLater()
    for canvas in c._canvases:
        canvas.widget.deleteLater()


def _hotpos(core, slot):
    from tabs.multitoon._ghost_cursors import HOTSPOT
    ov = core._overlays[slot]
    return (ov.x() + HOTSPOT[0], ov.y() + HOTSPOT[1])


def test_core_renders_fed_position(core):
    core.feed_line(proto.encode_position(0, 100, 100, None))
    core.tick()
    assert core._overlays[0].isVisible()
    assert _hotpos(core, 0) == (100, 100)


def test_core_newest_position_wins(core):
    core.feed_line(proto.encode_position(0, 100, 100, None))
    core.feed_line(proto.encode_position(0, 300, 300, None))
    core.tick()
    assert _hotpos(core, 0) == (300, 300)
    # No new samples: the next tick renders nothing new (seq unchanged).
    core.tick()
    assert _hotpos(core, 0) == (300, 300)


def test_core_focus_suppresses_matching_wid(core):
    core.feed_line(proto.encode_focus(str(GAME)))
    core.tick()
    core.feed_line(proto.encode_position(0, 100, 100, str(GAME)))
    core.tick()
    ov = core._overlays.get(0)
    assert ov is None or not ov.isVisible()
    # A glove on a DIFFERENT window still renders.
    core.feed_line(proto.encode_position(1, 50, 50, "999"))
    core.tick()
    assert core._overlays[1].isVisible()


def test_core_focus_hides_glove_already_on_that_window(core):
    core.feed_line(proto.encode_position(0, 100, 100, str(GAME)))
    core.tick()
    assert core._overlays[0].isVisible()
    core.feed_line(proto.encode_focus(str(GAME)))
    core.tick()
    assert not core._overlays[0].isVisible()


def test_core_clear_hides_everything(core):
    core.feed_line(proto.encode_position(0, 100, 100, None))
    core.feed_line(proto.encode_position(1, 200, 200, None))
    core.tick()
    core.feed_line(proto.encode_clear())
    core.tick()
    assert all(not ov.isVisible() for ov in core._overlays.values())


def test_core_quit_message_and_eof_request_quit(core):
    core.feed_line(proto.encode_quit())
    core.tick()
    assert core._quit_requested
    c2 = GhostRendererCore()
    c2.feed_eof()
    c2.tick()
    assert c2._quit_requested


def test_core_occlusion_hides_fully_covered_glove(core, monkeypatch):
    from tabs.multitoon import _ghost_cursors as gc
    snap = [(FOREIGN, (0, 0, 1600, 1200), 555),
            (GAME, (0, 0, 1600, 1200), 777)]
    monkeypatch.setattr(gc, "_darwin_zorder_snapshot", lambda: snap)
    core.feed_line(proto.encode_position(0, 100, 100, str(GAME)))
    core.tick()
    ov = core._overlays.get(0)
    assert ov is None or not ov.isVisible()


def test_core_sweep_fades_idle_glove(core):
    core.feed_line(proto.encode_position(0, 100, 100, None))
    core.tick()
    faded = []
    core._overlays[0].fade_out = lambda: faded.append(1)
    core._last_sample_t[0] -= 10.0     # long idle
    core._sweep(__import__("time").monotonic())
    assert faded == [1]


# ── client write semantics (no subprocess: fds injected) ────────────────────

class _StubProc:
    def __init__(self):
        self.pid = 4242

    def poll(self):
        return None


def _piped_client():
    import fcntl
    r, w = os.pipe()
    fcntl.fcntl(w, fcntl.F_SETFL, fcntl.fcntl(w, fcntl.F_GETFL) | os.O_NONBLOCK)
    c = GhostRendererClient()
    c._proc = _StubProc()
    c._fd = w
    return c, r, w


def test_client_writes_positions_to_pipe():
    c, r, w = _piped_client()
    try:
        assert c.send_positions([(0, 10, 20, "123")]) is True
        assert os.read(r, 4096) == b"P 0 10 20 123\n"
    finally:
        os.close(r), os.close(w)


def test_client_drops_on_full_pipe_never_blocks():
    c, r, w = _piped_client()
    try:
        # Fill the pipe buffer completely.
        import errno
        try:
            while True:
                os.write(w, b"x" * 65536)
        except BlockingIOError:
            pass
        assert c.send_positions([(0, 10, 20, None)]) is True  # dropped, alive
        assert c.dropped == 1
        assert c._dead is False
    finally:
        os.close(r), os.close(w)


def test_client_broken_pipe_marks_dead():
    c, r, w = _piped_client()
    os.close(r)   # reader gone
    try:
        assert c.send_positions([(0, 10, 20, None)]) is False
        assert c._dead is True
        assert c.alive() is False
    finally:
        os.close(w)


def test_spawn_command_targets_main_with_flag():
    cmd = _spawn_command()
    assert cmd[0] == sys.executable
    assert cmd[-1] == "--ghost-renderer"
    assert cmd[-2].endswith("main.py")


# ── controller integration: mode selection + fallback ───────────────────────

class _FakeService(QObject):
    ghost_pointer_event = Signal(object)
    ghost_clear = Signal()


class _FakeClient:
    def __init__(self):
        self.batches = []
        self.focus = []
        self.clears = 0
        self.ok = True
        self.pid = 999

    def send_positions(self, pts, t_ms=None):
        self.batches.append(list(pts))
        self.t_ms = t_ms
        return self.ok

    def send_focus(self, wid):
        self.focus.append(wid)
        return True

    def send_clear(self):
        self.clears += 1
        return True

    def alive(self):
        return self.ok


def test_controller_never_spawns_off_cocoa(qapp):
    # Offscreen QPA: the spawn gate must refuse even on darwin - otherwise
    # every test suite would fork a helper process.
    from tabs.multitoon._ghost_cursors import GhostCursorController
    svc = _FakeService()
    ctl = GhostCursorController(svc, None)
    assert ctl._renderer is None
    ctl._hide_all()


def test_controller_renderer_mode_feeds_and_skips_local_render(qapp):
    from tabs.multitoon._ghost_cursors import GhostCursorController
    svc = _FakeService()
    ctl = GhostCursorController(svc, None,
                                slot_window_resolver=lambda s: str(GAME))
    fake = _FakeClient()
    ctl._renderer = fake
    try:
        ctl._feed_renderer(("motion", [(0, 100, 100)]))
        assert fake.batches == [[(0, 100, 100, str(GAME))]]
        ctl._on_pointer_event(("motion", [(0, 100, 100)]))
        assert ctl._overlays == {}          # no in-process rendering
        ctl.set_focused_window(str(GAME))
        assert fake.focus == [str(GAME)]
        ctl._hide_all()
        assert fake.clears == 1
    finally:
        ctl._renderer = None
        ctl._hide_all()


def test_controller_falls_back_when_renderer_dies(qapp):
    from tabs.multitoon._ghost_cursors import GhostCursorController
    svc = _FakeService()
    ctl = GhostCursorController(svc, None)
    fake = _FakeClient()
    fake.ok = False                          # dead pipe
    ctl._renderer = fake
    try:
        ctl._feed_renderer(("motion", [(0, 100, 100)]))
        assert ctl._renderer is None         # flipped back
        ctl._on_pointer_event(("motion", [(0, 120, 120)]))
        assert ctl._overlays[0].isVisible()  # in-process rendering resumed
    finally:
        ctl._hide_all()


# ── end-to-end: the real helper process over a real pipe (offscreen) ────────

def test_renderer_subprocess_round_trip(tmp_path):
    import subprocess
    main_py = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "main.py")
    env = dict(os.environ)
    env.update(QT_QPA_PLATFORM="offscreen", TTMT_NO_VENV_REEXEC="1",
               PYTHON_KEYRING_BACKEND="keyring.backends.null.Keyring",
               HOME=str(tmp_path), TTMT_CONFIG_DIR=str(tmp_path),
               XDG_CACHE_HOME=str(tmp_path))
    p = subprocess.Popen([sys.executable, main_py, "--ghost-renderer"],
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, env=env, text=True)
    try:
        p.stdin.write(proto.encode_position(0, 50, 60, "-"))
        p.stdin.write(proto.encode_clear())
        p.stdin.write(proto.encode_quit())
        p.stdin.flush()
        out, _ = p.communicate(timeout=30)
    except Exception:
        p.kill()
        raise
    assert p.returncode == 0, out
    assert "[GhostRenderer] ready" in out


# ── own-window exemption spans the TTMT process family (3-toon regression) ──

def test_core_parent_pid_windows_never_occlude(core, monkeypatch):
    """The live 3-toon regression: the APP's float cards sit above the game
    windows, and with only the renderer's pid exempt they carved gloves to
    nothing. Windows of ANY exempt pid (the renderer AND its parent app)
    must never occlude; foreign windows still do."""
    from tabs.multitoon import _ghost_cursors as gc
    core._exempt_pids = frozenset({111111, 222222})
    app_card = (555, (0, 0, 1600, 1200), 222222)      # parent-app window
    snap = [app_card, (GAME, (0, 0, 1600, 1200), 777)]
    monkeypatch.setattr(gc, "_darwin_zorder_snapshot", lambda: snap)
    core.feed_line(proto.encode_position(0, 100, 100, str(GAME)))
    core.tick()
    assert core._overlays[0].isVisible()               # card exempt: visible
    # A FOREIGN window in the same spot still hides the glove.
    core._inputs_cache.clear()
    snap2 = [(FOREIGN, (0, 0, 1600, 1200), 999),
             (GAME, (0, 0, 1600, 1200), 777)]
    monkeypatch.setattr(gc, "_darwin_zorder_snapshot", lambda: snap2)
    core.feed_line(proto.encode_position(0, 120, 120, str(GAME)))
    core.tick()
    assert not core._overlays[0].isVisible()


def test_core_default_exempt_pids_cover_self_and_parent():
    c = GhostRendererCore()
    assert os.getpid() in c._exempt_pids
    assert os.getppid() in c._exempt_pids


def test_scan_region_inputs_accepts_pid_container():
    from tabs.multitoon._ghost_cursors import _scan_region_inputs
    snap = [(555, (0, 0, 800, 600), 42),
            (GAME, (0, 0, 800, 600), 777)]
    ident = lambda a, b: (a, b)  # noqa: E731
    # int form (in-process callers) and container form (renderer) agree.
    as_int = _scan_region_inputs(GAME, snap, 42, ident)
    as_set = _scan_region_inputs(GAME, snap, frozenset({42, 43}), ident)
    assert as_int == as_set
    assert as_int[1] == []      # pid-42 window exempt in both forms


def test_core_inputs_cache_is_per_target(core, monkeypatch):
    """Multiple gloves alternate targets every tick: the inputs cache must
    hold one entry per target for a snapshot, not thrash on alternation."""
    from tabs.multitoon import _ghost_cursors as gc
    snap = [(GAME, (0, 0, 800, 600), 777),
            (555, (800, 0, 1600, 600), 888)]
    monkeypatch.setattr(gc, "_darwin_zorder_snapshot", lambda: snap)
    scans = []
    real = gc._scan_region_inputs
    monkeypatch.setattr(gc, "_scan_region_inputs",
                        lambda *a: scans.append(1) or real(*a))
    core.feed_line(proto.encode_position(0, 100, 100, str(GAME)))
    core.feed_line(proto.encode_position(1, 900, 100, "555"))
    core.tick()
    core.feed_line(proto.encode_position(0, 110, 100, str(GAME)))
    core.feed_line(proto.encode_position(1, 910, 100, "555"))
    core.tick()
    assert len(scans) == 2      # one scan per target, reused across ticks


# ── display smoothing: delivery jitter absorbed by construction ─────────────

def test_sample_at_interpolates_between_straddling_samples():
    from utils.ghost_renderer import _sample_at
    samples = [(10.0, 100, 100), (10.08, 300, 500)]
    x, y = _sample_at(samples, 10.04)
    assert (round(x), round(y)) == (200, 300)


def test_sample_at_holds_newest_when_stream_idle():
    from utils.ghost_renderer import _sample_at
    assert _sample_at([(10.0, 100, 100)], 11.0) == (100, 100)


def test_sample_at_renders_newest_on_stream_start():
    # Every sample newer than the display time (stream just began): instant
    # appearance beats delayed fidelity for the first frames.
    from utils.ghost_renderer import _sample_at
    assert _sample_at([(10.0, 100, 100), (10.01, 120, 120)], 9.9) == (120, 120)


def test_sample_at_empty_is_none():
    from utils.ghost_renderer import _sample_at
    assert _sample_at([], 1.0) is None


def test_tick_renders_interpolated_position(core, monkeypatch):
    import time as _time
    from utils import ghost_renderer as gr
    monkeypatch.setattr(gr, "DISPLAY_SMOOTH_S", 0.04)
    now = _time.monotonic()
    core._samples[0] = [(now - 0.08, 100, 100), (now, 300, 300)]
    core._latest[0] = (300, 300, None)
    core._last_sample_t[0] = now
    core.tick()
    x, y = _hotpos(core, 0)
    # display time = now-0.04 -> halfway between the two samples (tick's
    # own monotonic() is microseconds after ours: allow 1px of drift).
    assert abs(x - 200) <= 1 and abs(y - 200) <= 1


def test_smoothing_disabled_renders_newest(core, monkeypatch):
    import time as _time
    from utils import ghost_renderer as gr
    monkeypatch.setattr(gr, "DISPLAY_SMOOTH_S", 0)
    now = _time.monotonic()
    core._samples[0] = [(now - 0.08, 100, 100), (now, 300, 300)]
    core._latest[0] = (300, 300, None)
    core._last_sample_t[0] = now
    core.tick()
    assert _hotpos(core, 0) == (300, 300)


def test_sample_buffer_is_pruned(core):
    import time as _time
    now = _time.monotonic()
    core._samples[0] = [(now - 5.0 + i * 0.001, i, i) for i in range(200)]
    core._samples[0].append((now, 300, 300))
    core._latest[0] = (300, 300, None)
    core._last_sample_t[0] = now
    core.tick()
    assert len(core._samples[0]) < 10      # ancient samples dropped


def test_order_front_only_on_show_transition(core, monkeypatch):
    from utils import ghost_renderer as gr
    fronts = []
    monkeypatch.setattr(gr, "_order_front", lambda ov: fronts.append(1))
    core.feed_line(proto.encode_position(0, 100, 100, None))
    core.tick()
    assert fronts == [1]                   # shown: ordered front once
    core.feed_line(proto.encode_position(0, 200, 200, None))
    core.tick()
    core.feed_line(proto.encode_position(0, 250, 250, None))
    core.tick()
    assert fronts == [1]                   # moves while visible: no ordering


def test_bunched_delivery_replays_on_event_timeline(core, monkeypatch):
    """THE dejitter contract: five samples generated 8ms apart but DELIVERED
    in one burst (the app-side GIL/lock bunching) must render as even
    motion, because the buffer keys on the EVENT stamps riding the wire -
    arrival-time stamping replayed the bunching verbatim (live regression:
    'absolutely zero difference')."""
    import time as _time
    from utils import ghost_renderer as gr
    monkeypatch.setattr(gr, "DISPLAY_SMOOTH_S", 0.04)
    now = _time.monotonic()
    # Even event times 8ms apart, all fed NOW in one burst.
    for i in range(6):
        t_ms = int((now - 0.048 + i * 0.008) * 1000)
        core.feed_line(proto.encode_position(0, i * 100, 0, "-", t_ms))
    core.tick()
    x, _y = _hotpos(core, 0)
    # Display time = now - 40ms -> between sample 1 (t=-40ms, x=100) and
    # sample 2 (t=-32ms, x=200), NOT snapped to the newest (x=500).
    # ms-integer stamps + the tick's own clock allow ~2 samples of slack;
    # the essential assertion is "mid-path, far from the newest".
    assert 50 <= x <= 350


def test_stale_event_stamp_falls_back_to_arrival(core):
    core.feed_line(proto.encode_position(0, 100, 100, "-", 1234))  # ancient
    buf = core._samples[0]
    import time as _time
    assert abs(buf[-1][0] - _time.monotonic()) < 1.0   # arrival-stamped


# ── sprite-canvas display mode (the freeze fix) ─────────────────────────────

def test_canvas_mode_is_default_and_creates_one_canvas_per_screen(core):
    from utils import ghost_renderer as gr
    assert gr.CANVAS_MODE is True
    core.feed_line(proto.encode_position(0, 100, 100, None))
    core.tick()
    from PySide6.QtGui import QGuiApplication
    assert len(core._canvases) == len(QGuiApplication.screens())
    # The glove is a child sprite INSIDE the canvas - not a toplevel.
    sprite = core._overlays[0]
    assert sprite.label.parent() is core._canvases[0].widget


def test_canvas_window_is_never_moved_by_glove_motion(core):
    core.feed_line(proto.encode_position(0, 100, 100, None))
    core.tick()
    canvas = core._canvases[0]
    geo_before = canvas.widget.geometry()
    for i in range(5):
        core.feed_line(proto.encode_position(0, 200 + i * 50, 300, None))
        core.tick()
    assert canvas.widget.geometry() == geo_before   # static, always
    assert core._overlays[0].isVisible()


def test_sprite_reports_global_position(core):
    core.feed_line(proto.encode_position(0, 150, 250, None))
    core.tick()
    assert _hotpos(core, 0) == (150, 250)


def test_legacy_window_mode_kill_switch(qapp, monkeypatch):
    from utils import ghost_renderer as gr
    from tabs.multitoon._ghost_cursors import GhostCursorOverlay
    monkeypatch.setattr(gr, "CANVAS_MODE", False)
    c = GhostRendererCore()
    try:
        c.feed_line(proto.encode_position(0, 100, 100, None))
        c.tick()
        assert isinstance(c._overlays[0], GhostCursorOverlay)
        assert c._overlays[0].isVisible()
        assert c._canvases == []           # no canvas in legacy mode
    finally:
        c._hide_all()
        for ov in c._overlays.values():
            ov.deleteLater()


def test_client_module_imports_without_fcntl(monkeypatch):
    """fcntl is Unix-only and the frozen Windows self-check imports EVERY
    module: a top-level `import fcntl` in the client broke the packaged
    Windows build (CI 2026-07-05). The import must live at USE (inside
    start(), which only ever runs on real cocoa). Simulate Windows by making
    `import fcntl` raise, then import the module fresh."""
    import importlib
    import sys

    saved = sys.modules.pop("utils.ghost_renderer_client", None)
    monkeypatch.setitem(sys.modules, "fcntl", None)   # None -> ImportError
    try:
        mod = importlib.import_module("utils.ghost_renderer_client")
        assert mod is not None
    finally:
        sys.modules.pop("utils.ghost_renderer_client", None)
        if saved is not None:
            sys.modules["utils.ghost_renderer_client"] = saved
