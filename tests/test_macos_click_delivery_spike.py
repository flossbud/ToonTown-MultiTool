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
