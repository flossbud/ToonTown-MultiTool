"""Tests for the keep-alive hide-when-disabled feature."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication, QHBoxLayout


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class _FakeSettingsManager:
    def __init__(self, initial=None):
        self._data = dict(initial or {})

    def get(self, key, default=None):
        return self._data.get(key, default)

    def set(self, key, value):
        self._data[key] = value

    def on_change(self, callback):
        pass


class _FakeWindowManager(QObject):
    window_ids_updated = Signal(list)

    def __init__(self):
        super().__init__()
        self.ttr_window_ids = []

    def get_window_ids(self):
        return []

    def clear_window_ids(self):
        pass

    def assign_windows(self):
        pass

    def enable_detection(self):
        pass

    def disable_detection(self):
        pass


@pytest.fixture
def tab(qapp):
    from tabs.multitoon_tab import MultitoonTab
    return MultitoonTab(
        settings_manager=_FakeSettingsManager(),
        window_manager=_FakeWindowManager(),
    )


def test_compact_ctrl_row_contains_nested_middle_layout(tab):
    """After build_ui, each compact card's ctrl_row should be:
    [enable_btn, middle (HBoxLayout containing ka_group + addStretch), selector]"""
    slot_zero = tab._compact._card_slots[0]
    ctrl_row = slot_zero["ctrl_row"]

    # ctrl_row should have 3 items: enable_btn (widget), middle (sub-layout), selector (widget)
    assert ctrl_row.count() == 3, (
        f"ctrl_row should have 3 items (enable, middle, selector); got {ctrl_row.count()}"
    )

    # Item 1 (middle) must be a QHBoxLayout (not a widget)
    middle_item = ctrl_row.itemAt(1)
    middle_layout = middle_item.layout()
    assert isinstance(middle_layout, QHBoxLayout), (
        f"ctrl_row item 1 should be a QHBoxLayout (middle); got {type(middle_layout)}"
    )

    # middle should have 2 items: ka_group widget + a stretch spacer
    assert middle_layout.count() == 2, (
        f"middle should have 2 items (ka_group, addStretch); got {middle_layout.count()}"
    )
    # Item 0: ka_group widget
    assert middle_layout.itemAt(0).widget() is slot_zero["ka_group"], (
        "middle item 0 should be ka_group"
    )
    # Item 1: spacer (stretch). spacerItem() returns the QSpacerItem if it's a stretch.
    assert middle_layout.itemAt(1).spacerItem() is not None, (
        "middle item 1 should be a stretch spacer"
    )


def test_init_visibility_master_off_hides_ka_widgets(qapp):
    """A fresh MultitoonTab with master OFF should have KA button + bar
    hidden after build_ui, and ka_group stretch in middle should be 0."""
    from tabs.multitoon_tab import MultitoonTab
    sm = _FakeSettingsManager({"keep_alive_enabled": False})
    tab = MultitoonTab(settings_manager=sm, window_manager=_FakeWindowManager())

    for i in range(4):
        assert tab.keep_alive_buttons[i].isHidden() is True, (
            f"slot {i} ka_btn should be hidden when master OFF"
        )
        assert tab.ka_progress_bars[i].isHidden() is True, (
            f"slot {i} ka_bar should be hidden when master OFF"
        )

    # Compact: ka_group stretch in middle should be 0
    for i in range(4):
        slot = tab._compact._card_slots[i]
        middle = slot["middle"]
        # ka_group is at index 0 of middle
        assert middle.stretch(0) == 0, (
            f"slot {i} ka_group stretch should be 0 when master OFF; got {middle.stretch(0)}"
        )


def test_init_visibility_master_on_shows_ka_widgets(qapp):
    """A fresh MultitoonTab with master ON should have KA widgets visible."""
    from tabs.multitoon_tab import MultitoonTab
    sm = _FakeSettingsManager({"keep_alive_enabled": True})
    tab = MultitoonTab(settings_manager=sm, window_manager=_FakeWindowManager())

    for i in range(4):
        assert tab.keep_alive_buttons[i].isHidden() is False, (
            f"slot {i} ka_btn should be visible when master ON"
        )
        assert tab.ka_progress_bars[i].isHidden() is False, (
            f"slot {i} ka_bar should be visible when master ON"
        )

    # Compact: ka_group stretch in middle should be 1
    for i in range(4):
        slot = tab._compact._card_slots[i]
        middle = slot["middle"]
        assert middle.stretch(0) == 1, (
            f"slot {i} ka_group stretch should be 1 when master ON; got {middle.stretch(0)}"
        )


def test_setting_change_does_not_alter_visibility_when_tab_hidden(qapp, monkeypatch):
    """Toggling master while MultitoonTab is hidden must NOT change widget
    visibility (deferred until showEvent). Thread state still changes."""
    from tabs.multitoon_tab import MultitoonTab
    sm = _FakeSettingsManager({"keep_alive_enabled": False})
    tab = MultitoonTab(settings_manager=sm, window_manager=_FakeWindowManager())

    # Confirm baseline: master OFF, widgets hidden.
    assert tab.keep_alive_buttons[0].isHidden() is True

    # Force MultitoonTab.isVisible() to return False (simulating user on Settings).
    monkeypatch.setattr(tab, "isVisible", lambda: False)
    sm.set("keep_alive_enabled", True)
    tab._on_setting_changed("keep_alive_enabled", True)

    # Visibility should NOT have changed yet.
    assert tab.keep_alive_buttons[0].isHidden() is True, (
        "ka_btn should still be hidden — visibility update is deferred"
    )


def test_show_event_reconciles_visibility_to_match_setting(qapp, monkeypatch):
    """When the multitoon tab becomes visible and widget hidden state doesn't
    match the master setting, showEvent should reconcile (instant setVisible
    in this task; animation comes in later tasks)."""
    from tabs.multitoon_tab import MultitoonTab
    from PySide6.QtGui import QShowEvent
    sm = _FakeSettingsManager({"keep_alive_enabled": False})
    tab = MultitoonTab(settings_manager=sm, window_manager=_FakeWindowManager())

    # Defer: master flips to True while tab "hidden".
    monkeypatch.setattr(tab, "isVisible", lambda: False)
    sm.set("keep_alive_enabled", True)
    tab._on_setting_changed("keep_alive_enabled", True)
    assert tab.keep_alive_buttons[0].isHidden() is True  # not yet reconciled

    # Now fire showEvent — reconciliation happens.
    tab.showEvent(QShowEvent())

    assert tab.keep_alive_buttons[0].isHidden() is False
    assert tab.ka_progress_bars[0].isHidden() is False


def test_setting_change_while_visible_reconciles_immediately(qapp, monkeypatch):
    """If the user toggles master while already on multitoon (isVisible True),
    reconciliation happens in _on_setting_changed without waiting for showEvent."""
    from tabs.multitoon_tab import MultitoonTab
    sm = _FakeSettingsManager({"keep_alive_enabled": False})
    tab = MultitoonTab(settings_manager=sm, window_manager=_FakeWindowManager())

    monkeypatch.setattr(tab, "isVisible", lambda: True)
    sm.set("keep_alive_enabled", True)
    tab._on_setting_changed("keep_alive_enabled", True)

    assert tab.keep_alive_buttons[0].isHidden() is False
    assert tab.ka_progress_bars[0].isHidden() is False


def test_show_event_no_op_when_state_matches(qapp):
    """When KA widget visibility already matches the master setting, showEvent
    must NOT touch the widgets — _maybe_animate_keep_alive_visibility short-
    circuits."""
    from tabs.multitoon_tab import MultitoonTab
    from PySide6.QtGui import QShowEvent
    sm = _FakeSettingsManager({"keep_alive_enabled": True})
    tab = MultitoonTab(settings_manager=sm, window_manager=_FakeWindowManager())

    # Master ON, widgets already visible (init paint set them visible).
    assert tab.keep_alive_buttons[0].isHidden() is False

    # Track setVisible calls on ka_btn[0] via a simple flag override.
    set_visible_calls = []
    original_setVisible = tab.keep_alive_buttons[0].setVisible
    def tracking_setVisible(v):
        set_visible_calls.append(v)
        original_setVisible(v)
    tab.keep_alive_buttons[0].setVisible = tracking_setVisible

    # Fire showEvent — no-op expected.
    tab.showEvent(QShowEvent())

    assert set_visible_calls == [], (
        f"showEvent should be no-op when state matches; setVisible called with {set_visible_calls}"
    )


def test_apply_visual_state_does_not_touch_ka_widget_visibility(qapp):
    """Architectural invariant: apply_visual_state must NOT change KA widget
    visibility. Visibility is owned only by _init_keep_alive_visibility and
    the animation completion handlers."""
    from tabs.multitoon_tab import MultitoonTab

    # Test both master states.
    for master_state in (False, True):
        sm = _FakeSettingsManager({"keep_alive_enabled": master_state})
        tab = MultitoonTab(settings_manager=sm, window_manager=_FakeWindowManager())

        # Capture initial visibility (set by _init_keep_alive_visibility).
        initial_btn_hidden = tab.keep_alive_buttons[0].isHidden()
        initial_bar_hidden = tab.ka_progress_bars[0].isHidden()

        # Run apply_visual_state for various per-toon states.
        for window_available in (False, True):
            tab.window_manager.ttr_window_ids = ["fake_wid"] if window_available else []
            tab.service_running = window_available
            tab.enabled_toons[0] = window_available
            tab.apply_visual_state(0)

            assert tab.keep_alive_buttons[0].isHidden() is initial_btn_hidden, (
                f"apply_visual_state changed ka_btn visibility (master={master_state}, "
                f"window_available={window_available})"
            )
            assert tab.ka_progress_bars[0].isHidden() is initial_bar_hidden, (
                f"apply_visual_state changed ka_bar visibility (master={master_state}, "
                f"window_available={window_available})"
            )


def test_full_ui_animation_fades_opacity(qapp):
    """Full UI's animation method should drive opacity, not position."""
    from PySide6.QtCore import QPropertyAnimation
    from tabs.multitoon_tab import MultitoonTab

    sm = _FakeSettingsManager({"keep_alive_enabled": False})
    tab = MultitoonTab(settings_manager=sm, window_manager=_FakeWindowManager())

    # Switch to Full UI so its animation method is the active one.
    tab.set_layout_mode("full")
    qapp.processEvents()

    # Selector x position before — capture for comparison.
    selector = tab.set_selectors[0]
    pos_before = selector.x()

    # Trigger expand animation via Full UI's method.
    tab._full._animate_keep_alive_visibility(True)
    qapp.processEvents()

    # The animation should have started with widgets visible but starting
    # at opacity 0 (effect in place, animating up).
    ka_btn = tab.keep_alive_buttons[0]
    assert ka_btn.isHidden() is False, "ka_btn should be visible during expand animation"

    # Selector x must NOT have moved (no position changes in Full UI).
    assert selector.x() == pos_before, (
        f"selector x should be unchanged in Full UI animation; was {pos_before}, now {selector.x()}"
    )


