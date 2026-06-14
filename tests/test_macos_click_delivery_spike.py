import importlib.util
import pathlib
import sys
import types

import pytest

_SPIKE = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "macos_click_delivery_spike.py"
_spec = importlib.util.spec_from_file_location("macos_click_delivery_spike", _SPIKE)
spike = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = spike
_spec.loader.exec_module(spike)


class _FakeSky:
    """Minimal stand-in for the Quartz + SkyLight surface build_cg_event uses."""
    def __init__(self):
        self.fields = {}
        self.window_locations = {}
        self.locations = {}
        self.source_user_data = {}
        self.posted = []   # [(pid, kind), ...] recorded by post()

    def make_event(self, kind, click_count, window_number):
        ev = types.SimpleNamespace(kind=kind, cc=click_count, win=window_number)
        self.fields[id(ev)] = {"public": {}, "private": {}}
        return ev

    def set_public_field(self, ev, field, value):
        self.fields[id(ev)]["public"][field] = value

    def set_private_field(self, ev, field, value):
        self.fields[id(ev)]["private"][field] = value

    def set_window_location(self, ev, pt):
        self.window_locations[id(ev)] = pt

    def set_location(self, ev, pt):
        self.locations[id(ev)] = pt

    def set_source_user_data(self, ev, tag):
        self.source_user_data[id(ev)] = tag

    def post(self, pid, ev):
        self.posted.append((pid, getattr(ev, "kind", None)))


def test_main_no_args_and_unknown_return_2():
    assert spike.main([]) == 2
    assert spike.main(["bogus"]) == 2


@pytest.mark.parametrize("cmd,func", [
    ("list", "cmd_list"),
    ("probe-rect", "cmd_probe_rect"),
    ("sl-click", "cmd_sl_click"),
    ("sl-gesture", "cmd_sl_gesture"),
    ("sl-fanout", "cmd_sl_fanout"),
    ("sl-positive-control", "cmd_sl_positive_control"),
    ("sl-echo", "cmd_sl_echo"),
    ("timeslice-click", "cmd_timeslice"),
    ("timeslice-drag", "cmd_timeslice"),
    ("inject-preflight", "cmd_inject_preflight"),
])
def test_main_routes_every_command_and_forwards_args(monkeypatch, cmd, func):
    calls = []
    monkeypatch.setattr(spike, func, lambda rest: (calls.append(rest), 0)[1])
    assert spike.main([cmd, "x", "y"]) == 0
    assert calls == [["x", "y"]]


def test_focus_record_layout():
    rec = spike.build_focus_record(0x1234ABCD, mode=0x01)
    assert isinstance(rec, (bytes, bytearray))
    assert len(rec) == 0xF8
    assert rec[0x04] == 0xF8
    assert rec[0x08] == 0x0D
    assert rec[0x8A] == 0x01
    # window id is a u32 little-endian at [0x3C:0x40]
    assert bytes(rec[0x3C:0x40]) == (0x1234ABCD).to_bytes(4, "little")
    # everything else is zero
    cleared = bytearray(rec)
    for off in (0x04, 0x08, 0x8A):
        cleared[off] = 0
    cleared[0x3C:0x40] = b"\x00\x00\x00\x00"
    assert set(cleared) == {0}


def test_focus_record_defocus_mode():
    rec = spike.build_focus_record(1, mode=0x02)
    assert rec[0x8A] == 0x02


def test_psn_pack_unpack_roundtrip():
    assert spike.pack_psn((0, 0x2A)) == (0).to_bytes(4, "little") + (0x2A).to_bytes(4, "little")
    assert spike.unpack_psn(spike.pack_psn((7, 99))) == (7, 99)
    assert len(spike.pack_psn((1, 1))) == 8


