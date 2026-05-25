"""Tests for accent override flowing into the card stripe + chip."""

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
    # Bypass the 1s cold-start delay so stripe.set_color() applies
    # immediately during the test.
    tab._compact._cold_start_in_progress = False
    return tab


def test_stripe_picks_up_accent_override(qapp, tmp_path, monkeypatch):
    tab = _build_tab(qapp, tmp_path, monkeypatch)
    tab.toon_names[0] = "Flossbud"
    tab.slot_badges[0].set_toon_name("Flossbud")
    tab.customizations.set("ttr", "Flossbud", {"accent": "#56c856"})
    tab._set_card_brand_for_slot(0, "ttr", enabled=True)
    stripe = tab._compact._card_slots[0]["card_stripe"]
    # _CardStripe should now hold the override color.
    assert stripe.target_color() == QColor("#56c856")


def test_chip_qss_picks_up_accent_override(qapp, tmp_path, monkeypatch):
    tab = _build_tab(qapp, tmp_path, monkeypatch)
    tab.toon_names[0] = "Flossbud"
    tab.slot_badges[0].set_toon_name("Flossbud")
    tab.customizations.set("ttr", "Flossbud", {"accent": "#56c856"})
    tab._apply_chip_for_slot(0, "ttr")
    qss = tab.game_badges[0].styleSheet()
    assert "#56c856" in qss
    assert "#4A8FE7" not in qss  # default TTR brand replaced


def test_stripe_falls_back_to_brand_when_no_override(qapp, tmp_path, monkeypatch):
    tab = _build_tab(qapp, tmp_path, monkeypatch)
    tab.toon_names[0] = "Flossbud"
    tab.slot_badges[0].set_toon_name("Flossbud")
    # No customization set.
    tab._set_card_brand_for_slot(0, "ttr", enabled=True)
    stripe = tab._compact._card_slots[0]["card_stripe"]
    # Default TTR brand color from the theme.
    from utils.theme_manager import get_theme_colors, resolve_theme
    is_dark = resolve_theme(tab.settings_manager) == "dark"
    expected = QColor(get_theme_colors(is_dark)["game_pill_ttr"])
    assert stripe.target_color() == expected
