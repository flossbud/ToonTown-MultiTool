"""Tests for the Reduce Motion row in the Settings General group."""

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget

import utils.motion as motion


class _StubSettings:
    def __init__(self, **kv):
        self._kv = dict(kv)
        self._cbs = []
    def get(self, key, default=None):
        return self._kv.get(key, default)
    def set(self, key, value):
        self._kv[key] = value
        for cb in self._cbs:
            cb(key, value)
    def on_change(self, cb):
        self._cbs.append(cb)


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    return app


def _build_general_only(stub):
    """Build a SettingsTab instance and only run _build_general_group on it.

    This bypasses the heavy full __init__ (which spins up other tabs and
    services we don't need for this test).

    The container widget is kept alive by storing it on the tab so Qt signals
    from child widgets remain valid after _build_general_group returns.
    """
    from tabs.settings_tab import SettingsTab
    tab = SettingsTab.__new__(SettingsTab)
    tab.settings_manager = stub
    container = QWidget()
    tab._container = container  # keep alive so child signals stay valid
    tab._main_layout = QVBoxLayout(container)
    tab._groups = []
    tab._build_general_group()
    return tab


def test_reduce_motion_row_present_in_general(qapp, monkeypatch):
    monkeypatch.setattr(motion, "_os_reduced_motion", lambda: False)
    monkeypatch.setattr(motion, "_settings", None)
    stub = _StubSettings()
    tab = _build_general_only(stub)
    assert hasattr(tab, "reduce_motion_row")


def test_toggling_reduce_motion_writes_both_keys(qapp, monkeypatch):
    monkeypatch.setattr(motion, "_os_reduced_motion", lambda: False)
    monkeypatch.setattr(motion, "_settings", None)
    stub = _StubSettings()
    tab = _build_general_only(stub)

    tab.reduce_motion_row.toggled.emit(True)

    assert stub.get("reduce_motion") is True
    assert stub.get("reduce_motion_set_explicitly") is True


def test_initial_toggle_state_reflects_os_when_unset(qapp, monkeypatch):
    monkeypatch.setattr(motion, "_os_reduced_motion", lambda: True)
    monkeypatch.setattr(motion, "_OS_REDUCED_MOTION_CACHE", None)
    stub = _StubSettings(reduce_motion_set_explicitly=False)
    motion.set_settings_manager(stub)
    tab = _build_general_only(stub)

    # Row should reflect the effective is_reduced() result.
    assert tab.reduce_motion_row.isChecked() is True
