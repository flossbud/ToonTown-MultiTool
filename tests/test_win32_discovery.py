"""win32_discovery unit tests. Run cross-platform: the module lazy-imports
win32 APIs inside functions, so tests inject fakes into sys.modules."""
import sys
import types

import pytest

from utils import win32_discovery


class _FakeWin32gui(types.SimpleNamespace):
    pass


@pytest.fixture
def fake_gui(monkeypatch):
    fake = _FakeWin32gui()
    monkeypatch.setitem(sys.modules, "win32gui", fake)
    return fake


def test_get_window_geometry_client_area_screen_coords(fake_gui):
    calls = {}

    def get_client_rect(h):
        calls["rect_hwnd"] = h
        return (0, 0, 958, 1008)

    def client_to_screen(h, pt):
        calls["cts"] = (h, pt)
        return (961, 31)

    fake_gui.GetClientRect = get_client_rect
    fake_gui.ClientToScreen = client_to_screen
    assert win32_discovery.get_window_geometry("7407592") == (961, 31, 958, 1008)
    assert calls["rect_hwnd"] == 7407592          # wid parsed to int hwnd
    assert calls["cts"] == (7407592, (0, 0))      # client origin as ONE tuple


def test_get_window_geometry_failure_returns_none(fake_gui):
    def boom(h):
        raise OSError("dead hwnd")
    fake_gui.GetClientRect = boom
    assert win32_discovery.get_window_geometry("123") is None
    assert win32_discovery.get_window_geometry("not-a-number") is None


def test_toplevel_at_point_returns_root_ancestor(fake_gui, monkeypatch):
    seen = {}

    def window_from_point(pt):
        seen["pt"] = pt
        return 0x501  # deepest child

    fake_gui.WindowFromPoint = window_from_point
    monkeypatch.setattr(win32_discovery, "_get_ancestor_root",
                        lambda hwnd: 0x700)
    assert win32_discovery.toplevel_at_point(500, 250) == str(0x700)
    assert seen["pt"] == (500, 250)               # single POINT tuple


def test_toplevel_at_point_clean_miss_is_empty_string(fake_gui):
    fake_gui.WindowFromPoint = lambda pt: 0
    assert win32_discovery.toplevel_at_point(5000, 5000) == ""


def test_toplevel_at_point_failure_is_none(fake_gui):
    def boom(pt):
        raise OSError("no desktop")
    fake_gui.WindowFromPoint = boom
    assert win32_discovery.toplevel_at_point(1, 1) is None


def test_toplevel_at_point_zero_ancestor_falls_back_to_hit(fake_gui, monkeypatch):
    fake_gui.WindowFromPoint = lambda pt: 0x501
    monkeypatch.setattr(win32_discovery, "_get_ancestor_root", lambda hwnd: 0)
    assert win32_discovery.toplevel_at_point(1, 1) == str(0x501)
