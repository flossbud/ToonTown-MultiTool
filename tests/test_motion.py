"""Tests for utils/motion.py — tokens and the is_reduced() gate."""

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEasingCurve

import utils.motion as motion


class _StubSettings:
    def __init__(self, **kv):
        self._kv = dict(kv)
    def get(self, key, default=None):
        return self._kv.get(key, default)
    def set(self, key, value):
        self._kv[key] = value


@pytest.fixture(autouse=True)
def reset_motion_state(monkeypatch):
    """Each test gets a fresh stub settings + cleared OS cache."""
    stub = _StubSettings()
    monkeypatch.setattr(motion, "_settings", stub)
    monkeypatch.setattr(motion, "_OS_REDUCED_MOTION_CACHE", None)
    return stub


def test_durations_are_in_micro_interaction_band():
    """Per UX 'duration-timing' rule: 150-300ms for micro-interactions."""
    assert 50 <= motion.DURATION_PRESS <= 150
    assert 150 <= motion.DURATION_HOVER <= 300
    assert 150 <= motion.DURATION_MENU <= 300
    assert 100 <= motion.DURATION_MENU_X < motion.DURATION_MENU
    assert 150 <= motion.DURATION_PILL <= 300
    assert 200 <= motion.DURATION_PAGE <= 400


def test_press_scale_in_recommended_band():
    """Per UX 'scale-feedback' rule: 0.95-1.05 band."""
    assert 0.95 <= motion.PRESS_SCALE <= 1.05


def test_ease_overshoot_returns_outback_with_set_overshoot():
    curve = motion.ease_overshoot(0.10)
    assert curve.type() == QEasingCurve.OutBack
    # Qt clamps overshoot internally; verify we set it.
    assert abs(curve.overshoot() - 0.10) < 1e-6


def test_is_reduced_returns_false_when_unset_and_os_says_no(monkeypatch, reset_motion_state):
    monkeypatch.setattr(motion, "_os_reduced_motion", lambda: False)
    assert motion.is_reduced() is False


def test_is_reduced_returns_true_when_os_says_yes_and_user_unset(monkeypatch, reset_motion_state):
    monkeypatch.setattr(motion, "_os_reduced_motion", lambda: True)
    assert motion.is_reduced() is True


def test_explicit_user_override_wins_when_true(monkeypatch, reset_motion_state):
    """User explicitly set reduce_motion=True overrides any OS state."""
    reset_motion_state.set("reduce_motion_set_explicitly", True)
    reset_motion_state.set("reduce_motion", True)
    monkeypatch.setattr(motion, "_os_reduced_motion", lambda: False)
    assert motion.is_reduced() is True


def test_explicit_user_override_wins_when_false(monkeypatch, reset_motion_state):
    """User explicitly set reduce_motion=False overrides OS-says-reduced."""
    reset_motion_state.set("reduce_motion_set_explicitly", True)
    reset_motion_state.set("reduce_motion", False)
    monkeypatch.setattr(motion, "_os_reduced_motion", lambda: True)
    assert motion.is_reduced() is False


def test_refresh_cache_clears_os_cache(monkeypatch, reset_motion_state):
    """After _refresh_cache, the next _os_reduced_motion call must re-run."""
    calls = {"n": 0}
    def fake_os():
        calls["n"] += 1
        return False
    monkeypatch.setattr(motion, "_os_reduced_motion_impl", fake_os)
    motion._OS_REDUCED_MOTION_CACHE = None
    motion._os_reduced_motion()
    motion._os_reduced_motion()  # cached
    assert calls["n"] == 1
    motion._refresh_cache()
    motion._os_reduced_motion()
    assert calls["n"] == 2
