"""Tests for MultitoonTab's picker wiring (manager + dialog open)."""

from __future__ import annotations

import os
import sys

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance() or QApplication(sys.argv)
    return app


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


def _make_tab(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("TTMT_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("TTMT_NO_VENV_REEXEC", "1")
    from tabs.multitoon._tab import MultitoonTab
    from utils.settings_manager import SettingsManager

    tab = MultitoonTab(
        settings_manager=SettingsManager(),
        window_manager=_FakeWindowManager(),
    )
    return tab


@pytest.fixture
def multitoon_env(monkeypatch, tmp_path):
    monkeypatch.setenv("TTMT_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("TTMT_NO_VENV_REEXEC", "1")
    return tmp_path


def test_multitoon_tab_owns_overrides_manager(qt_app, monkeypatch, tmp_path):
    tab = _make_tab(monkeypatch, tmp_path)
    assert hasattr(tab, "cc_overrides")
    from utils.cc_race_overrides_manager import CCRaceOverridesManager
    assert isinstance(tab.cc_overrides, CCRaceOverridesManager)


def test_badges_have_overrides_manager_injected(qt_app, monkeypatch, tmp_path):
    tab = _make_tab(monkeypatch, tmp_path)
    for badge in tab.slot_badges:
        assert badge._overrides_manager is tab.cc_overrides


def test_save_from_picker_persists_override(qt_app, monkeypatch, tmp_path):
    """When the picker returns ('set', stem), the manager is updated and
    the badge's resolution returns the new stem."""
    tab = _make_tab(monkeypatch, tmp_path)
    badge = tab.slot_badges[0]
    badge.set_toon_name("Flossbud")
    badge.set_cc_auto_species("DOG")
    badge.set_cc_mode(
        skin_rgb=(0.84, 0.19, 0.19),
        accent_rgb=None, gloves_rgb=None, emoji=None,
    )

    # Simulate the picker returning a manual choice.
    tab._apply_picker_result(slot=0, result=("set", "cat"))

    assert tab.cc_overrides.get("Flossbud") == "cat"
    assert badge._resolve_asset_stem() == "cat"


def test_clear_from_picker_removes_override(qt_app, monkeypatch, tmp_path):
    tab = _make_tab(monkeypatch, tmp_path)
    tab.cc_overrides.set("Flossbud", "cat")
    badge = tab.slot_badges[0]
    badge.set_toon_name("Flossbud")
    badge.set_cc_auto_species("DOG")
    badge.set_cc_mode(
        skin_rgb=(0.84, 0.19, 0.19),
        accent_rgb=None, gloves_rgb=None, emoji=None,
    )

    tab._apply_picker_result(slot=0, result=("clear", None))

    assert tab.cc_overrides.get("Flossbud") is None
    assert badge._resolve_asset_stem() == "dog"


def test_cancel_from_picker_is_noop(qt_app, monkeypatch, tmp_path):
    tab = _make_tab(monkeypatch, tmp_path)
    tab.cc_overrides.set("Flossbud", "cat")
    badge = tab.slot_badges[0]
    badge.set_toon_name("Flossbud")

    tab._apply_picker_result(slot=0, result=("cancel", None))

    assert tab.cc_overrides.get("Flossbud") == "cat"
