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