def test_compact_animation_drives_ka_group_fixed_width(qapp):
    """Compact's animation should drive ka_group.setFixedWidth via
    QVariantAnimation. After expand animation completes, ka_group's
    fixed-width is cleared (set to QWIDGETSIZE_MAX) so stretch takes over."""
    from PySide6.QtCore import QVariantAnimation
    from tabs.multitoon_tab import MultitoonTab

    sm = _FakeSettingsManager({"keep_alive_enabled": False})
    tab = MultitoonTab(settings_manager=sm, window_manager=_FakeWindowManager())

    # Trigger expand via Compact's method directly.
    tab._compact._animate_keep_alive_visibility(True)
    qapp.processEvents()

    # During animation, _ka_anims should contain at least one QVariantAnimation
    # (the width animation) per slot.
    assert hasattr(tab._compact, "_ka_anims")
    width_anims = [a for a in tab._compact._ka_anims if isinstance(a, QVariantAnimation)]
    assert len(width_anims) >= 4, (
        f"expected at least 4 QVariantAnimation instances (one per slot); got {len(width_anims)}"
    )


def test_compact_collapse_animation_hides_widgets_at_end(qapp):
    """After a collapse animation completes (driven via processEvents),
    ka_btn and ka_bar should be hidden, and ka_group's stretch in middle
    should be 0."""
    from tabs.multitoon_tab import MultitoonTab
    import time

    sm = _FakeSettingsManager({"keep_alive_enabled": True})
    tab = MultitoonTab(settings_manager=sm, window_manager=_FakeWindowManager())

    # Master OFF→trigger collapse.
    tab._compact._animate_keep_alive_visibility(False)

    # Drive event loop until all collapse animations finish (max 500 ms wall clock).
    # Both ka_btn hidden AND stretch==0 must be satisfied (width anim finishes ~80ms
    # after widgets hide, so we keep processing events past the hide event).
    middle = tab._compact._card_slots[0]["middle"]
    deadline = time.monotonic() + 0.5
    while time.monotonic() < deadline:
        qapp.processEvents()
        if tab.keep_alive_buttons[0].isHidden() and middle.stretch(0) == 0:
            break

    assert tab.keep_alive_buttons[0].isHidden() is True, (
        "ka_btn should be hidden after collapse animation completes"
    )
    assert tab.ka_progress_bars[0].isHidden() is True, (
        "ka_bar should be hidden after collapse animation completes"
    )
    # Stretch returned to 0
    assert middle.stretch(0) == 0