def test_mouse_event_fields_values_and_setters():
    fields = spike.mouse_event_fields(pid=4321, window_id=77)
    # ordered (field_id, value, via_private)
    assert fields == [
        (1, 1, False),    # kCGMouseEventClickState
        (3, 0, False),    # kCGMouseEventButtonNumber
        (7, 3, False),    # kCGMouseEventSubtype
        (40, 4321, True), # kCGEventTargetUnixProcessID (private setter, per cua)
        (91, 77, True),   # window under pointer
        (92, 77, True),   # window under pointer that can handle this event
    ]


def test_timing_profiles_with_primer():
    assert spike.timing_gaps("zero", has_primer=True) == {
        "after_move": 0.0, "primer_internal": 0.0,
        "primer_to_target": 0.0, "down_to_up": 0.0,
    }
    assert spike.timing_gaps("cua", has_primer=True) == {
        "after_move": 0.015, "primer_internal": 0.001,
        "primer_to_target": 0.100, "down_to_up": 0.001,
    }
    assert spike.timing_gaps("16ms", has_primer=True)["after_move"] == 0.016


def test_timing_profiles_without_primer_zero_the_primer_gaps():
    g = spike.timing_gaps("cua", has_primer=False)
    assert g["primer_internal"] == 0.0
    assert g["primer_to_target"] == 0.0
    assert g["after_move"] == 0.015  # non-primer gaps unaffected


def test_timing_unknown_profile_raises():
    import pytest as _pytest
    with _pytest.raises(ValueError):
        spike.timing_gaps("bogus", has_primer=False)


def test_click_specs_minimal_no_primer():
    specs = spike.click_event_specs((100.0, 50.0), primer=False)
    assert [(s.kind, s.point, s.click_count, s.primer) for s in specs] == [
        ("move", (100.0, 50.0), 0, False),
        ("down", (100.0, 50.0), 1, False),
        ("up",   (100.0, 50.0), 1, False),
    ]


def test_click_specs_with_primer_inserts_offwindow_pair():
    specs = spike.click_event_specs((10.0, 20.0), primer=True)
    kinds = [(s.kind, s.point, s.primer) for s in specs]
    assert kinds == [
        ("move", (10.0, 20.0), False),
        ("down", (-1.0, -1.0), True),
        ("up",   (-1.0, -1.0), True),
        ("down", (10.0, 20.0), False),
        ("up",   (10.0, 20.0), False),
    ]


def test_hover_specs_are_all_moves():
    pts = [(0.0, 0.0), (5.0, 5.0), (9.0, 9.0)]
    specs = spike.hover_event_specs(pts)
    assert all(s.kind == "move" and s.click_count == 0 for s in specs)
    assert [s.point for s in specs] == pts


def test_drag_specs_prime_down_drag_up_with_intermediate_points():
    specs = spike.drag_event_specs((0.0, 0.0), (10.0, 0.0), steps=2)
    kinds = [s.kind for s in specs]
    # move (prime), down, 2 dragged, up
    assert kinds == ["move", "down", "dragged", "dragged", "up"]
    assert specs[0].point == (0.0, 0.0) and specs[1].point == (0.0, 0.0)
    assert specs[-1].point == (10.0, 0.0)
    # every drag event carries click_count 1 from down through up
    assert all(s.click_count == 1 for s in specs[1:])
    # intermediate points strictly advance toward the target
    xs = [s.point[0] for s in specs]
    assert xs == sorted(xs)


def test_drag_steps_must_be_at_least_one():
    import pytest as _pytest
    with _pytest.raises(ValueError):
        spike.drag_event_specs((0, 0), (1, 1), steps=0)


def test_drag_specs_interpolate_both_axes():
    # diagonal drag: pins the EXACT interpolated value on BOTH axes (a forward-only
    # sorted-xs check cannot catch a wrong y term).
    specs = spike.drag_event_specs((0.0, 0.0), (10.0, 20.0), steps=2)
    assert specs[2].kind == "dragged" and specs[2].point == (5.0, 10.0)
    assert specs[3].kind == "dragged" and specs[3].point == (10.0, 20.0)
    assert specs[-1].kind == "up" and specs[-1].point == (10.0, 20.0)


