import importlib.util
import pathlib
import sys
import types

import pytest

_SPIKE = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "macos_mouse_spike.py"
_spec = importlib.util.spec_from_file_location("macos_mouse_spike", _SPIKE)
spike = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = spike
_spec.loader.exec_module(spike)


def test_content_rect_zero_inset_is_identity():
    assert spike.content_rect((10, 20, 800, 600), 0) == (10, 20, 800, 600)


def test_content_rect_subtracts_top_inset():
    # A 28pt title bar shifts the content origin down and shrinks the height.
    assert spike.content_rect((10, 20, 800, 600), 28) == (10, 48, 800, 572)


def test_content_rect_never_negative_height():
    # A pathological inset larger than the frame clamps height to 0, never negative.
    assert spike.content_rect((0, 0, 100, 20), 50) == (0, 50, 100, 0)


def test_content_point_to_global_corners_and_center():
    frame = (100, 200, 800, 600)  # inset 0 -> content == frame
    assert spike.content_point_to_global((0.0, 0.0), frame, 0) == (100.0, 200.0)
    assert spike.content_point_to_global((1.0, 1.0), frame, 0) == (900.0, 800.0)
    assert spike.content_point_to_global((0.5, 0.5), frame, 0) == (500.0, 500.0)


def test_content_point_to_global_respects_inset():
    frame = (0, 0, 200, 120)
    # inset 20 -> content (0,20,200,100); center maps to (100, 70).
    assert spike.content_point_to_global((0.5, 0.5), frame, 20) == (100.0, 70.0)


def test_main_no_args_and_unknown_return_2():
    assert spike.main([]) == 2
    assert spike.main(["bogus"]) == 2


@pytest.mark.parametrize("cmd,func", [
    ("list", "cmd_list"), ("probe-rect", "cmd_probe_rect"), ("click", "cmd_click"),
    ("motion", "cmd_motion"), ("echo", "cmd_echo"),
])
def test_main_routes_every_command_and_forwards_args(monkeypatch, cmd, func):
    calls = []
    monkeypatch.setattr(spike, func, lambda rest: (calls.append(rest), 0)[1])
    assert spike.main([cmd, "x", "y"]) == 0
    assert calls == [["x", "y"]]


class _FakeQuartz:
    # Records the CGEvent the spike builds so the test can assert the stamp.
    kCGEventSourceUserData = 111
    kCGMouseButtonLeft = 0
    kCGMouseButtonCenter = 2
    kCGEventMouseMoved = 5
    kCGEventLeftMouseDown = 1
    kCGEventLeftMouseUp = 2
    kCGEventLeftMouseDragged = 6
    kCGEventOtherMouseDragged = 27

    def __init__(self):
        self.posted = []        # (pid, event)
        self.fields = {}        # id(event) -> {field: value}

    def CGEventCreateMouseEvent(self, src, etype, pos, button):
        ev = types.SimpleNamespace(etype=etype, pos=pos, button=button)
        self.fields[id(ev)] = {}
        return ev

    def CGEventSetIntegerValueField(self, ev, field, value):
        self.fields[id(ev)][field] = value

    def CGEventPostToPid(self, pid, ev):
        self.posted.append((pid, ev))


def test_post_mouse_stamps_marker_and_posts(monkeypatch):
    fq = _FakeQuartz()
    monkeypatch.setattr(spike.kb, "_quartz", lambda: fq)
    monkeypatch.setattr(spike.kb, "preflight_post_access", lambda: True)
    # Pass an explicit source so post_mouse does NOT call kb._event_source()
    # (which the fake Quartz does not implement); this isolates the stamp path.
    ok = spike.post_mouse(4242, 7, fq.kCGEventLeftMouseDown, 120.0, 240.0,
                          button=fq.kCGMouseButtonLeft, source=object(),
                          revalidate=False)
    assert ok is True
    assert len(fq.posted) == 1
    pid, ev = fq.posted[0]
    assert pid == 4242
    assert fq.fields[id(ev)][fq.kCGEventSourceUserData] == spike.SPIKE_EVENT_TAG


def test_post_mouse_refuses_without_access(monkeypatch):
    fq = _FakeQuartz()
    monkeypatch.setattr(spike.kb, "_quartz", lambda: fq)
    monkeypatch.setattr(spike.kb, "preflight_post_access", lambda: False)
    assert spike.post_mouse(4242, 7, fq.kCGEventLeftMouseDown, 1.0, 2.0,
                            source=object(), revalidate=False) is False
    assert fq.posted == []


