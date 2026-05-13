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


def test_settings_change_callback_refreshes_cache(monkeypatch, reset_motion_state):
    """When the user toggles reduce_motion in Settings, the OS cache must
    be invalidated so the next is_reduced() reflects the new value."""
    calls = {"refresh": 0}
    real_refresh = motion._refresh_cache
    def spy():
        calls["refresh"] += 1
        real_refresh()
    monkeypatch.setattr(motion, "_refresh_cache", spy)

    motion.on_settings_change("reduce_motion", True)
    assert calls["refresh"] == 1

    # Unrelated key should not trigger a refresh
    motion.on_settings_change("theme", "dark")
    assert calls["refresh"] == 1


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


# ── push_slide_pages tests ───────────────────────────────────────────────────

from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QApplication, QLabel, QStackedWidget, QWidget


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    return app


@pytest.fixture
def stack(qapp):
    s = QStackedWidget()
    s.resize(400, 300)
    for i in range(3):
        p = QWidget()
        p.setObjectName(f"page_{i}")
        s.addWidget(p)
    s.show()
    qapp.processEvents()
    return s


def test_push_slide_pages_reduced_motion_snaps(monkeypatch, stack, reset_motion_state):
    reset_motion_state.set("reduce_motion_set_explicitly", True)
    reset_motion_state.set("reduce_motion", True)

    result = motion.push_slide_pages(stack, 0, 2, axis="h")

    assert result is None
    assert stack.currentIndex() == 2
    # No proxy labels should have been created.
    proxies = [c for c in stack.children() if isinstance(c, QLabel)
               and c.property("is_transition_proxy")]
    assert proxies == []


def test_push_slide_pages_animation_completes(monkeypatch, qapp, stack, reset_motion_state):
    """With duration scale 0, animation finishes within one event-loop tick."""
    monkeypatch.setattr(motion, "_os_reduced_motion", lambda: False)
    monkeypatch.setattr(motion, "_TEST_DURATION_SCALE", 0.0)

    group = motion.push_slide_pages(stack, 0, 1, axis="h")
    assert group is not None

    # Drive event loop until finished
    finished = {"v": False}
    group.finished.connect(lambda: finished.update(v=True))
    for _ in range(50):
        qapp.processEvents()
        if finished["v"]:
            break

    assert finished["v"] is True
    assert stack.currentIndex() == 1
    # Proxy labels cleaned up
    proxies = [c for c in stack.children() if isinstance(c, QLabel)
               and c.property("is_transition_proxy")]
    # Proxies may exist briefly post-finish until deleteLater() processes.
    qapp.processEvents()
    proxies = [c for c in stack.children() if isinstance(c, QLabel)
               and c.property("is_transition_proxy") and not c.isHidden()]
    assert proxies == []


def test_push_slide_pages_interrupt(monkeypatch, qapp, stack, reset_motion_state):
    """Calling push_slide_pages mid-animation cancels the in-flight one."""
    monkeypatch.setattr(motion, "_os_reduced_motion", lambda: False)
    monkeypatch.setattr(motion, "_TEST_DURATION_SCALE", 0.0)

    g1 = motion.push_slide_pages(stack, 0, 1, axis="h")
    g2 = motion.push_slide_pages(stack, 0, 2, axis="h")

    # First group must be stopped; second must own the in-flight slot.
    from PySide6.QtCore import QAbstractAnimation
    assert g1.state() == QAbstractAnimation.Stopped
    assert getattr(stack, "_in_flight_anim", None) is g2 or g2 is None

    # Eventually settles on the latest target.
    finished = {"v": False}
    if g2 is not None:
        g2.finished.connect(lambda: finished.update(v=True))
        for _ in range(50):
            qapp.processEvents()
            if finished["v"]:
                break
    assert stack.currentIndex() == 2


def test_push_slide_pages_vertical_axis(monkeypatch, qapp, stack, reset_motion_state):
    """axis='v' creates a vertical animation. We assert end state, not motion."""
    monkeypatch.setattr(motion, "_os_reduced_motion", lambda: False)
    monkeypatch.setattr(motion, "_TEST_DURATION_SCALE", 0.0)

    group = motion.push_slide_pages(stack, 0, 2, axis="v")
    finished = {"v": False}
    group.finished.connect(lambda: finished.update(v=True))
    for _ in range(50):
        qapp.processEvents()
        if finished["v"]:
            break
    assert stack.currentIndex() == 2


# ── press_scale / morph_icon_size tests ─────────────────────────────────────

from PySide6.QtCore import QSize
from PySide6.QtWidgets import QToolButton


def test_press_scale_shrinks_icon_size(qapp, monkeypatch, reset_motion_state):
    monkeypatch.setattr(motion, "_os_reduced_motion", lambda: False)
    monkeypatch.setattr(motion, "_TEST_DURATION_SCALE", 0.0)

    btn = QToolButton()
    btn.setIconSize(QSize(22, 22))

    anim = motion.press_scale(btn, depressed=True)
    assert anim is not None
    for _ in range(50):
        qapp.processEvents()
        from PySide6.QtCore import QAbstractAnimation
        if anim.state() == QAbstractAnimation.Stopped:
            break
    # Target = round(22 * 0.96) = 21
    assert btn.iconSize() == QSize(21, 21)