def test_builders_coerce_int_coords_to_float():
    # click/hover/drag all coerce int inputs to float (uniform across builders).
    for s in spike.click_event_specs((3, 4), primer=True):
        assert all(isinstance(v, float) for v in s.point)
    for s in spike.hover_event_specs([(1, 2)]):
        assert all(isinstance(v, float) for v in s.point)
    for s in spike.drag_event_specs((1, 2), (3, 4), steps=1):
        assert all(isinstance(v, float) for v in s.point)
    for _phase, _tid, s in spike.fanout_phase_plan(["A"], (5, 6)):
        assert all(isinstance(v, float) for v in s.point)


def test_fanout_plan_is_phase_wise_not_serial():
    # two targets; plan groups ALL moves, then ALL downs, then ALL ups.
    plan = spike.fanout_phase_plan(["A", "B"], (3.0, 4.0))
    assert [(phase, tid) for (phase, tid, spec) in plan] == [
        ("move", "A"), ("move", "B"),
        ("down", "A"), ("down", "B"),
        ("up", "A"), ("up", "B"),
    ]
    # every spec carries the shared point; downs/ups are click_count 1, moves 0
    for phase, tid, spec in plan:
        assert spec.point == (3.0, 4.0)
        assert spec.click_count == (0 if phase == "move" else 1)


def test_fanout_plan_single_target_still_phase_ordered():
    plan = spike.fanout_phase_plan(["only"], (0.0, 0.0))
    assert [phase for (phase, _t, _s) in plan] == ["move", "down", "up"]


def test_fanout_plan_rejects_empty_targets():
    import pytest as _pytest
    with _pytest.raises(ValueError):
        spike.fanout_phase_plan([], (0.0, 0.0))


def test_parse_sl_args_defaults_are_minimal():
    opts = spike.parse_sl_args(["123", "77"])
    assert opts.positionals == ["123", "77"]
    assert opts.focus is False and opts.primer is False and opts.restore_focus is False
    assert opts.timing == "1ms"
    assert opts.inset == 0
    assert opts.frac == (0.5, 0.5)
    assert opts.reps == 1
    assert opts.kind is None   # amendment: --kind is required for gesture, no default


def test_parse_sl_args_flags_and_values():
    opts = spike.parse_sl_args(
        ["9", "8", "--focus", "--primer", "--restore-focus",
         "--timing", "cua", "--inset", "28", "--frac", "0.1", "0.2",
         "--hold", "0.6", "--reps", "10", "--kind", "drag",
         "--from", "0.05", "0.5", "--to", "0.95", "0.5"])
    assert opts.focus and opts.primer and opts.restore_focus
    assert opts.timing == "cua" and opts.inset == 28
    assert opts.frac == (0.1, 0.2) and opts.hold == 0.6 and opts.reps == 10
    assert opts.kind == "drag"
    assert opts.frm == (0.05, 0.5) and opts.to == (0.95, 0.5)


def test_parse_sl_args_rejects_restore_without_focus():
    import pytest as _pytest
    with _pytest.raises(spike.ArgError):
        spike.parse_sl_args(["1", "2", "--restore-focus"])


def test_parse_sl_args_rejects_unknown_timing():
    import pytest as _pytest
    with _pytest.raises(spike.ArgError):
        spike.parse_sl_args(["1", "2", "--timing", "fast"])


def test_parse_sl_args_rejects_unknown_kind():
    import pytest as _pytest
    with _pytest.raises(spike.ArgError):
        spike.parse_sl_args(["1", "2", "--kind", "wiggle"])


def test_parse_sl_args_rejects_unknown_flag():
    import pytest as _pytest
    with _pytest.raises(spike.ArgError):
        spike.parse_sl_args(["1", "2", "--bogus"])


def test_parse_sl_args_rejects_missing_or_swallowed_value():
    import pytest as _pytest
    with _pytest.raises(spike.ArgError):
        spike.parse_sl_args(["1", "2", "--timing"])            # value flag at end
    with _pytest.raises(spike.ArgError):
        spike.parse_sl_args(["1", "2", "--frac", "0.1"])       # pair flag, one value
    with _pytest.raises(spike.ArgError):
        spike.parse_sl_args(["1", "2", "--timing", "--focus"])  # next flag not swallowed


