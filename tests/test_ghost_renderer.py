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
        ("position", 2, 10, -5, "123")
    assert proto.decode_line(proto.encode_position(0, 1, 2, None)) == \
        ("position", 0, 1, 2, None)
    assert proto.decode_line(proto.encode_focus("77")) == ("focus", "77")
    assert proto.decode_line(proto.encode_focus(None)) == ("focus", None)
    assert proto.decode_line(proto.encode_clear()) == ("clear",)
    assert proto.decode_line(proto.encode_quit()) == ("quit",)


def test_protocol_tolerates_garbage():
    for junk in ("", "\n", "X 1 2", "P 1 2", "P a b c d", "PP 1 2 3 4"):
        assert proto.decode_line(junk) is None


# ── renderer core (offscreen) ────────────────────────────────────────────────

@pytest.fixture
def core(qapp):
    c = GhostRendererCore()
    yield c
    c._hide_all()
    for ov in c._overlays.values():
        ov.deleteLater()


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

    def send_positions(self, pts):
        self.batches.append(list(pts))
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