def _stub_window(monkeypatch, pids):
    # enumerate_windows() -> one WindowRecord per pid, frame (0,0,800,600).
    recs = [spike.kb.WindowRecord(pid=p, window_id=p * 10, owner="Toontown Rewritten",
                                  bounds=(0, 0, 800, 600), bundle_id="com.ttr")
            for p in pids]
    monkeypatch.setattr(spike.kb, "enumerate_windows", lambda: recs)
    return recs


def _capture_posts(monkeypatch, ok=True):
    """Patch post_mouse to record (pid, etype) per call and return `ok`.

    Lets the click/probe-rect tests assert the real choreography (which pid,
    which event, in what order) instead of only a coarse exit code. Also fakes
    kb._quartz (event-type constants) and spike.time.sleep (no real waiting).
    """
    posts = []

    def _rec(pid, wid, etype, gx, gy, *a, **k):
        posts.append((pid, etype, gx, gy))
        return ok

    monkeypatch.setattr(spike.kb, "_quartz", lambda: _FakeQuartz())
    monkeypatch.setattr(spike.time, "sleep", lambda *_a: None)
    monkeypatch.setattr(spike, "post_mouse", _rec)
    return posts


def test_cmd_click_drives_all_four_stages_to_right_targets(monkeypatch):
    _stub_window(monkeypatch, [4242, 5252])  # pidA=4242, pidB=5252
    monkeypatch.setattr("builtins.input", lambda *_a: "")
    posts = _capture_posts(monkeypatch)
    assert spike.cmd_click(["4242", "5252"]) == 0
    Q = _FakeQuartz()
    down, up = Q.kCGEventLeftMouseDown, Q.kCGEventLeftMouseUp
    c = (400.0, 300.0)  # content center of the (0,0,800,600) frame at inset 0
    # baseline B, central B, reverse A, third-app B -- each a down then an up,
    # always at the window center.
    assert posts == [
        (5252, down, *c), (5252, up, *c),   # baseline  -> pidB
        (5252, down, *c), (5252, up, *c),   # central   -> pidB
        (4242, down, *c), (4242, up, *c),   # reverse   -> pidA
        (5252, down, *c), (5252, up, *c),   # third-app -> pidB
    ]


def test_cmd_click_refused_returns_exactly_one(monkeypatch):
    _stub_window(monkeypatch, [4242, 5252])
    monkeypatch.setattr("builtins.input", lambda *_a: "")
    _capture_posts(monkeypatch, ok=False)  # every post refused
    assert spike.cmd_click(["4242", "5252"]) == 1


def test_click_at_returns_one_when_window_gone(monkeypatch):
    _stub_window(monkeypatch, [4242])  # target 9999 is absent from the list
    monkeypatch.setattr(spike.kb, "_quartz", lambda: _FakeQuartz())
    assert spike._click_at(9999, 90, (0.5, 0.5), 0, "com.ttr") == 1


def test_cmd_probe_rect_clicks_five_points(monkeypatch):
    _stub_window(monkeypatch, [4242])
    monkeypatch.setattr("builtins.input", lambda *_a: "")
    posts = _capture_posts(monkeypatch)
    assert spike.cmd_probe_rect(["4242"]) == 0
    Q = _FakeQuartz()
    down, up = Q.kCGEventLeftMouseDown, Q.kCGEventLeftMouseUp
    # 4 corners (0.02/0.98) + center, each a down+up, at the exact global points
    # for the (0,0,800,600) frame at inset 0 -- verifies the corner walk.
    assert posts == [
        (4242, down, 16.0, 12.0),   (4242, up, 16.0, 12.0),     # top-left
        (4242, down, 784.0, 12.0),  (4242, up, 784.0, 12.0),    # top-right
        (4242, down, 16.0, 588.0),  (4242, up, 16.0, 588.0),    # bottom-left
        (4242, down, 784.0, 588.0), (4242, up, 784.0, 588.0),   # bottom-right
        (4242, down, 400.0, 300.0), (4242, up, 400.0, 300.0),   # center
    ]


def test_cmd_click_rejects_equal_pids(monkeypatch):
    assert spike.cmd_click(["4242", "4242"]) == 2


