"""Tests for the tri-state Reduce Motion row in the General settings group.

The control encodes:
  index 0 → "System default"  (reduce_motion_set_explicitly = False)
  index 1 → "On"              (set_explicitly = True, reduce_motion = True)
  index 2 → "Off"             (set_explicitly = True, reduce_motion = False)
"""

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
    from tabs.settings_tab import SettingsTab
    tab = SettingsTab.__new__(SettingsTab)
    tab.settings_manager = stub
    container = QWidget()
    tab._container = container  # keep alive across signal emit
    tab._main_layout = QVBoxLayout(container)
    tab._groups = []
    tab._build_general_group()
    return tab


def test_reduce_motion_row_is_dropdown_with_three_options(qapp, monkeypatch):
    monkeypatch.setattr(motion, "_os_reduced_motion", lambda: False)
    monkeypatch.setattr(motion, "_settings", None)
    monkeypatch.setattr(motion, "_OS_REDUCED_MOTION_CACHE", None)
    stub = _StubSettings()
    tab = _build_general_only(stub)
    assert hasattr(tab, "reduce_motion_row")
    assert tab.reduce_motion_row._options == ["System default", "On", "Off"]


def test_selecting_system_default_clears_explicit(qapp, monkeypatch):
    monkeypatch.setattr(motion, "_os_reduced_motion", lambda: False)
    monkeypatch.setattr(motion, "_settings", None)
    monkeypatch.setattr(motion, "_OS_REDUCED_MOTION_CACHE", None)
    # Start with the user having explicitly chosen Off.
    stub = _StubSettings(
        reduce_motion=False,
        reduce_motion_set_explicitly=True,
    )
    tab = _build_general_only(stub)
    # User selects "System default" (index 0).
    tab.reduce_motion_row.index_changed.emit(0)
    assert stub.get("reduce_motion_set_explicitly") is False


def test_selecting_on_sets_explicit_true_and_value_true(qapp, monkeypatch):
    monkeypatch.setattr(motion, "_os_reduced_motion", lambda: False)
    monkeypatch.setattr(motion, "_settings", None)
    monkeypatch.setattr(motion, "_OS_REDUCED_MOTION_CACHE", None)
    stub = _StubSettings()
    tab = _build_general_only(stub)
    tab.reduce_motion_row.index_changed.emit(1)
    assert stub.get("reduce_motion") is True
    assert stub.get("reduce_motion_set_explicitly") is True


def test_selecting_off_sets_explicit_true_and_value_false(qapp, monkeypatch):
    monkeypatch.setattr(motion, "_os_reduced_motion", lambda: False)
    monkeypatch.setattr(motion, "_settings", None)
    monkeypatch.setattr(motion, "_OS_REDUCED_MOTION_CACHE", None)
    stub = _StubSettings()
    tab = _build_general_only(stub)
    tab.reduce_motion_row.index_changed.emit(2)
    assert stub.get("reduce_motion") is False
    assert stub.get("reduce_motion_set_explicitly") is True


def test_initial_index_when_unset_is_system_default(qapp, monkeypatch):
    monkeypatch.setattr(motion, "_os_reduced_motion", lambda: True)
    monkeypatch.setattr(motion, "_OS_REDUCED_MOTION_CACHE", None)
    stub = _StubSettings(reduce_motion_set_explicitly=False)
    motion.set_settings_manager(stub)
    tab = _build_general_only(stub)
    # User has NOT set the pref explicitly — initial index must be 0
    # (System default), regardless of what the OS currently says.
    assert tab.reduce_motion_row.combo.currentIndex() == 0


def test_initial_index_when_explicit_on(qapp, monkeypatch):
    monkeypatch.setattr(motion, "_os_reduced_motion", lambda: False)
    monkeypatch.setattr(motion, "_OS_REDUCED_MOTION_CACHE", None)
    stub = _StubSettings(
        reduce_motion=True,
        reduce_motion_set_explicitly=True,
    )
    motion.set_settings_manager(stub)
    tab = _build_general_only(stub)
    assert tab.reduce_motion_row.combo.currentIndex() == 1


def test_initial_index_when_explicit_off(qapp, monkeypatch):
    monkeypatch.setattr(motion, "_os_reduced_motion", lambda: False)
    monkeypatch.setattr(motion, "_OS_REDUCED_MOTION_CACHE", None)
    stub = _StubSettings(
        reduce_motion=False,
        reduce_motion_set_explicitly=True,
    )
    motion.set_settings_manager(stub)
    tab = _build_general_only(stub)
    assert tab.reduce_motion_row.combo.currentIndex() == 2
