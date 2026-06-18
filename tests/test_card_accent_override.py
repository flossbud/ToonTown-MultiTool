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
    def get_active_window(self): return None


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
    """Accent override flows into the card background widget (pinwheel layout)."""
    tab = _build_tab(qapp, tmp_path, monkeypatch)
    tab.toon_names[0] = "Flossbud"
    tab.slot_badges[0].set_toon_name("Flossbud")
    tab.customizations.set("ttr", "Flossbud", {"accent": "#56c856"})
    tab._set_card_brand_for_slot(0, "ttr", enabled=True)
    bg = tab._compact._card_slots[0]["bg"]
    # _QuadCardBackground should now hold the override accent.
    assert bg._accent == QColor("#56c856")


def test_chip_qss_picks_up_accent_override(qapp, tmp_path, monkeypatch):
    """Accent override is stored on the cell dict (pinwheel has no chip QSS)."""
    tab = _build_tab(qapp, tmp_path, monkeypatch)
    tab.toon_names[0] = "Flossbud"
    tab.slot_badges[0].set_toon_name("Flossbud")
    tab.customizations.set("ttr", "Flossbud", {"accent": "#56c856"})
    tab._set_card_brand_for_slot(0, "ttr", enabled=True)
    cell = tab._compact._card_slots[0]
    # Cell accent tracks the override; the portrait frame ring also uses it.
    assert cell["accent"] == QColor("#56c856")
    assert cell["portrait_frame"]._ring == QColor("#56c856")


def test_stripe_falls_back_to_brand_when_no_override(qapp, tmp_path, monkeypatch):
    """No override: card background uses the game brand color."""
    tab = _build_tab(qapp, tmp_path, monkeypatch)
    tab.toon_names[0] = "Flossbud"
    tab.slot_badges[0].set_toon_name("Flossbud")
    # No customization set.
    tab._set_card_brand_for_slot(0, "ttr", enabled=True)
    bg = tab._compact._card_slots[0]["bg"]
    # Default TTR brand color from the theme.
    from utils.theme_manager import get_theme_colors, resolve_theme
    is_dark = resolve_theme(tab.settings_manager) == "dark"
    expected = QColor(get_theme_colors(is_dark)["game_pill_ttr"])
    assert bg._accent == expected


# ── Body-fill override tests ──────────────────────────────────────────────────

def test_body_base_helper_uses_body_when_set(qapp):
    """Pure helper: entry with body key returns the body color, not the accent."""
    from tabs.multitoon._compact_layout import _resolve_body_base
    accent = QColor("#4a7cff")
    result = _resolve_body_base({"accent": "#4a7cff", "body": "#aa3377"}, accent)
    assert result == QColor("#aa3377")


def test_body_base_helper_falls_back_to_accent(qapp):
    """Pure helper: entry without body key returns the accent color."""
    from tabs.multitoon._compact_layout import _resolve_body_base
    accent = QColor("#4a7cff")
    result = _resolve_body_base({"accent": "#4a7cff"}, accent)
    assert result == QColor("#4a7cff")


def test_card_body_override_applied_to_background(qapp, tmp_path, monkeypatch):
    """Integration: separate body color flows into _QuadCardBackground._body."""
    tab = _build_tab(qapp, tmp_path, monkeypatch)
    tab.toon_names[0] = "Flossbud"
    tab.slot_badges[0].set_toon_name("Flossbud")
    tab.customizations.set("ttr", "Flossbud", {"accent": "#4a7cff", "body": "#aa3377"})
    tab._set_card_brand_for_slot(0, "ttr", enabled=True)
    bg = tab._compact._card_slots[0]["bg"]
    # Body fill must be the override, not the accent.
    assert bg._body == QColor("#aa3377")
    # Accent (border/ring) must NOT be replaced by the body color.
    assert bg._accent == QColor("#4a7cff")


def test_card_body_falls_back_without_override(qapp, tmp_path, monkeypatch):
    """Integration: no body key means _body is None (paintEvent uses accent)."""
    tab = _build_tab(qapp, tmp_path, monkeypatch)
    tab.toon_names[0] = "Flossbud"
    tab.slot_badges[0].set_toon_name("Flossbud")
    tab.customizations.set("ttr", "Flossbud", {"accent": "#4a7cff"})
    tab._set_card_brand_for_slot(0, "ttr", enabled=True)
    bg = tab._compact._card_slots[0]["bg"]
    # No body override stored: falls back to accent in paintEvent.
    assert bg._body is None