def test_cmd_motion_rejects_bad_mode_and_kind(monkeypatch):
    _stub_window(monkeypatch, [4242])
    assert spike.cmd_motion(["4242", "--mode", "bogus"]) == 2
    assert spike.cmd_motion(["4242", "--kind", "bogus"]) == 2
    # A sweep needs both ends: --steps < 2 is rejected (before any PyObjC).
    assert spike.cmd_motion(["4242", "--steps", "1"]) == 2
    assert spike.cmd_motion(["4242", "--steps", "0"]) == 2


def _capture_motion(monkeypatch):
    """Patch post_mouse to record (pid, wid, etype, gx, gy, button, revalidate)
    per call (success), fake kb._quartz, and silence time.sleep. Also stubs
    enumerate_windows via _stub_window so the post-prompt revalidation passes."""
    calls = []

    def _rec(pid, wid, etype, gx, gy, *a, **k):
        calls.append((pid, wid, etype, gx, gy, k.get("button"), k.get("revalidate")))
        return True

    monkeypatch.setattr(spike.kb, "_quartz", lambda: _FakeQuartz())
    monkeypatch.setattr(spike.time, "sleep", lambda *_a: None)
    monkeypatch.setattr(spike, "post_mouse", _rec)
    return calls


def test_cmd_motion_hover_plain_sweeps_moves_left_to_right(monkeypatch):
    _stub_window(monkeypatch, [4242])
    monkeypatch.setattr("builtins.input", lambda *_a: "")
    calls = _capture_motion(monkeypatch)
    rc = spike.cmd_motion(["4242", "--kind", "hover", "--mode", "plain", "--steps", "5"])
    assert rc == 0
    moved = _FakeQuartz().kCGEventMouseMoved
    # 5 hover samples, ALL mouseMoved, to pid 4242, sweeping strictly L->R, with
    # no button override and the hot-path revalidate=False.
    assert len(calls) == 5
    assert all(c[0] == 4242 and c[2] == moved for c in calls)
    assert all(c[5] is None and c[6] is False for c in calls)
    xs = [c[3] for c in calls]
    assert xs == sorted(xs) and xs[0] < xs[-1]


def test_cmd_motion_drag_plain_brackets_sweep_with_down_up(monkeypatch):
    _stub_window(monkeypatch, [4242])
    monkeypatch.setattr("builtins.input", lambda *_a: "")
    calls = _capture_motion(monkeypatch)
    rc = spike.cmd_motion(["4242", "--kind", "drag", "--mode", "plain", "--steps", "3"])
    assert rc == 0
    Q = _FakeQuartz()
    # leftMouseDown, then 3x leftMouseDragged, then leftMouseUp.
    assert [c[2] for c in calls] == [
        Q.kCGEventLeftMouseDown,
        Q.kCGEventLeftMouseDragged, Q.kCGEventLeftMouseDragged,
        Q.kCGEventLeftMouseDragged,
        Q.kCGEventLeftMouseUp,
    ]


def test_cmd_motion_hover_carrier_posts_other_dragged(monkeypatch):
    _stub_window(monkeypatch, [4242])
    monkeypatch.setattr("builtins.input", lambda *_a: "")
    calls = _capture_motion(monkeypatch)
    rc = spike.cmd_motion(["4242", "--kind", "hover", "--mode", "carrier", "--steps", "3"])
    assert rc == 0
    Q = _FakeQuartz()
    # carrier hover: the inert CENTER-button carrier, no bracket -> 3x otherDragged.
    assert len(calls) == 3
    assert all(c[2] == Q.kCGEventOtherMouseDragged
               and c[5] == Q.kCGMouseButtonCenter and c[6] is False
               for c in calls)


def test_cmd_motion_drag_carrier_posts_other_dragged_no_bracket(monkeypatch):
    _stub_window(monkeypatch, [4242])
    monkeypatch.setattr("builtins.input", lambda *_a: "")
    calls = _capture_motion(monkeypatch)
    rc = spike.cmd_motion(["4242", "--kind", "drag", "--mode", "carrier", "--steps", "3"])
    assert rc == 0
    Q = _FakeQuartz()
    # carrier drag uses the same inert CENTER carrier and NO real down/up bracket.
    assert len(calls) == 3
    assert all(c[2] == Q.kCGEventOtherMouseDragged
               and c[5] == Q.kCGMouseButtonCenter and c[6] is False
               for c in calls)