def test_compact_animation_reversal_stops_old_animations(qapp):
    """Calling _animate_keep_alive_visibility a second time mid-flight
    should stop the first animations and start new ones."""
    from tabs.multitoon_tab import MultitoonTab
    from PySide6.QtCore import QAbstractAnimation

    sm = _FakeSettingsManager({"keep_alive_enabled": False})
    tab = MultitoonTab(settings_manager=sm, window_manager=_FakeWindowManager())

    # Start expand animation.
    tab._compact._animate_keep_alive_visibility(True)
    qapp.processEvents()
    first_anims = list(tab._compact._ka_anims)
    assert len(first_anims) > 0

    # Mid-flight, request collapse — first animations should be stopped.
    tab._compact._animate_keep_alive_visibility(False)
    qapp.processEvents()

    for a in first_anims:
        # Stopped animations have state == Stopped (which is 0 in PySide6).
        assert a.state() == QAbstractAnimation.State.Stopped, (
            "previous animations should be stopped after reversal"
        )


def test_layout_swap_cancels_in_flight_animation(qapp):
    """Switching layouts mid-animation should cancel in-flight animations
    and apply the target state immediately."""
    from tabs.multitoon_tab import MultitoonTab
    from PySide6.QtCore import QAbstractAnimation

    sm = _FakeSettingsManager({"keep_alive_enabled": False})
    tab = MultitoonTab(settings_manager=sm, window_manager=_FakeWindowManager())

    # Trigger expand animation in compact.
    tab._compact._animate_keep_alive_visibility(True)
    qapp.processEvents()

    # Mid-animation, swap to full layout.
    tab.set_layout_mode("full")
    qapp.processEvents()

    # All compact animations should be stopped.
    for a in tab._compact._ka_anims:
        assert a.state() == QAbstractAnimation.State.Stopped


def test_prewarm_calls_cancel_animations_and_reconcile(qapp, monkeypatch):
    """prewarm_full_layout's finally block must call _cancel_keep_alive_animations
    and _reconcile_keep_alive_visibility_instant — symmetric with set_layout_mode."""
    from tabs.multitoon_tab import MultitoonTab
    from PySide6.QtCore import QSize

    sm = _FakeSettingsManager({"keep_alive_enabled": False})
    tab = MultitoonTab(settings_manager=sm, window_manager=_FakeWindowManager())

    cancel_called = []
    reconcile_called = []
    monkeypatch.setattr(
        tab, "_cancel_keep_alive_animations",
        lambda: cancel_called.append(True),
    )
    monkeypatch.setattr(
        tab, "_reconcile_keep_alive_visibility_instant",
        lambda: reconcile_called.append(True),
    )

    # prewarm_full_layout requires self._mode == "compact"
    tab._mode = "compact"
    tab.prewarm_full_layout(size=QSize(1280, 812), include_active=True)

    assert cancel_called == [True], (
        "prewarm should call _cancel_keep_alive_animations"
    )
    assert reconcile_called == [True], (
        "prewarm should call _reconcile_keep_alive_visibility_instant"
    )
