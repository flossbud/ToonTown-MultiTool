"""Regression: keep_alive_enabled on -> off -> on must keep the per-slot KA
widgets AND their container in lockstep with the master flag (live finding:
the pinwheel actuator snapped only the container while the gate tracked the
button's hidden state, so the cycle left an empty capsule / no controls).

Drives the REAL settings-changed chain (the fake fires callbacks like the
real SettingsManager), never the handlers directly."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class _SignalingFakeSettings:
    def __init__(self, initial=None):
        self._data = dict(initial or {})
        self._callbacks = []

    def get(self, key, default=None):
        return self._data.get(key, default)

    def set(self, key, value):
        self._data[key] = value
        for cb in self._callbacks:
            try:
                cb(key, value)
            except Exception:
                pass

    def on_change(self, callback):
        self._callbacks.append(callback)


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


def _assert_lockstep(tab, master: bool, step: str):
    for i in range(4):
        btn = tab.keep_alive_buttons[i]
        bar = tab.ka_progress_bars[i]
        pill = tab._compact._card_slots[i]["ka_pill"]
        # The gate reads the button's explicit hidden state: it must always
        # equal the master flag or the next transition early-returns.
        assert btn.isHidden() == (not master), (
            f"{step}: slot {i} ka_btn isHidden={btn.isHidden()} "
            f"but master={master}")
        assert bar.isHidden() == (not master), (
            f"{step}: slot {i} ka_bar isHidden={bar.isHidden()} "
            f"but master={master}")
        # The container and the interior must agree: an empty shown capsule
        # (container visible, controls hidden) is the reported bug.
        assert pill.isHidden() == (not master), (
            f"{step}: slot {i} ka_pill container isHidden={pill.isHidden()} "
            f"but master={master}")
        assert btn.isVisibleTo(tab) == master, (
            f"{step}: slot {i} ka_btn isVisibleTo={btn.isVisibleTo(tab)} "
            f"but master={master}")


def test_ka_on_off_on_cycle_keeps_widgets_in_lockstep(qapp, monkeypatch):
    from tabs.multitoon_tab import MultitoonTab
    sm = _SignalingFakeSettings()
    tab = MultitoonTab(settings_manager=sm, window_manager=_FakeWindowManager())
    monkeypatch.setattr(tab, "isVisible", lambda: True)

    _assert_lockstep(tab, master=False, step="after build")

    sm.set("keep_alive_consent_acknowledged", True)
    sm.set("keep_alive_enabled", True)
    _assert_lockstep(tab, master=True, step="after ON #1")

    sm.set("keep_alive_enabled", False)
    _assert_lockstep(tab, master=False, step="after OFF")

    sm.set("keep_alive_enabled", True)
    _assert_lockstep(tab, master=True, step="after ON #2")