def test_parse_sl_args_rejects_nonpositive_reps_and_negative_inset():
    import pytest as _pytest
    with _pytest.raises(spike.ArgError):
        spike.parse_sl_args(["1", "2", "--reps", "0"])
    with _pytest.raises(spike.ArgError):
        spike.parse_sl_args(["1", "2", "--inset", "-1"])
    # a negative coordinate is still a valid value (single '-', not a flag)
    ok = spike.parse_sl_args(["1", "2", "--frac", "-0.1", "0.2"])
    assert ok.frac == (-0.1, 0.2)


def test_skylight_symbol_table_exact_signatures():
    # [AMENDMENT] assert the EXACT (restype, argtypes) per spec 2.2, not just names.
    S = spike.SKYLIGHT_SYMBOLS
    assert S["CGSMainConnectionID"] == ("uint32", ())
    assert S["SLSGetWindowOwner"] == ("int32", ("uint32", "uint32", "ptr"))
    assert S["SLSGetConnectionPSN"] == ("int32", ("uint32", "ptr"))
    assert S["_SLPSGetFrontProcess"] == ("int32", ("ptr",))
    assert S["SLPSPostEventRecordTo"] == ("int32", ("ptr", "ptr"))
    assert S["CGEventSetWindowLocation"] == ("void", ("ptr", "cgpoint"))
    assert S["SLEventSetIntegerValueField"] == ("void", ("ptr", "uint32", "int64"))
    assert S["CGEventSetTimestamp"] == ("void", ("ptr", "uint64"))
    assert S["SLEventPostToPid"] == ("void", ("pid", "ptr"))


def test_build_cg_event_stamps_all_fields_and_window_location():
    fake = _FakeSky()
    ev = spike.build_cg_event(
        fake, kind="down", win_point=(12.0, 34.0), screen_point=(112.0, 234.0),
        click_count=1, pid=4321, window_id=77)
    # [AMENDMENT] the NSEvent args make_event received: type(kind), click_count, window_number
    assert ev.kind == "down" and ev.cc == 1 and ev.win == 77
    f = fake.fields[id(ev)]
    # public fields via set_public_field, private via set_private_field
    assert f["public"][1] == 1 and f["public"][3] == 0 and f["public"][7] == 3
    assert f["private"][40] == 4321 and f["private"][91] == 77 and f["private"][92] == 77
    assert fake.window_locations[id(ev)] == (12.0, 34.0)
    assert fake.locations[id(ev)] == (112.0, 234.0)
    assert fake.source_user_data[id(ev)] == spike.SPIKE_EVENT_TAG


def test_summarize_samples_detects_change():
    samples = [(100, 10.0, 20.0), (100, 10.0, 20.0), (100, 10.5, 20.0)]
    s = spike.summarize_samples(samples)
    assert s["frontmost_pids"] == [100]
    assert s["cursor_moved"] is True
    assert s["cursor_x_range"] == (10.0, 10.5)


def test_summarize_samples_stable_when_no_change():
    samples = [(7, 5.0, 5.0), (7, 5.0, 5.0)]
    s = spike.summarize_samples(samples)
    assert s["frontmost_pids"] == [7]
    assert s["cursor_moved"] is False
    assert s["focus_changed"] is False


def test_summarize_samples_flags_focus_change():
    samples = [(1, 0.0, 0.0), (2, 0.0, 0.0)]
    s = spike.summarize_samples(samples)
    assert s["focus_changed"] is True
    assert set(s["frontmost_pids"]) == {1, 2}


def test_summarize_empty_is_inconclusive():
    s = spike.summarize_samples([])
    assert s["inconclusive"] is True


