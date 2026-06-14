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
