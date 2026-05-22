"""Regression tests: CC badge state must clear when the service stops or
a CC window disappears. Without these, the badge keeps painting the stale
CC silhouette after the toon is no longer in play."""

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
        return list(self.ttr_window_ids)

    def clear_window_ids(self):
        self.ttr_window_ids = []

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

    return MultitoonTab(
        settings_manager=SettingsManager(),
        window_manager=_FakeWindowManager(),
    )


def _paint_cc_on_slot(tab, slot_idx: int, name: str = "Flossbud"):
    """Apply CC paint to a slot the way _apply_cc_toon_info would."""
    badge = tab.slot_badges[slot_idx]
    badge.set_toon_name(name)
    badge.set_cc_auto_species("DOG")
    badge.set_cc_mode(
        skin_rgb=(0.84, 0.19, 0.19),
        accent_rgb=(0.5, 0.5, 0.5),
        gloves_rgb=(1.0, 1.0, 1.0),
        emoji="🐶",
    )
    assert badge._cc_mode is True, "precondition: CC paint applied"


def test_disable_all_toon_controls_clears_cc_paint(qt_app, monkeypatch, tmp_path):
    """When the service stops, every slot's CC paint must clear."""
    tab = _make_tab(monkeypatch, tmp_path)
    _paint_cc_on_slot(tab, 0, "Flossbud")
    _paint_cc_on_slot(tab, 1, "Kubuntu")

    tab.disable_all_toon_controls()

    for idx in (0, 1):
        b = tab.slot_badges[idx]
        assert b._cc_mode is False, f"slot {idx} CC paint still on after service stop"
        assert b._toon_name is None, f"slot {idx} toon name still set after service stop"
        assert b._cc_auto_species is None, f"slot {idx} auto species still set after service stop"


def test_update_toon_controls_clears_cc_paint_when_window_disappears(
    qt_app, monkeypatch, tmp_path,
):
    """When a CC window closes, the slot that lost its window must clear
    its CC paint instead of leaving the stale silhouette."""
    tab = _make_tab(monkeypatch, tmp_path)
    # Simulate a previous state with one window present at slot 0.
    tab._last_window_ids = [12345]
    _paint_cc_on_slot(tab, 0, "Flossbud")

    # New poll: window list is now empty (game closed).
    tab.update_toon_controls([])

    b = tab.slot_badges[0]
    assert b._cc_mode is False, "slot 0 CC paint still on after window disappeared"
    assert b._toon_name is None
    assert b._cc_auto_species is None


def test_manual_refresh_clears_cc_paint(qt_app, monkeypatch, tmp_path):
    """Manual refresh resets per-slot data and must also clear CC paint."""
    tab = _make_tab(monkeypatch, tmp_path)
    _paint_cc_on_slot(tab, 0, "Flossbud")

    tab.manual_refresh()

    b = tab.slot_badges[0]
    assert b._cc_mode is False, "slot 0 CC paint still on after manual refresh"
    assert b._toon_name is None
    assert b._cc_auto_species is None