def test_summarize_samples_flags_isactive_change():
    # [AMENDMENT] 6-tuples (fp, cx, cy, src_active, tgt_active, ax): source active flips
    samples = [(9, 0.0, 0.0, True, False, None), (9, 0.0, 0.0, False, False, None)]
    s = spike.summarize_samples(samples)
    assert s["isactive_changed"] is True
    assert s["focus_changed"] is False and s["cursor_moved"] is False


def test_sampler_lifecycle_with_injected_probes_survives_raising_probe():
    # [AMENDMENT] a raising probe must not kill the thread; ticks continue.
    import threading as _th
    enough = _th.Event()
    calls = {"n": 0}

    def cursor_fn():
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("transient cursor read failure")
        if calls["n"] >= 4:
            enough.set()
        return (float(calls["n"]), 0.0)

    sampler = spike.FocusCursorSampler(
        source_pid=1, target_pid=2, interval=0.001,
        cursor_fn=cursor_fn, frontmost_fn=lambda: 1,
        isactive_fn=lambda pid: True, ax_fn=lambda fp: None)
    sampler.start()
    assert enough.wait(timeout=2.0)   # survived the raising tick and kept going
    summary = sampler.stop()
    assert summary["inconclusive"] is False
    assert summary["thread_stopped"] is True
    assert len(sampler.samples) >= 2   # successful ticks recorded (raising one skipped)


def test_summarize_inconclusive_has_all_keys():
    # callers may read ranges/ax without first gating on `inconclusive`.
    s = spike.summarize_samples([])
    for k in ("cursor_x_range", "cursor_y_range", "ax_focused_windows",
              "isactive_changed", "frontmost_pids"):
        assert k in s


def test_summarize_isactive_single_value_does_not_flag():
    # a None followed by a single real value is NOT a flip.
    samples = [(1, 0.0, 0.0, None, None, None), (1, 0.0, 0.0, True, False, None)]
    s = spike.summarize_samples(samples)
    assert s["isactive_changed"] is False


def test_sampler_stop_before_start_is_inconclusive():
    s = spike.FocusCursorSampler(cursor_fn=lambda: (0.0, 0.0), frontmost_fn=lambda: 1,
                                 isactive_fn=lambda p: None, ax_fn=lambda f: None)
    out = s.stop()
    assert out["inconclusive"] is True and out["thread_stopped"] is True


def test_sampler_double_start_raises():
    import pytest as _pytest
    s = spike.FocusCursorSampler(cursor_fn=lambda: (0.0, 0.0), frontmost_fn=lambda: 1,
                                 isactive_fn=lambda p: None, ax_fn=lambda f: None,
                                 interval=0.001)
    s.start()
    try:
        with _pytest.raises(RuntimeError):
            s.start()
    finally:
        s.stop()


def test_sampler_ipc_probes_run_on_subcadence_not_every_tick():
    # locks the FULL cadence split: cheap probes (cursor, frontmost) every tick,
    # IPC probes (isActive, AX) only on the sub-cadence, carried forward, tick-0 IPC.
    import threading as _th
    enough = _th.Event()
    c = {"cursor": 0, "frontmost": 0, "isactive": 0, "ax": 0}

    def cursor_fn():
        c["cursor"] += 1
        if c["cursor"] >= 60:
            enough.set()
        return (0.0, 0.0)

    def frontmost_fn():
        c["frontmost"] += 1
        return 1

    def isactive_fn(pid):
        c["isactive"] += 1   # called for src AND tgt on each IPC-cadence tick
        return f"act{pid}"   # distinct per pid so the value in the sample is verifiable

    def ax_fn(fp):
        c["ax"] += 1
        return "AXWIN"

    s = spike.FocusCursorSampler(
        source_pid=1, target_pid=2, interval=0.001, ipc_interval=0.05,  # _ipc_every=50
        cursor_fn=cursor_fn, frontmost_fn=frontmost_fn,
        isactive_fn=isactive_fn, ax_fn=ax_fn)
    s.start()
    assert enough.wait(2.0)
    s.stop()
    # cheap probes run EVERY tick; IPC probes run far less often (sub-cadence).
    assert c["frontmost"] == c["cursor"]          # frontmost is every-tick (cheap)
    assert c["ax"] < c["cursor"] // 10            # ax is sub-cadence
    assert c["isactive"] < c["cursor"] // 5       # isactive (2 per IPC tick) sub-cadence
    # tick-0 IPC values (src isActive, tgt isActive, ax) reach the sample...
    assert s.samples[0][3] == "act1" and s.samples[0][4] == "act2" and s.samples[0][5] == "AXWIN"
    # ...and carry forward unchanged on the next intervening cheap-only tick.
    assert s.samples[1][3] == "act1" and s.samples[1][4] == "act2" and s.samples[1][5] == "AXWIN"


