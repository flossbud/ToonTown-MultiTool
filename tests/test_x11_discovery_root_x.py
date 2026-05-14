"""Regression test for get_window_root_x: it must return the window's
real (positive) root-space X, not the negated value the swapped
translate_coords arguments produced."""

import types
import pytest

import utils.x11_discovery as x11


class _FakeCoordObj:
    """Models an X11 window/root with a known top-left offset in root space."""

    def __init__(self, off_x, off_y):
        self._off_x = off_x
        self._off_y = off_y

    def translate_coords(self, src, src_x, src_y):
        # X11 TranslateCoordinates: translate (src_x, src_y) from `src`'s
        # space into `self`'s space. Absolute root point = src.offset + src_xy;
        # expressed in self's space = that minus self's offset.
        abs_x = src._off_x + src_x
        abs_y = src._off_y + src_y
        return types.SimpleNamespace(x=abs_x - self._off_x, y=abs_y - self._off_y)


class _FakeScreen:
    def __init__(self, root):
        self.root = root


class _FakeDisplay:
    def __init__(self, window, root):
        self._window = window
        self._root = root

    def create_resource_object(self, kind, wid):
        assert kind == "window"
        return self._window

    def screen(self):
        return _FakeScreen(self._root)

    def close(self):
        pass


def test_get_window_root_x_returns_positive_root_space_x(monkeypatch):
    # Root is at (0, 0); the window is at root position (250, 80).
    root = _FakeCoordObj(0, 0)
    window = _FakeCoordObj(250, 80)
    monkeypatch.setattr(x11, "_open_display", lambda: _FakeDisplay(window, root))

    # Must return the window's real root X (+250), NOT the negated -250.
    assert x11.get_window_root_x("12345") == 250


def test_get_window_root_x_orders_left_before_right(monkeypatch):
    root = _FakeCoordObj(0, 0)
    left_window = _FakeCoordObj(100, 0)
    right_window = _FakeCoordObj(900, 0)

    monkeypatch.setattr(x11, "_open_display", lambda: _FakeDisplay(left_window, root))
    left_x = x11.get_window_root_x("1")
    monkeypatch.setattr(x11, "_open_display", lambda: _FakeDisplay(right_window, root))
    right_x = x11.get_window_root_x("2")

    # Ascending sort on these must put the left window first.
    assert left_x < right_x
    assert sorted([("right", right_x), ("left", left_x)], key=lambda i: i[1])[0][0] == "left"
