"""Tests for the tri-state Reduce Motion control on the General settings page.

The combo encodes:
  index 0 → "System default"  (reduce_motion_set_explicitly = False)
  index 1 → "On"              (set_explicitly = True, reduce_motion = True)
  index 2 → "Off"             (set_explicitly = True, reduce_motion = False)
"""

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QComboBox

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
    return QApplication.instance() or QApplication([])


def _build_tab(stub):
    from tabs.settings_tab import SettingsTab
    return SettingsTab(settings_manager=stub)


def _find_reduce_motion_combo(tab):
    """Walk the General page for a SettingsField labeled 'Reduce motion' and
    return its QComboBox control."""
    from tabs.settings_tab import SettingsField
    for f in tab.pages["general"].findChildren(SettingsField):
        if f.label_widget.text() == "Reduce motion":
            assert isinstance(f.control_widget, QComboBox)
            return f.control_widget
    return None


def test_reduce_motion_combo_has_three_options(qapp, monkeypatch):
    monkeypatch.setattr(motion, "_os_reduced_motion", lambda: False)
    monkeypatch.setattr(motion, "_settings", None)
    monkeypatch.setattr(motion, "_OS_REDUCED_MOTION_CACHE", None)
    stub = _StubSettings()
    tab = _build_tab(stub)
    combo = _find_reduce_motion_combo(tab)
    assert combo is not None
    # Closed state uses short "System" (avoids truncation at 150px); the
    # menu retains "System default" via MENU_TEXT_ROLE — see
    # test_reduce_motion_combo_uses_short_closed_text for that path.
    options = [combo.itemText(i) for i in range(combo.count())]
    assert options == ["System", "On", "Off"]


def test_selecting_system_default_clears_explicit(qapp, monkeypatch):
    monkeypatch.setattr(motion, "_os_reduced_motion", lambda: False)
    monkeypatch.setattr(motion, "_settings", None)
    monkeypatch.setattr(motion, "_OS_REDUCED_MOTION_CACHE", None)
    stub = _StubSettings(
        reduce_motion=False,
        reduce_motion_set_explicitly=True,
    )
    tab = _build_tab(stub)
    combo = _find_reduce_motion_combo(tab)
    combo.setCurrentIndex(0)
    assert stub.get("reduce_motion_set_explicitly") is False


def test_selecting_on_sets_explicit_true_and_value_true(qapp, monkeypatch):
    monkeypatch.setattr(motion, "_os_reduced_motion", lambda: False)
    monkeypatch.setattr(motion, "_settings", None)
    monkeypatch.setattr(motion, "_OS_REDUCED_MOTION_CACHE", None)
    stub = _StubSettings()
    tab = _build_tab(stub)
    combo = _find_reduce_motion_combo(tab)
    combo.setCurrentIndex(1)
    assert stub.get("reduce_motion") is True
    assert stub.get("reduce_motion_set_explicitly") is True


def test_selecting_off_sets_explicit_true_and_value_false(qapp, monkeypatch):
    monkeypatch.setattr(motion, "_os_reduced_motion", lambda: False)
    monkeypatch.setattr(motion, "_settings", None)
    monkeypatch.setattr(motion, "_OS_REDUCED_MOTION_CACHE", None)
    # Start at index 0 (System default) so setCurrentIndex(2) actually fires.
    stub = _StubSettings()
    tab = _build_tab(stub)
    combo = _find_reduce_motion_combo(tab)
    combo.setCurrentIndex(2)
    assert stub.get("reduce_motion") is False
    assert stub.get("reduce_motion_set_explicitly") is True


def test_initial_index_when_unset_is_system_default(qapp, monkeypatch):
    monkeypatch.setattr(motion, "_os_reduced_motion", lambda: True)
    monkeypatch.setattr(motion, "_OS_REDUCED_MOTION_CACHE", None)
    stub = _StubSettings(reduce_motion_set_explicitly=False)
    motion.set_settings_manager(stub)
    tab = _build_tab(stub)
    combo = _find_reduce_motion_combo(tab)
    # User has NOT set the pref explicitly — initial index must be 0
    # (System default), regardless of OS state.
    assert combo.currentIndex() == 0


def test_initial_index_when_explicit_on(qapp, monkeypatch):
    monkeypatch.setattr(motion, "_os_reduced_motion", lambda: False)
    monkeypatch.setattr(motion, "_OS_REDUCED_MOTION_CACHE", None)
    stub = _StubSettings(
        reduce_motion=True,
        reduce_motion_set_explicitly=True,
    )
    motion.set_settings_manager(stub)
    tab = _build_tab(stub)
    combo = _find_reduce_motion_combo(tab)
    assert combo.currentIndex() == 1


def test_initial_index_when_explicit_off(qapp, monkeypatch):
    monkeypatch.setattr(motion, "_os_reduced_motion", lambda: False)
    monkeypatch.setattr(motion, "_OS_REDUCED_MOTION_CACHE", None)
    stub = _StubSettings(
        reduce_motion=False,
        reduce_motion_set_explicitly=True,
    )
    motion.set_settings_manager(stub)
    tab = _build_tab(stub)
    combo = _find_reduce_motion_combo(tab)
    assert combo.currentIndex() == 2