def test_sampler_reports_not_stopped_when_worker_parks():
    # the thread_stopped flag surfaces a worker parked in a slow probe.
    import threading as _th
    started, release = _th.Event(), _th.Event()

    def cursor_fn():
        started.set()
        release.wait(timeout=2.0)   # park the worker until the test releases it
        return (0.0, 0.0)

    s = spike.FocusCursorSampler(cursor_fn=cursor_fn, frontmost_fn=lambda: 1,
                                 isactive_fn=lambda p: None, ax_fn=lambda f: None,
                                 interval=0.001)
    s.start()
    assert started.wait(1.0)
    out = s.stop(join_timeout=0.05)    # worker still parked in cursor_fn
    assert out["thread_stopped"] is False
    release.set()                      # let the daemon finish


def _winrec(pid=1, window_id=77, w=800, h=600):
    return spike.kb.WindowRecord(pid=pid, window_id=window_id,
                                 owner="Toontown Rewritten", bounds=(0, 0, w, h))


def test_win_local_and_screen_point_roundtrip():
    rec = spike.kb.WindowRecord(1, 77, "Toontown Rewritten", (100, 200, 800, 600))
    wl = spike._win_local(rec, (0.5, 0.5), inset=0)
    assert wl == (400.0, 300.0)
    assert spike._screen_point(rec, wl, inset=0) == (500.0, 500.0)
    # inset shifts the content origin down (and shrinks height)
    wl2 = spike._win_local(rec, (0.0, 0.0), inset=28)
    assert wl2 == (0.0, 0.0)
    assert spike._screen_point(rec, wl2, inset=28) == (100.0, 228.0)


def test_gap_after_selects_the_right_gap():
    g = {"after_move": 0.9, "primer_internal": 0.1, "primer_to_target": 0.5, "down_to_up": 0.2}
    move = spike.EventSpec("move", (0.0, 0.0), 0)
    down = spike.EventSpec("down", (0.0, 0.0), 1)
    up = spike.EventSpec("up", (0.0, 0.0), 1)
    pdown = spike.EventSpec("down", spike.OFF_WINDOW_POINT, 1, primer=True)
    pup = spike.EventSpec("up", spike.OFF_WINDOW_POINT, 1, primer=True)
    assert spike._gap_after(move, g, hold=0.0) == 0.9
    assert spike._gap_after(down, g, hold=0.3) == 0.2 + 0.3   # down_to_up + hold
    assert spike._gap_after(up, g, hold=0.0) == 0.0
    assert spike._gap_after(pdown, g, hold=0.3) == 0.1        # primer internal (no hold)
    assert spike._gap_after(pup, g, hold=0.0) == 0.5          # primer -> target
    drag = spike.EventSpec("dragged", (0.0, 0.0), 1)
    assert spike._gap_after(drag, g, hold=0.3) == 0.0         # no inter-step sleep