def test_press_scale_restores_on_release(qapp, monkeypatch, reset_motion_state):
    monkeypatch.setattr(motion, "_os_reduced_motion", lambda: False)
    monkeypatch.setattr(motion, "_TEST_DURATION_SCALE", 0.0)

    btn = QToolButton()
    btn.setIconSize(QSize(22, 22))
    btn.setProperty("press_baseline_icon_size", 22)

    motion.press_scale(btn, depressed=True)
    qapp.processEvents()
    motion.press_scale(btn, depressed=False)
    qapp.processEvents()

    assert btn.iconSize() == QSize(22, 22)


def test_press_scale_reduced_motion_snaps(qapp, monkeypatch, reset_motion_state):
    monkeypatch.setattr(motion, "_os_reduced_motion", lambda: True)
    btn = QToolButton()
    btn.setIconSize(QSize(22, 22))

    result = motion.press_scale(btn, depressed=True)

    assert result is None
    # Snap to depressed value
    assert btn.iconSize() == QSize(21, 21)


def test_press_scale_baseline_refreshes_per_press(qapp, monkeypatch, reset_motion_state):
    """If the chip's icon size changes between press cycles (e.g., via
    nav-select toggling selected→unselected), the next press should target
    a baseline derived from the CURRENT iconSize, not a cached one."""
    monkeypatch.setattr(motion, "_os_reduced_motion", lambda: False)
    monkeypatch.setattr(motion, "_TEST_DURATION_SCALE", 0.0)

    btn = QToolButton()
    btn.setIconSize(QSize(22, 22))
    # First press-release cycle establishes baseline=22.
    motion.press_scale(btn, depressed=True)
    qapp.processEvents()
    motion.press_scale(btn, depressed=False)
    qapp.processEvents()
    assert btn.iconSize() == QSize(22, 22)

    # Simulate the chip being deselected externally (e.g., by nav_select):
    btn.setIconSize(QSize(20, 20))

    # Press again — baseline should refresh to 20, target = round(20*0.96) = 19.
    motion.press_scale(btn, depressed=True)
    qapp.processEvents()
    assert btn.iconSize() == QSize(19, 19)

    # Release — should restore to 20, not 22.
    motion.press_scale(btn, depressed=False)
    qapp.processEvents()
    assert btn.iconSize() == QSize(20, 20)


def test_morph_icon_size_animates_to_target(qapp, monkeypatch, reset_motion_state):
    monkeypatch.setattr(motion, "_os_reduced_motion", lambda: False)
    monkeypatch.setattr(motion, "_TEST_DURATION_SCALE", 0.0)

    btn = QToolButton()
    btn.setIconSize(QSize(20, 20))
    anim = motion.morph_icon_size(btn, 22)
    assert anim is not None
    for _ in range(50):
        qapp.processEvents()
        from PySide6.QtCore import QAbstractAnimation
        if anim.state() == QAbstractAnimation.Stopped:
            break
    assert btn.iconSize() == QSize(22, 22)


def test_pop_menu_enter_duration_matches_token(qapp, monkeypatch, reset_motion_state):
    monkeypatch.setattr(motion, "_os_reduced_motion", lambda: False)
    monkeypatch.setattr(motion, "_TEST_DURATION_SCALE", 1.0)

    from utils.widgets.overflow_popup import OverflowPopup
    pop = OverflowPopup()
    anchor = QToolButton()
    group = motion.pop_menu(pop, anchor, show=True)
    durations = [group.animationAt(i).duration() for i in range(group.animationCount())]
    assert all(d == motion.DURATION_MENU for d in durations)


def test_pop_menu_exit_shorter_than_enter(qapp, monkeypatch, reset_motion_state):
    monkeypatch.setattr(motion, "_os_reduced_motion", lambda: False)
    monkeypatch.setattr(motion, "_TEST_DURATION_SCALE", 1.0)

    from utils.widgets.overflow_popup import OverflowPopup
    pop = OverflowPopup()
    anchor = QToolButton()
    motion.pop_menu(pop, anchor, show=True)
    group = motion.pop_menu(pop, anchor, show=False)
    durations = [group.animationAt(i).duration() for i in range(group.animationCount())]
    assert all(d == motion.DURATION_MENU_X for d in durations)
    assert motion.DURATION_MENU_X < motion.DURATION_MENU


def test_pop_menu_reduced_motion_shows_instantly(qapp, monkeypatch, reset_motion_state):
    monkeypatch.setattr(motion, "_os_reduced_motion", lambda: True)
    from utils.widgets.overflow_popup import OverflowPopup
    pop = OverflowPopup()
    anchor = QToolButton()
    result = motion.pop_menu(pop, anchor, show=True)
    assert result is None
    assert pop.isVisible()
