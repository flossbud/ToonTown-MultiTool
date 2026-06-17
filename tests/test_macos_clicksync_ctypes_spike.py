import importlib.util
import pathlib

import pytest

_PATH = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "macos_clicksync_ctypes_spike.py"
_spec = importlib.util.spec_from_file_location("cs_spike", _PATH)
cs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cs)


def test_decode_csflags_platform_and_runtime():
    # CS_PLATFORM_BINARY=0x04000000, CS_RUNTIME=0x00010000
    assert cs.decode_csflags(0x04000000) == {"platform_binary": True, "runtime": False}
    assert cs.decode_csflags(0x00010000) == {"platform_binary": False, "runtime": True}
    assert cs.decode_csflags(0x04010000) == {"platform_binary": True, "runtime": True}
    assert cs.decode_csflags(0) == {"platform_binary": False, "runtime": False}


def test_parser_inject_requires_coords():
    with pytest.raises(SystemExit):
        cs.build_parser().parse_args(["inject", "--pid", "1"])  # missing required coords


def test_parser_inject_full():
    ns = cs.build_parser().parse_args([
        "inject", "--pid", "42", "--wid", "7", "--win-x", "10", "--win-y", "20",
        "--screen-x", "100", "--screen-y", "200", "--kind", "hover"])
    assert (ns.pid, ns.wid, ns.kind) == (42, 7, "hover")
    assert (ns.win_x, ns.win_y, ns.screen_x, ns.screen_y) == (10.0, 20.0, 100.0, 200.0)


def test_objc_selector_signatures_table():
    sigs = cs.OBJC_SELECTOR_SIGS
    name = ("mouseEventWithType:location:modifierFlags:timestamp:windowNumber:"
            "context:eventNumber:clickCount:pressure:")
    assert name in sigs
    assert "CGEvent" in sigs
    for sel, (restype, argtypes) in sigs.items():
        assert isinstance(argtypes, tuple)
    # the mouse-event selector takes its 9 explicit args (after id self, SEL op)
    assert len(sigs[name][1]) == 9
    # CGEvent takes no explicit args
    assert len(sigs["CGEvent"][1]) == 0


def test_window_point_from_fraction():
    # bounds = (x, y, w, h); fraction -> screen point + window-local point
    scr, win = cs.point_from_fraction(bounds=(100.0, 200.0, 640.0, 480.0), fx=0.5, fy=0.25)
    assert scr == (100.0 + 320.0, 200.0 + 120.0)
    assert win == (320.0, 120.0)


def test_source_user_data_and_cgevent_types_pinned():
    # ABI constants confirmed against live Quartz on macOS 26 (kCGEventSourceUserData=42)
    assert cs._SOURCE_USER_DATA_FIELD == 42
    assert cs.CGEVENT_TYPE == {"move": 5, "down": 1, "up": 2, "dragged": 6}
