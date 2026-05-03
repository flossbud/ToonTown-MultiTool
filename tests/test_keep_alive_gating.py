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
