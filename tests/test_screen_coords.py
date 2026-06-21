# tests/test_screen_coords.py
import sys
import pytest
from utils.screen_coords import native_to_logical, emitted_to_logical


class _FakeScreen:
    def __init__(self, x, y, w, h, dpr):
        self._g = (x, y, w, h)
        self._dpr = dpr

    def geometry(self):
        class _G:
            def __init__(s, t): s._t = t
            def x(s): return s._t[0]
            def y(s): return s._t[1]
            def width(s): return s._t[2]
            def height(s): return s._t[3]
        return _G(self._g)

    def devicePixelRatio(self):
        return self._dpr


def test_native_to_logical_identity_at_dpr_1():
    screens = [_FakeScreen(0, 0, 1920, 1080, 1.0)]
    assert native_to_logical(800, 600, screens) == (800, 600)


def test_native_to_logical_scales_around_screen_origin():
    screens = [_FakeScreen(0, 0, 1280, 800, 1.5)]
    # (970, 35) / 1.5 around origin (0,0) -> (647, 23)
    assert native_to_logical(970, 35, screens) == (647, 23)


def test_native_to_logical_empty_is_identity():
    assert native_to_logical(800, 600, []) == (800, 600)


def test_emitted_to_logical_darwin_is_identity(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    # No screens needed: darwin path returns the point unchanged.
    assert emitted_to_logical(123, 456) == (123, 456)


def test_emitted_to_logical_non_darwin_delegates(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    screens = [_FakeScreen(0, 0, 1280, 800, 2.0)]
    assert emitted_to_logical(800, 600, screens) == (400, 300)
