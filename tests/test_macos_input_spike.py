import collections
import dataclasses
import importlib.util
import pathlib
import sys

import pytest

_SPIKE = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "macos_input_spike.py"
_spec = importlib.util.spec_from_file_location("macos_input_spike", _SPIKE)
spike = importlib.util.module_from_spec(_spec)
# Register before exec so the frozen dataclass's annotation resolution can find
# the module namespace (dataclasses looks up sys.modules[cls.__module__]).
sys.modules[_spec.name] = spike
_spec.loader.exec_module(spike)


# ── Task 2: module imports cleanly without PyObjC ────────────────────────────
def test_module_imports_without_pyobjc():
    # The module must import on any platform: PyObjC is imported lazily, never
    # at module top level, so the pure-logic helpers are testable on Linux CI.
    assert hasattr(spike, "main")
    assert callable(spike.main)


# ── Task 3: keycode map ──────────────────────────────────────────────────────
def test_vk_for_key_movement_and_specials():
    assert spike.vk_for_key("w") == 0x0D
    assert spike.vk_for_key("a") == 0x00
    assert spike.vk_for_key("s") == 0x01
    assert spike.vk_for_key("d") == 0x02
    assert spike.vk_for_key("up") == 0x7E
    assert spike.vk_for_key("down") == 0x7D
    assert spike.vk_for_key("left") == 0x7B
    assert spike.vk_for_key("right") == 0x7C
    assert spike.vk_for_key("return") == 0x24
    assert spike.vk_for_key("escape") == 0x35
    assert spike.vk_for_key("delete") == 0x33
    assert spike.vk_for_key("space") == 0x31


def test_vk_for_key_is_case_insensitive():
    assert spike.vk_for_key("W") == spike.vk_for_key("w")


def test_vk_for_key_unknown_raises():
    with pytest.raises(KeyError):
        spike.vk_for_key("f24-nonexistent")


# ── Task 4: TTR window identification ────────────────────────────────────────
def _win(pid, num, name, x=0, y=0, w=800, h=600, title=None):
    d = {
        "kCGWindowOwnerPID": pid,
        "kCGWindowNumber": num,
        "kCGWindowOwnerName": name,
        "kCGWindowBounds": {"X": x, "Y": y, "Width": w, "Height": h},
    }
    if title is not None:
        d["kCGWindowName"] = title
    return d


def test_identify_ttr_windows_matches_owner_name():
    info = [
        _win(101, 11, "Toontown Rewritten", w=800, h=600),
        _win(202, 22, "Finder"),
        _win(101, 12, "Toontown Rewritten", w=640, h=480, title="TTR"),
    ]
    recs = spike.identify_ttr_windows(info)
    assert [(r.pid, r.window_id) for r in recs] == [(101, 11), (101, 12)]
    assert recs[0].bounds == (0, 0, 800, 600)
    assert recs[0].owner == "Toontown Rewritten"


def test_identify_ttr_windows_ignores_zero_size_and_missing_fields():
    info = [
        _win(101, 11, "Toontown Rewritten", w=0, h=0),   # zero-size: skip
        {"kCGWindowOwnerName": "Toontown Rewritten"},     # no pid/number: skip
    ]
    assert spike.identify_ttr_windows(info) == []


def test_identify_ttr_windows_records_are_immutable():
    rec = spike.identify_ttr_windows([_win(101, 11, "Toontown Rewritten")])[0]
    with pytest.raises(dataclasses.FrozenInstanceError):
        rec.pid = 999


# ── Task 5: pynput callback compat shim ──────────────────────────────────────
def test_call_pynput_handler_one_arg_version():
    seen = []
    cb = spike.call_pynput_handler(lambda key, injected: seen.append((key, injected)))
    cb("KEY")                      # pynput 1.7 style
    assert seen == [("KEY", False)]


def test_call_pynput_handler_two_arg_version():
    seen = []
    cb = spike.call_pynput_handler(lambda key, injected: seen.append((key, injected)))
    cb("KEY", True)               # pynput 1.8 style
    assert seen == [("KEY", True)]


# ── Task 6: echo-guard tag predicate ─────────────────────────────────────────
def test_is_spike_event_matches_tag():
    assert spike.is_spike_event(spike.SPIKE_EVENT_TAG) is True


def test_is_spike_event_rejects_other_values():
    assert spike.is_spike_event(0) is False
    assert spike.is_spike_event(12345) is False


# ── Task 7: port -> PID -> window resolver ───────────────────────────────────
_Conn = collections.namedtuple("_Conn", "pid laddr status")
_Addr = collections.namedtuple("_Addr", "ip port")


def test_resolve_port_pid_window_maps_ttr_ports():
    windows = [
        spike.WindowRecord(pid=101, window_id=11, owner="Toontown Rewritten", bounds=(0, 0, 800, 600)),
        spike.WindowRecord(pid=202, window_id=22, owner="Toontown Rewritten", bounds=(0, 0, 800, 600)),
    ]
    conns = [
        _Conn(pid=101, laddr=_Addr("127.0.0.1", 7000), status="LISTEN"),
        _Conn(pid=202, laddr=_Addr("::1", 7001), status="LISTEN"),
        _Conn(pid=999, laddr=_Addr("127.0.0.1", 8080), status="LISTEN"),  # not TTR
        _Conn(pid=101, laddr=_Addr("127.0.0.1", 5555), status="ESTABLISHED"),  # not listening
    ]
    mapping = spike.resolve_port_pid_window(conns, windows)
    assert mapping == {7000: (101, 11), 7001: (202, 22)}


def test_resolve_port_pid_window_ignores_no_laddr():
    windows = [spike.WindowRecord(pid=101, window_id=11, owner="Toontown Rewritten", bounds=(0, 0, 1, 1))]
    conns = [_Conn(pid=101, laddr=(), status="LISTEN")]
    assert spike.resolve_port_pid_window(conns, windows) == {}


def test_resolve_port_pid_window_excludes_non_loopback():
    windows = [spike.WindowRecord(pid=101, window_id=11, owner="Toontown Rewritten", bounds=(0, 0, 1, 1))]
    conns = [
        _Conn(pid=101, laddr=_Addr("0.0.0.0", 7000), status="LISTEN"),     # wildcard: excluded
        _Conn(pid=101, laddr=_Addr("192.168.1.5", 7001), status="LISTEN"), # LAN: excluded
        _Conn(pid=101, laddr=_Addr("127.0.0.1", 7002), status="LISTEN"),   # loopback: kept
    ]
    assert spike.resolve_port_pid_window(conns, windows) == {7002: (101, 11)}
