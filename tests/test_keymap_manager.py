"""Unit tests for KeymapManager."""

import threading
import time

import pytest

from utils.keymap_manager import KeymapManager, DEFAULT_SETS, DIRECTIONS


def _make_manager():
    """Create a KeymapManager without touching disk or the real config."""
    mgr = object.__new__(KeymapManager)
    mgr._lock = threading.Lock()
    mgr._listeners = []
    mgr._sets = [dict(s) for s in DEFAULT_SETS]
    mgr._path = "/dev/null"
    return mgr


# ── get_direction_in_set ──────────────────────────────────────────────────


class TestGetDirectionInSet:
    def test_returns_correct_direction_set0(self):
        mgr = _make_manager()
        assert mgr.get_direction_in_set(0, "w") == "up"
        assert mgr.get_direction_in_set(0, "a") == "left"
        assert mgr.get_direction_in_set(0, "s") == "down"
        assert mgr.get_direction_in_set(0, "d") == "right"
        assert mgr.get_direction_in_set(0, "space") == "jump"

    def test_returns_correct_direction_set1(self):
        mgr = _make_manager()
        assert mgr.get_direction_in_set(1, "Up") == "up"
        assert mgr.get_direction_in_set(1, "Left") == "left"
        assert mgr.get_direction_in_set(1, "Down") == "down"
        assert mgr.get_direction_in_set(1, "Right") == "right"
        assert mgr.get_direction_in_set(1, "Control_L") == "jump"

    def test_returns_none_for_unknown_key(self):
        mgr = _make_manager()
        assert mgr.get_direction_in_set(0, "nonexistent") is None

    def test_returns_none_for_out_of_range_set(self):
        mgr = _make_manager()
        assert mgr.get_direction_in_set(99, "w") is None
        assert mgr.get_direction_in_set(-1, "w") is None


# ── get_key_for_direction ─────────────────────────────────────────────────


class TestGetKeyForDirection:
    def test_returns_correct_key(self):
        mgr = _make_manager()
        assert mgr.get_key_for_direction(0, "up") == "w"
        assert mgr.get_key_for_direction(1, "up") == "Up"
        assert mgr.get_key_for_direction(0, "jump") == "space"
        assert mgr.get_key_for_direction(1, "jump") == "Control_L"

    def test_returns_none_for_invalid_set_index(self):
        mgr = _make_manager()
        assert mgr.get_key_for_direction(99, "up") is None
        assert mgr.get_key_for_direction(-1, "up") is None

    def test_returns_none_for_missing_direction(self):
        mgr = _make_manager()
        assert mgr.get_key_for_direction(0, "nonexistent") is None


# ── on_change / _notify ──────────────────────────────────────────────────


class TestOnChangeNotify:
    def test_listener_called_on_notify(self):
        mgr = _make_manager()
        calls = []
        mgr.on_change(lambda: calls.append(1))
        mgr._notify()
        assert calls == [1]

    def test_multiple_listeners_called(self):
        mgr = _make_manager()
        results = []
        mgr.on_change(lambda: results.append("a"))
        mgr.on_change(lambda: results.append("b"))
        mgr._notify()
        assert results == ["a", "b"]

    def test_listener_exception_does_not_break_others(self):
        mgr = _make_manager()
        results = []

        def bad():
            raise RuntimeError("boom")

        mgr.on_change(bad)
        mgr.on_change(lambda: results.append("ok"))
        mgr._notify()
        assert results == ["ok"]


# ── Thread safety ─────────────────────────────────────────────────────────


class TestThreadSafety:
    def test_register_listener_during_notify(self):
        """Registering a listener while _notify() is iterating must not crash."""
        mgr = _make_manager()
        barrier = threading.Barrier(2, timeout=5)

        def slow_listener():
            barrier.wait()  # sync with the registering thread
            time.sleep(0.01)

        mgr.on_change(slow_listener)

        errors = []

        def notify_thread():
            try:
                mgr._notify()
            except Exception as e:
                errors.append(e)

        def register_thread():
            try:
                barrier.wait()  # wait until slow_listener is running
                mgr.on_change(lambda: None)
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=notify_thread)
        t2 = threading.Thread(target=register_thread)
        t1.start()
        t2.start()
        t1.join(timeout=5)
        t2.join(timeout=5)

        assert errors == [], f"Thread safety error: {errors}"
