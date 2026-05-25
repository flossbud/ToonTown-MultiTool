"""Tests for tab-level wiring of ToonCustomizationsManager."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class _FakeWindowManager(QObject):
    window_ids_updated = Signal(list)

    def __init__(self):
        super().__init__()
        self.ttr_window_ids = []

    def get_window_ids(self): return []
    def clear_window_ids(self): pass
    def assign_windows(self): pass
    def enable_detection(self): pass
    def disable_detection(self): pass


def _build_tab(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("TTMT_CONFIG_DIR", str(tmp_path))
    from tabs.multitoon._tab import MultitoonTab
    from utils.settings_manager import SettingsManager
    tab = MultitoonTab(
        settings_manager=SettingsManager(),
        window_manager=_FakeWindowManager(),
    )
    for _ in range(3):
        qapp.processEvents()
    return tab


def test_tab_has_customizations_manager(qapp, tmp_path, monkeypatch):
    from utils.toon_customizations_manager import ToonCustomizationsManager
    tab = _build_tab(qapp, tmp_path, monkeypatch)
    assert isinstance(tab.customizations, ToonCustomizationsManager)


def test_tab_has_no_cc_overrides_attr(qapp, tmp_path, monkeypatch):
    tab = _build_tab(qapp, tmp_path, monkeypatch)
    assert not hasattr(tab, "cc_overrides")


def test_each_badge_wired_to_manager(qapp, tmp_path, monkeypatch):
    tab = _build_tab(qapp, tmp_path, monkeypatch)
    for badge in tab.slot_badges:
        assert badge._customizations is tab.customizations


def test_open_customization_dialog_method_exists(qapp, tmp_path, monkeypatch):
    tab = _build_tab(qapp, tmp_path, monkeypatch)
    assert hasattr(tab, "_open_customization_dialog")
    assert callable(tab._open_customization_dialog)


def test_open_customization_dialog_returns_early_without_name(qapp, tmp_path, monkeypatch):
    """No toon name on slot 0 -> no crash, no dialog ever shown."""
    tab = _build_tab(qapp, tmp_path, monkeypatch)
    tab.slot_badges[0].set_toon_name(None)
    tab.slot_badges[0].set_game("ttr")
    tab._open_customization_dialog(0)


def test_open_customization_dialog_returns_early_without_game(qapp, tmp_path, monkeypatch):
    tab = _build_tab(qapp, tmp_path, monkeypatch)
    tab.slot_badges[0].set_toon_name("Flossbud")
    tab.slot_badges[0].set_game(None)
    tab._open_customization_dialog(0)
