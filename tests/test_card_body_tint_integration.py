"""Tests for body-tint widget lazy instantiation per slot."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QColor
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


def test_body_tint_widget_not_created_without_override(qapp, tmp_path, monkeypatch):
    tab = _build_tab(qapp, tmp_path, monkeypatch)
    slot = tab._compact._card_slots[0]
    assert slot.get("body_tint") is None


def test_body_tint_widget_created_when_override_set(qapp, tmp_path, monkeypatch):
    tab = _build_tab(qapp, tmp_path, monkeypatch)
    tab.toon_names[0] = "Flossbud"
    tab.slot_badges[0].set_toon_name("Flossbud")
    tab.customizations.set("ttr", "Flossbud", {"body": "#101020"})
    tab._set_card_brand_for_slot(0, "ttr", enabled=True)
    slot = tab._compact._card_slots[0]
    tint = slot.get("body_tint")
    assert tint is not None
    assert tint.color() == QColor("#101020")


def test_body_tint_widget_hidden_when_override_cleared(qapp, tmp_path, monkeypatch):
    tab = _build_tab(qapp, tmp_path, monkeypatch)
    tab.toon_names[0] = "Flossbud"
    tab.slot_badges[0].set_toon_name("Flossbud")
    tab.customizations.set("ttr", "Flossbud", {"body": "#101020"})
    tab._set_card_brand_for_slot(0, "ttr", enabled=True)
    tab.customizations.clear("ttr", "Flossbud")
    tab._set_card_brand_for_slot(0, "ttr", enabled=True)
    slot = tab._compact._card_slots[0]
    tint = slot.get("body_tint")
    # Widget kept (lazy-create, never destroy) but must be hidden.
    if tint is not None:
        assert not tint.isVisible()
