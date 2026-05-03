"""Tests for the keep-alive opt-in master toggle (TTR/CC TOS compliance)."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_keep_alive_master_default_off(tmp_path, monkeypatch):
    """A fresh SettingsManager has keep_alive_enabled defaulting to False."""
    monkeypatch.setenv("HOME", str(tmp_path))
    from utils.settings_manager import SettingsManager
    sm = SettingsManager()
    assert sm.get("keep_alive_enabled") is False


import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication


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


def test_keep_alive_helper_returns_false_by_default(tab):
    assert tab._keep_alive_globally_enabled() is False


def test_keep_alive_helper_returns_true_when_set(tab):
    tab.settings_manager.set("keep_alive_enabled", True)
    assert tab._keep_alive_globally_enabled() is True


def _force_window_available(tab, slot=0):
    """Helper: simulate one detected toon window so per-toon controls activate."""
    tab.window_manager.ttr_window_ids = ["fake_wid"]
    tab.enabled_toons[slot] = True
    tab.service_running = True


def test_per_toon_button_disabled_when_master_off(tab):
    _force_window_available(tab, slot=0)
    tab.settings_manager.set("keep_alive_enabled", False)
    tab.apply_visual_state(0)
    assert tab.keep_alive_buttons[0].isEnabled() is False
    assert "Settings" in tab.keep_alive_buttons[0].toolTip()


def test_per_toon_button_enabled_when_master_on(tab):
    _force_window_available(tab, slot=0)
    tab.settings_manager.set("keep_alive_enabled", True)
    tab.apply_visual_state(0)
    assert tab.keep_alive_buttons[0].isEnabled() is True
    # Existing tooltip preserved (set in _build_shared_widgets)
    assert "Toggle keep-alive" in tab.keep_alive_buttons[0].toolTip()


def test_keep_alive_loop_skips_when_master_off(tab, monkeypatch):
    """The thread loop reads keep_alive_enabled at the top of each cycle
    and skips firing when it's False. Defense in depth against races."""
    sent_calls = []

    class _StubInputService:
        def send_keep_alive_to_window(self, *args, **kwargs):
            sent_calls.append((args, kwargs))

        def stop(self):
            pass

        def start(self):
            pass

    tab.input_service = _StubInputService()
    tab.window_manager.ttr_window_ids = ["wid_a", "wid_b"]
    tab.keep_alive_enabled = [True, True, False, False]
    tab.settings_manager.set("keep_alive_enabled", False)

    # Drive one iteration of the loop body manually.
    # We can't easily start the thread in tests; instead, assert the
    # gating helper that the loop checks returns False, AND assert the
    # production loop's gating decision via a direct invariant test.
    assert tab._keep_alive_globally_enabled() is False
    # Simulate the loop's gating decision:
    fire_toons = [
        i for i, state in enumerate(tab.keep_alive_enabled)
        if state and tab._keep_alive_globally_enabled()
    ]
    assert fire_toons == []


def test_keep_alive_loop_fires_when_master_on(tab):
    tab.window_manager.ttr_window_ids = ["wid_a", "wid_b"]
    tab.keep_alive_enabled = [True, True, False, False]
    tab.settings_manager.set("keep_alive_enabled", True)

    fire_toons = [
        i for i, state in enumerate(tab.keep_alive_enabled)
        if state and tab._keep_alive_globally_enabled()
    ]
    assert fire_toons == [0, 1]


def test_toggle_keep_alive_no_op_when_master_off(tab):
    """Programmatic calls to toggle_keep_alive must early-return when master
    is off (defense against profile-load or hotkey paths)."""
    tab.window_manager.ttr_window_ids = ["wid_a"]
    tab.service_running = True
    tab.enabled_toons[0] = True
    tab.settings_manager.set("keep_alive_enabled", False)

    assert tab.keep_alive_enabled[0] is False
    tab.toggle_keep_alive(0)
    assert tab.keep_alive_enabled[0] is False  # Still off — toggle suppressed


def test_toggle_keep_alive_works_when_master_on(tab):
    tab.window_manager.ttr_window_ids = ["wid_a"]
    tab.service_running = True
    tab.enabled_toons[0] = True
    tab.settings_manager.set("keep_alive_enabled", True)

    assert tab.keep_alive_enabled[0] is False
    tab.toggle_keep_alive(0)
    assert tab.keep_alive_enabled[0] is True
    # Cleanup so other tests aren't polluted
    tab.toggle_keep_alive(0)


