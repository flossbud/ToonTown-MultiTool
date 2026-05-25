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


def test_ttr_name_propagates_to_badge_via_apply_toon_names(qapp, tmp_path, monkeypatch):
    """Regression: when TTR toon names arrive via the signal-driven path,
    the badge widget must receive the name so its pencil can show."""
    tab = _build_tab(qapp, tmp_path, monkeypatch)
    tab._apply_toon_names(["Flossbud", None, "Beanie", None])
    qapp.processEvents()
    assert tab.slot_badges[0].toon_name == "Flossbud"
    assert tab.slot_badges[1].toon_name is None
    assert tab.slot_badges[2].toon_name == "Beanie"
    assert tab.slot_badges[3].toon_name is None


def test_ttr_pencil_shows_after_apply_toon_names(qapp, tmp_path, monkeypatch):
    """End-to-end: after apply_toon_names + set_card_brand for ttr,
    _can_show_pencil returns True."""
    tab = _build_tab(qapp, tmp_path, monkeypatch)
    tab._apply_toon_names(["Flossbud", None, None, None])
    tab._set_card_brand_for_slot(0, "ttr", enabled=True)
    qapp.processEvents()
    assert tab.slot_badges[0]._can_show_pencil() is True


def test_customizations_follow_toon_name_across_slots(qapp, tmp_path, monkeypatch):
    """Lock-in: customizations are keyed by toon name, not slot index.
    When a toon moves between slots, its customization moves with it."""
    tab = _build_tab(qapp, tmp_path, monkeypatch)
    # Bypass the 1s cold-start delay so stripe.set_color() applies
    # immediately during the test (otherwise set_card_brand is gated off).
    tab._compact._cold_start_in_progress = False
    # Save a customization for "Flossbud" before placing the toon anywhere.
    tab.customizations.set("ttr", "Flossbud", {"accent": "#56c856"})

    # Place "Flossbud" in slot 0.
    tab._apply_toon_names(["Flossbud", None, None, None])
    tab._set_card_brand_for_slot(0, "ttr", enabled=True)
    qapp.processEvents()

    stripe_0 = tab._compact._card_slots[0]["card_stripe"]
    from PySide6.QtGui import QColor
    assert stripe_0.target_color() == QColor("#56c856"), (
        "Slot 0 should pick up Flossbud's accent override"
    )

    # Move "Flossbud" to slot 2. Slot 0 is now empty.
    tab._apply_toon_names([None, None, "Flossbud", None])
    tab._set_card_brand_for_slot(0, "ttr", enabled=False)
    tab._set_card_brand_for_slot(2, "ttr", enabled=True)
    qapp.processEvents()

    stripe_2 = tab._compact._card_slots[2]["card_stripe"]
    assert stripe_2.target_color() == QColor("#56c856"), (
        "Slot 2 should now have Flossbud's accent (customization moved with name)"
    )
    # Slot 0 should fall back to default (empty / no override).
    assert stripe_0.target_color() != QColor("#56c856"), (
        "Slot 0 should no longer show Flossbud's accent after she moved away"
    )


def test_customizations_keyed_by_game_isolate_cc_vs_ttr(qapp, tmp_path, monkeypatch):
    """Lock-in: a CC toon and a TTR toon with the same name keep
    independent customizations (namespaced keys)."""
    tab = _build_tab(qapp, tmp_path, monkeypatch)
    # Bypass the 1s cold-start delay so stripe.set_color() applies
    # immediately during the test.
    tab._compact._cold_start_in_progress = False
    tab.customizations.set("cc", "Flossbud", {"accent": "#e74a4a"})
    tab.customizations.set("ttr", "Flossbud", {"accent": "#56c856"})

    # Slot 0 = CC Flossbud
    tab._apply_toon_names(["Flossbud", None, None, None])
    tab._set_card_brand_for_slot(0, "cc", enabled=True)
    qapp.processEvents()

    from PySide6.QtGui import QColor
    stripe_0 = tab._compact._card_slots[0]["card_stripe"]
    assert stripe_0.target_color() == QColor("#e74a4a"), (
        "CC slot must show CC-namespaced override, not TTR's"
    )

    # Now treat slot 0 as TTR Flossbud
    tab._set_card_brand_for_slot(0, "ttr", enabled=True)
    qapp.processEvents()
    assert stripe_0.target_color() == QColor("#56c856"), (
        "Same slot, same name, but TTR game tag picks up TTR override"
    )