def test_post_one_posts_through_port_with_correct_points():
    posts = []
    class _P:
        def make_event(self, kind, cc, win):
            return __import__("types").SimpleNamespace(kind=kind, cc=cc, win=win)
        def set_public_field(self, *a): pass
        def set_private_field(self, *a): pass
        def set_window_location(self, ev, pt): ev.wl = pt
        def set_location(self, ev, pt): ev.sl = pt
        def set_source_user_data(self, *a): pass
        def post(self, pid, ev): posts.append((pid, ev.kind, ev.wl, ev.sl))
    rec = _winrec(w=800, h=600)
    # a non-primer event: win-local from spec.point, screen = content_origin + win-local
    spike._post_one(_P(), 1, 77, rec, 0, spike.EventSpec("down", (10.0, 20.0), 1))
    assert posts[-1] == (1, "down", (10.0, 20.0), (10.0, 20.0))
    # a primer event posts off-window at OFF_WINDOW_POINT for both
    spike._post_one(_P(), 1, 77, rec, 0, spike.EventSpec("down", (5.0, 5.0), 1, primer=True))
    assert posts[-1] == (1, "down", spike.OFF_WINDOW_POINT, spike.OFF_WINDOW_POINT)


def test_deliver_specs_orders_focus_then_posts_then_restore_and_pays_timing():
    log = []
    sleeps = []
    class _P:
        def make_event(self, kind, cc, win): return __import__("types").SimpleNamespace(kind=kind)
        def set_public_field(self, *a): pass
        def set_private_field(self, *a): pass
        def set_window_location(self, *a): pass
        def set_location(self, *a): pass
        def set_source_user_data(self, *a): pass
        def post(self, pid, ev): log.append(("post", ev.kind))
    class _Nop:
        def start(self): pass
        def stop(self): return {"inconclusive": True}
    def fake_apply(wid):
        log.append(("focus", wid))
        return {"prev_psn": b"p", "prev_window_id": 5, "target_psn": b"t",
                "target_window_id": wid}
    def fake_restore(ctx): log.append(("restore", ctx["target_window_id"]))
    opts = spike.parse_sl_args(["1", "2", "--focus", "--restore-focus", "--timing", "zero"])
    spike._deliver_specs(1, 77, _winrec(), 0,
                         spike.click_event_specs((10.0, 20.0), primer=False),
                         opts, port=_P(), sleep=lambda s: sleeps.append(s),
                         apply_focus=fake_apply, restore_focus=fake_restore,
                         make_sampler=lambda: _Nop())
    assert log[0] == ("focus", 77)
    assert [k for (t, k) in log if t == "post"] == ["move", "down", "up"]
    assert log[-1] == ("restore", 77)
    assert len(sleeps) == 3   # one gap per posted event


def test_deliver_specs_preflight_refusal_is_inconclusive(monkeypatch):
    monkeypatch.setattr(spike.kb, "preflight_post_access", lambda: False)
    opts = spike.parse_sl_args(["1", "2"])
    out = spike._deliver_specs(1, 77, _winrec(), 0,
                               spike.click_event_specs((1.0, 1.0), primer=False), opts)
    assert out == {"inconclusive": True}


def test_resolve_psns_assembles_and_surfaces_status_errors():
    out = spike._resolve_psns(
        77, main_cid_fn=lambda: 1, owner_fn=lambda cid, wid: (0, 99),
        psn_fn=lambda owner: (0, b"\x01\x00\x00\x00\x02\x00\x00\x00"),
        front_psn_fn=lambda: b"\xaa" * 8, front_pid_fn=lambda: 4321)
    assert out == (b"\x01\x00\x00\x00\x02\x00\x00\x00", b"\xaa" * 8, 4321)
    import pytest as _pytest
    # non-zero owner status raises...
    with _pytest.raises(RuntimeError):
        spike._resolve_psns(77, main_cid_fn=lambda: 1, owner_fn=lambda c, w: (-1, 0),
                            psn_fn=lambda o: (0, b""), front_psn_fn=lambda: b"",
                            front_pid_fn=lambda: 1)
    # ...and so does a non-zero connection-PSN status (the second branch)
    with _pytest.raises(RuntimeError):
        spike._resolve_psns(77, main_cid_fn=lambda: 1, owner_fn=lambda c, w: (0, 9),
                            psn_fn=lambda o: (-2, b""), front_psn_fn=lambda: b"",
                            front_pid_fn=lambda: 1)


