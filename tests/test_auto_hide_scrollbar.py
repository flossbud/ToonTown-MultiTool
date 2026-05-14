"""Tests for utils/widgets/auto_hide_scrollbar.py — modern scrollbar."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QScrollBar


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_construction_returns_qscrollbar_subclass(qapp):
    from utils.widgets.auto_hide_scrollbar import AutoHideScrollBar

    bar = AutoHideScrollBar()
    assert isinstance(bar, QScrollBar)
    bar.deleteLater()


def test_set_theme_dark_uses_white_alpha(qapp):
    from utils.widgets.auto_hide_scrollbar import AutoHideScrollBar

    bar = AutoHideScrollBar()
    bar.set_theme(is_dark=True)
    qss = bar.styleSheet()

    # Width spec: bar reserves 18px (12px gutter + 6px right margin so the
    # thumb sits clear of the window edge); thumb is 8px idle, 12px hover.
    # Vertical: 12px top/bottom margin so the bar doesn't run edge-to-edge.
    assert "QScrollBar:vertical" in qss
    assert "width: 18px" in qss
    assert "margin: 12px 6px 12px 0" in qss
    assert "min-width: 8px" in qss
    # Hover thumb expands to 12px.
    assert "QScrollBar::handle:vertical:hover" in qss
    # Dark mode: white-alpha colors.
    assert "rgba(255, 255, 255, 0.45)" in qss  # active
    assert "rgba(255, 255, 255, 0.70)" in qss  # hover
    # Track / arrows / pages all hidden.
    assert "QScrollBar::add-line:vertical" in qss
    assert "QScrollBar::sub-line:vertical" in qss
    assert "QScrollBar::add-page:vertical" in qss
    assert "QScrollBar::sub-page:vertical" in qss
    bar.deleteLater()


def test_set_theme_light_uses_dark_alpha(qapp):
    from utils.widgets.auto_hide_scrollbar import AutoHideScrollBar

    bar = AutoHideScrollBar()
    bar.set_theme(is_dark=False)
    qss = bar.styleSheet()

    assert "rgba(15, 23, 42, 0.30)" in qss   # active (dark thumb on light bg)
    assert "rgba(15, 23, 42, 0.55)" in qss   # hover
    # Make sure dark-mode colors are not present.
    assert "rgba(255, 255, 255, 0.45)" not in qss
    bar.deleteLater()


def test_set_theme_is_idempotent(qapp):
    from utils.widgets.auto_hide_scrollbar import AutoHideScrollBar

    bar = AutoHideScrollBar()
    bar.set_theme(is_dark=True)
    first = bar.styleSheet()
    bar.set_theme(is_dark=True)
    assert bar.styleSheet() == first
    bar.deleteLater()


def test_bar_starts_with_opacity_effect_at_zero(qapp):
    from PySide6.QtWidgets import QGraphicsOpacityEffect
    from utils.widgets.auto_hide_scrollbar import AutoHideScrollBar

    bar = AutoHideScrollBar()
    effect = bar.graphicsEffect()
    assert isinstance(effect, QGraphicsOpacityEffect)
    assert effect.opacity() == 0.0
    bar.deleteLater()


def test_wake_animates_opacity_to_one(qapp, qtbot, monkeypatch):
    """When wake() is called, opacity should land at 1.0 within the fade-in
    duration. Use class-constant override to make the animation instant."""
    from utils.widgets.auto_hide_scrollbar import AutoHideScrollBar
    import utils.motion as motion

    monkeypatch.setattr(AutoHideScrollBar, "_FADE_IN_MS", 1)
    monkeypatch.setattr(motion, "is_reduced", lambda: False)

    bar = AutoHideScrollBar()
    bar.setRange(0, 100)  # ensure scrollable
    bar.wake()

    qtbot.waitUntil(lambda: bar._opacity_effect.opacity() == 1.0, timeout=200)
    bar.deleteLater()


def test_wake_is_idempotent_at_full_opacity(qapp, monkeypatch):
    """A second wake() while already at 1.0 should not crash and should not
    restart the fade-in animation needlessly."""
    from utils.widgets.auto_hide_scrollbar import AutoHideScrollBar
    import utils.motion as motion

    monkeypatch.setattr(AutoHideScrollBar, "_FADE_IN_MS", 1)
    monkeypatch.setattr(motion, "is_reduced", lambda: False)

    bar = AutoHideScrollBar()
    bar.setRange(0, 100)
    bar._opacity_effect.setOpacity(1.0)  # pretend already faded in
    bar.wake()  # must not raise
    assert bar._opacity_effect.opacity() == 1.0
    bar.deleteLater()


def test_idle_timer_fades_back_to_zero(qapp, qtbot, monkeypatch):
    from utils.widgets.auto_hide_scrollbar import AutoHideScrollBar
    import utils.motion as motion

    monkeypatch.setattr(AutoHideScrollBar, "_FADE_IN_MS", 1)
    monkeypatch.setattr(AutoHideScrollBar, "_FADE_OUT_MS", 1)
    monkeypatch.setattr(AutoHideScrollBar, "_IDLE_TIMEOUT_MS", 50)
    monkeypatch.setattr(motion, "is_reduced", lambda: False)

    bar = AutoHideScrollBar()
    bar.setRange(0, 100)
    bar.wake()
    qtbot.waitUntil(lambda: bar._opacity_effect.opacity() == 1.0, timeout=200)

    # After idle timeout fires + fade-out, opacity returns to 0.
    qtbot.waitUntil(lambda: bar._opacity_effect.opacity() == 0.0, timeout=500)
    bar.deleteLater()


def test_wake_restarts_idle_timer(qapp, qtbot, monkeypatch):
    """A second wake() while we're waiting to fade-out should reset the timer
    so the bar stays visible."""
    from utils.widgets.auto_hide_scrollbar import AutoHideScrollBar
    import utils.motion as motion

    monkeypatch.setattr(AutoHideScrollBar, "_FADE_IN_MS", 1)
    monkeypatch.setattr(AutoHideScrollBar, "_FADE_OUT_MS", 1)
    monkeypatch.setattr(AutoHideScrollBar, "_IDLE_TIMEOUT_MS", 100)
    monkeypatch.setattr(motion, "is_reduced", lambda: False)

    bar = AutoHideScrollBar()
    bar.setRange(0, 100)
    bar.wake()
    qtbot.waitUntil(lambda: bar._opacity_effect.opacity() == 1.0, timeout=200)

    # Re-wake right before the timer would have fired.
    qtbot.wait(60)
    bar.wake()
    # The timer must have been restarted — total ~110ms wait shouldn't have
    # triggered fade-out yet.
    qtbot.wait(60)
    assert bar._opacity_effect.opacity() == 1.0

    # Eventually idle does fire.
    qtbot.waitUntil(lambda: bar._opacity_effect.opacity() == 0.0, timeout=500)
    bar.deleteLater()


def test_reduce_motion_wakes_instantly_no_animation(qapp, monkeypatch):
    from utils.widgets.auto_hide_scrollbar import AutoHideScrollBar
    import utils.motion as motion
    from PySide6.QtCore import QPropertyAnimation

    monkeypatch.setattr(motion, "is_reduced", lambda: True)

    bar = AutoHideScrollBar()
    bar.setRange(0, 100)
    bar.wake()

    # Opacity is 1.0 immediately — no waiting, no animation running.
    assert bar._opacity_effect.opacity() == 1.0
    assert bar._anim.state() != QPropertyAnimation.Running
    # Idle timer is NOT started in reduce-motion mode.
    assert not bar._idle_timer.isActive()
    bar.deleteLater()


def test_reduce_motion_idle_callback_is_noop(qapp, monkeypatch):
    """Even if the idle timer somehow fires (e.g. mode toggled mid-wait),
    _on_idle should not animate when reduce-motion is on."""
    from utils.widgets.auto_hide_scrollbar import AutoHideScrollBar
    import utils.motion as motion

    monkeypatch.setattr(motion, "is_reduced", lambda: True)

    bar = AutoHideScrollBar()
    bar.setRange(0, 100)
    bar._opacity_effect.setOpacity(1.0)
    bar._on_idle()  # must not animate or change opacity
    assert bar._opacity_effect.opacity() == 1.0
    bar.deleteLater()


def test_value_changed_signal_wakes_the_bar(qapp, qtbot, monkeypatch):
    from utils.widgets.auto_hide_scrollbar import AutoHideScrollBar
    import utils.motion as motion

    monkeypatch.setattr(AutoHideScrollBar, "_FADE_IN_MS", 1)
    monkeypatch.setattr(motion, "is_reduced", lambda: False)

    bar = AutoHideScrollBar()
    bar.setRange(0, 100)
    assert bar._opacity_effect.opacity() == 0.0

    # Programmatic scroll position change emits valueChanged.
    bar.setValue(50)

    qtbot.waitUntil(lambda: bar._opacity_effect.opacity() == 1.0, timeout=200)
    bar.deleteLater()


def test_enter_event_wakes_the_bar(qapp, qtbot, monkeypatch):
    from PySide6.QtCore import QEvent
    from utils.widgets.auto_hide_scrollbar import AutoHideScrollBar
    import utils.motion as motion

    monkeypatch.setattr(AutoHideScrollBar, "_FADE_IN_MS", 1)
    monkeypatch.setattr(motion, "is_reduced", lambda: False)

    bar = AutoHideScrollBar()
    bar.setRange(0, 100)
    assert bar._opacity_effect.opacity() == 0.0

    # Synthesize an Enter event — Qt's enterEvent is the canonical hover hook.
    bar.event(QEvent(QEvent.Enter))

    qtbot.waitUntil(lambda: bar._opacity_effect.opacity() == 1.0, timeout=200)
    bar.deleteLater()


def test_attach_to_viewport_wakes_on_wheel_event(qapp, qtbot, monkeypatch):
    from PySide6.QtCore import QEvent, QPoint, QPointF, Qt, QCoreApplication
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtWidgets import QWidget
    from utils.widgets.auto_hide_scrollbar import AutoHideScrollBar
    import utils.motion as motion

    monkeypatch.setattr(AutoHideScrollBar, "_FADE_IN_MS", 1)
    monkeypatch.setattr(motion, "is_reduced", lambda: False)

    viewport = QWidget()
    bar = AutoHideScrollBar()
    bar.setRange(0, 100)
    bar.attach_to_viewport(viewport)

    assert bar._opacity_effect.opacity() == 0.0

    # Synthesize a wheel event delivered to the viewport.
    wheel = QWheelEvent(
        QPointF(10, 10), QPointF(10, 10),
        QPoint(0, -120), QPoint(0, -120),
        Qt.NoButton, Qt.NoModifier,
        Qt.NoScrollPhase, False,
    )
    QCoreApplication.sendEvent(viewport, wheel)

    qtbot.waitUntil(lambda: bar._opacity_effect.opacity() == 1.0, timeout=200)
    bar.deleteLater()
    viewport.deleteLater()


def test_attach_to_viewport_wakes_on_enter(qapp, qtbot, monkeypatch):
    from PySide6.QtCore import QEvent, QCoreApplication
    from PySide6.QtWidgets import QWidget
    from utils.widgets.auto_hide_scrollbar import AutoHideScrollBar
    import utils.motion as motion

    monkeypatch.setattr(AutoHideScrollBar, "_FADE_IN_MS", 1)
    monkeypatch.setattr(motion, "is_reduced", lambda: False)

    viewport = QWidget()
    bar = AutoHideScrollBar()
    bar.setRange(0, 100)
    bar.attach_to_viewport(viewport)

    QCoreApplication.sendEvent(viewport, QEvent(QEvent.Enter))

    qtbot.waitUntil(lambda: bar._opacity_effect.opacity() == 1.0, timeout=200)
    bar.deleteLater()
    viewport.deleteLater()


def test_install_modern_scrollbar_wires_up_scroll_area(qapp):
    from PySide6.QtWidgets import QScrollArea, QLabel
    from utils.widgets.auto_hide_scrollbar import (
        AutoHideScrollBar,
        install_modern_scrollbar,
    )

    area = QScrollArea()
    area.setWidget(QLabel("content"))

    install_modern_scrollbar(area, is_dark=True)

    bar = area.verticalScrollBar()
    assert isinstance(bar, AutoHideScrollBar)
    # set_theme was called — stylesheet contains dark-mode active color.
    assert "rgba(255, 255, 255, 0.45)" in bar.styleSheet()
    # Helper stashed a reference for later theme refreshes.
    assert area._auto_hide_scrollbar is bar
    area.deleteLater()


def test_install_modern_scrollbar_wakes_on_viewport_wheel(qapp, qtbot, monkeypatch):
    """Smoke: after install, wheeling on the viewport should wake the bar."""
    from PySide6.QtCore import QCoreApplication, QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtWidgets import QLabel, QScrollArea
    from utils.widgets.auto_hide_scrollbar import (
        AutoHideScrollBar,
        install_modern_scrollbar,
    )
    import utils.motion as motion

    monkeypatch.setattr(AutoHideScrollBar, "_FADE_IN_MS", 1)
    monkeypatch.setattr(motion, "is_reduced", lambda: False)

    area = QScrollArea()
    big = QLabel("X" * 5000)
    big.setWordWrap(True)
    area.setWidget(big)
    area.resize(120, 80)
    install_modern_scrollbar(area, is_dark=True)

    bar = area.verticalScrollBar()
    bar.setRange(0, 1000)  # ensure the bar has scrollable range

    wheel = QWheelEvent(
        QPointF(10, 10), QPointF(10, 10),
        QPoint(0, -120), QPoint(0, -120),
        Qt.NoButton, Qt.NoModifier,
        Qt.NoScrollPhase, False,
    )
    QCoreApplication.sendEvent(area.viewport(), wheel)

    qtbot.waitUntil(lambda: bar._opacity_effect.opacity() == 1.0, timeout=200)
    area.deleteLater()


def test_re_exported_from_utils_widgets(qapp):
    """Call sites should be able to import from utils.widgets directly."""
    from utils.widgets import AutoHideScrollBar, install_modern_scrollbar
    assert AutoHideScrollBar is not None
    assert callable(install_modern_scrollbar)


def test_no_qscrollbar_qss_remains_in_tabs():
    """All scrollbar styling must go through AutoHideScrollBar / utils.widgets.

    Regression guard for the 2026-05-13 modern scrollbar migration: bare
    `QScrollBar:` QSS strings in the `tabs/` tree are forbidden because
    they bypass the auto-hide / theme-aware bar.
    """
    import pathlib

    repo_root = pathlib.Path(__file__).parent.parent
    tabs_dir = repo_root / "tabs"
    offenders = []
    for py in tabs_dir.rglob("*.py"):
        text = py.read_text(encoding="utf-8")
        if "QScrollBar:" in text or "QScrollBar::" in text:
            offenders.append(str(py.relative_to(repo_root)))
    assert offenders == [], (
        f"Files in tabs/ contain raw QScrollBar QSS: {offenders}. "
        f"Use utils.widgets.install_modern_scrollbar instead."
    )