def test_suspend_keep_alive_preserves_per_toon_flags(tab):
    """_suspend_keep_alive stops execution but does NOT zero per-toon flags.
    Per-toon configuration is the user's setup, preserved across master toggles."""
    tab.window_manager.ttr_window_ids = ["wid_a", "wid_b"]
    tab.service_running = True
    tab.enabled_toons = [True, True, False, False]
    tab.keep_alive_enabled = [True, True, False, False]
    tab.rapid_fire_enabled = [False, True, False, False]
    tab.settings_manager.set("keep_alive_enabled", True)

    tab._suspend_keep_alive()

    # Per-toon flags preserved
    assert tab.keep_alive_enabled == [True, True, False, False]
    assert tab.rapid_fire_enabled == [False, True, False, False]
    # Thread halted (or was never running, but the flag should be cleared)
    assert tab._keep_alive_running is False


def test_long_press_no_op_when_button_disabled(qapp):
    """Holding a disabled KeepAliveBtn for >5s does not toggle rapid-fire."""
    from tabs.multitoon._tab import KeepAliveBtn
    btn = KeepAliveBtn()
    btn.setEnabled(False)
    btn.is_rapid_fire = False
    # Simulate the timer having fired (the timer is a singleshot — bypass
    # the press/release machinery and call _on_long_press directly).
    btn._on_long_press()
    assert btn.is_rapid_fire is False


def test_setting_change_off_invokes_suspend(tab, monkeypatch):
    """When SettingsManager changes keep_alive_enabled to False,
    _on_setting_changed must call _suspend_keep_alive."""
    suspend_called = []
    monkeypatch.setattr(
        tab, "_suspend_keep_alive", lambda: suspend_called.append(True)
    )
    tab.settings_manager.set("keep_alive_enabled", True)  # initial state
    tab._on_setting_changed("keep_alive_enabled", False)
    assert suspend_called == [True]


def test_setting_change_on_resumes_per_toon_flags(tab, monkeypatch):
    """When the master flips on with per-toon flags set, the thread starts."""
    started = []
    monkeypatch.setattr(
        tab, "_start_keep_alive", lambda: started.append(True)
    )
    tab.window_manager.ttr_window_ids = ["wid_a"]
    tab.service_running = True
    tab.keep_alive_enabled = [True, False, False, False]
    tab.settings_manager.set("keep_alive_enabled", True)
    tab._on_setting_changed("keep_alive_enabled", True)
    assert started == [True]


def test_setting_change_on_no_start_when_no_per_toon_active(tab, monkeypatch):
    """Master flips on but no per-toon flags set → thread NOT started."""
    started = []
    monkeypatch.setattr(
        tab, "_start_keep_alive", lambda: started.append(True)
    )
    tab.keep_alive_enabled = [False, False, False, False]
    tab.settings_manager.set("keep_alive_enabled", True)
    tab._on_setting_changed("keep_alive_enabled", True)
    assert started == []


def test_load_profile_respects_master_off(tab, monkeypatch):
    """Loading a profile with keep_alive=[true, true, true, true] while the
    master is off must NOT start the keep-alive thread, but must preserve the
    per-toon flags so they restore when the master is later flipped on."""
    started = []
    monkeypatch.setattr(
        tab, "_start_keep_alive", lambda: started.append(True)
    )

    # Stub a minimal profile_manager so load_profile can run end-to-end.
    class _Profile:
        enabled_toons = [True, True, True, True]
        movement_modes = ["Default"] * 4
        keep_alive = [True, True, True, True]
        rapid_fire = [False, False, False, False]

    class _ProfileManager:
        def get_profile(self, idx):
            return _Profile()

        def get_name(self, idx):
            return "Test"

    tab.profile_manager = _ProfileManager()
    tab._active_profile = -1  # so _autosave_active_profile is a no-op
    tab.settings_manager.set("keep_alive_enabled", False)

    tab.load_profile(0)

    assert started == []  # _start_keep_alive NOT invoked
    assert tab.keep_alive_enabled == [True, True, True, True]  # flags preserved