def test_apply_and_restore_focus_post_the_right_records():
    # record (psn, mode_byte, embedded_window_id) for each focus post.
    posts = []

    def rec_post(psn, rec):
        posts.append((psn, rec[0x8A], int.from_bytes(rec[0x3C:0x40], "little")))

    ctx = spike._apply_focus(
        77, resolve_psns_fn=lambda: (b"TGT", b"PREV", 4321),
        front_window_fn=lambda pid: 5, sky_post=rec_post, sleep=lambda s: None)
    # apply: defocus prev (mode 2) then focus target (mode 1); BOTH carry the TARGET
    # window id (77) -- cua reuses the one target-wid record (spec 2.2).
    assert posts == [(b"PREV", 0x02, 77), (b"TGT", 0x01, 77)]
    assert ctx["prev_window_id"] == 5 and ctx["target_window_id"] == 77
    posts.clear()
    spike._restore_focus(ctx, sky_post=rec_post)
    # restore inverse pair: defocus target (mode 2, target wid 77) then focus prev
    # (mode 1, with the PRIOR window id 5).
    assert posts == [(b"TGT", 0x02, 77), (b"PREV", 0x01, 5)]


def test_apply_focus_rolls_back_prev_defocus_on_target_focus_failure():
    posts = []
    calls = {"n": 0}

    def sky_post(psn, rec):
        calls["n"] += 1
        posts.append((psn, rec[0x8A], int.from_bytes(rec[0x3C:0x40], "little")))
        if calls["n"] == 2:   # the target-focus post fails
            raise RuntimeError("focus boom")

    import pytest as _pytest
    with _pytest.raises(RuntimeError):
        spike._apply_focus(77, resolve_psns_fn=lambda: (b"TGT", b"PREV", 4321),
                           front_window_fn=lambda pid: 5, sky_post=sky_post,
                           sleep=lambda s: None)
    # defocus prev (77/m2), focus target (raises), then ROLLBACK re-focus prev (5/m1)
    assert posts == [(b"PREV", 0x02, 77), (b"TGT", 0x01, 77), (b"PREV", 0x01, 5)]


def test_deliver_specs_restores_focus_and_surfaces_error_on_post_failure():
    log = []

    class _BoomPort:
        def make_event(self, *a): return __import__("types").SimpleNamespace(kind="x")
        def set_public_field(self, *a): pass
        def set_private_field(self, *a): pass
        def set_window_location(self, *a): pass
        def set_location(self, *a): pass
        def set_source_user_data(self, *a): pass
        def post(self, pid, ev): raise RuntimeError("post boom")

    class _Nop:
        def start(self): pass
        def stop(self): return {"inconclusive": False}

    def fake_apply(wid):
        log.append("focus")
        return {"prev_psn": b"p", "prev_window_id": 5, "target_psn": b"t",
                "target_window_id": wid}

    def fake_restore(ctx): log.append("restore")

    opts = spike.parse_sl_args(["1", "2", "--focus", "--restore-focus", "--timing", "zero"])
    out = spike._deliver_specs(1, 77, _winrec(), 0,
                               spike.click_event_specs((1.0, 1.0), primer=False), opts,
                               port=_BoomPort(), sleep=lambda s: None,
                               apply_focus=fake_apply, restore_focus=fake_restore,
                               make_sampler=lambda: _Nop())
    # never raised through; surfaced the error + marked inconclusive; restored focus
    # despite the mid-delivery failure.
    assert out["inconclusive"] is True and "post boom" in out["error"]
    assert log == ["focus", "restore"]


def test_front_window_id_picks_owner_window():
    wins = [{"kCGWindowOwnerPID": 9, "kCGWindowNumber": 111},
            {"kCGWindowOwnerPID": 4321, "kCGWindowNumber": 222},
            {"kCGWindowOwnerPID": 4321, "kCGWindowNumber": 333}]
    assert spike._front_window_id(4321, window_list_fn=lambda: wins) == 222
    assert spike._front_window_id(7, window_list_fn=lambda: wins) is None
